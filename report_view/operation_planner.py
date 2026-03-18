import copy
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .query_preprocessor import PreprocessedQuestion, QueryPreprocessor
from .report_context_memory import ReportContextMemory
from .result_models import CandidateInterpretation, InterpretationResult, ProjectSchemaContext, QueryPlan
from .text_utils import contains_hint_tokens, normalize_text, tokenize_text


MATERIAL_VALUES = ("pvc", "pead", "pba", "fofo", "ferro", "aco", "fibrocimento")
LOCATION_INTRO_PATTERNS = (
    r"\bem\s+([a-z0-9_ ]{2,50})",
    r"\bde\s+([a-z0-9_ ]{2,50})$",
    r"\bno municipio de\s+([a-z0-9_ ]{2,50})",
    r"\bna cidade de\s+([a-z0-9_ ]{2,50})",
    r"\bno bairro\s+([a-z0-9_ ]{2,50})",
)
FOLLOW_UP_PREFIXES = ("agora", "e ", "e de", "so", "somente", "apenas", "usa", "mostra", "troca", "mantem")
GROUP_HINTS = {
    "municipio": ("municipio", "cidade"),
    "bairro": ("bairro", "setor"),
    "localidade": ("localidade", "comunidade", "povoado"),
}
SUBJECT_HINTS = {
    "rede": ("rede", "adutora", "ramal", "tubulacao", "trecho"),
    "ligacao": ("ligacao", "ligacoes", "ponto", "pontos"),
    "lote": ("lote", "lotes", "parcela", "parcelas"),
}
LOCATION_REJECT_TOKENS = {
    "adutora",
    "bairro",
    "cidade",
    "diametro",
    "dn",
    "extensao",
    "ligacoes",
    "ligacao",
    "material",
    "municipio",
    "por",
    "quantidade",
    "rede",
    "trecho",
}


@dataclass
class LayerPlanningCandidate:
    layer_id: str
    layer_name: str
    score: float
    reasons: List[str] = field(default_factory=list)


@dataclass
class PlanningBrief:
    original_question: str
    normalized_question: str
    rewritten_question: str
    intent_label: str
    metric_hint: str
    subject_hint: str
    group_hint: str
    attribute_hint: str
    value_mode: str
    top_n: Optional[int]
    follow_up: bool
    extracted_filters: List[Dict[str, str]] = field(default_factory=list)
    likely_layers: List[LayerPlanningCandidate] = field(default_factory=list)
    alternate_questions: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


class OperationPlanner:
    def __init__(self):
        self.preprocessor = QueryPreprocessor()

    def build_brief(
        self,
        question: str,
        schema_context: ProjectSchemaContext,
        context_memory: Optional[ReportContextMemory] = None,
    ) -> PlanningBrief:
        preprocessed = self.preprocessor.preprocess(question)
        follow_up = self._is_follow_up(preprocessed, context_memory)
        extracted_filters = self._extract_filters(preprocessed.corrected_text or question)
        likely_layers = self._rank_layers(preprocessed, extracted_filters, schema_context, context_memory)
        alternate_questions = self._build_alternate_questions(
            question,
            preprocessed,
            extracted_filters,
            likely_layers,
            context_memory,
        )
        return PlanningBrief(
            original_question=question,
            normalized_question=preprocessed.corrected_text or preprocessed.normalized_text,
            rewritten_question=preprocessed.rewritten_text,
            intent_label=preprocessed.intent_label,
            metric_hint=preprocessed.metric_hint,
            subject_hint=preprocessed.subject_hint,
            group_hint=preprocessed.group_hint,
            attribute_hint=preprocessed.attribute_hint,
            value_mode=preprocessed.value_mode,
            top_n=preprocessed.top_n,
            follow_up=follow_up,
            extracted_filters=extracted_filters,
            likely_layers=likely_layers,
            alternate_questions=alternate_questions,
            notes=list(preprocessed.notes or []),
        )

    def candidate_questions(self, brief: PlanningBrief) -> List[str]:
        candidates = [brief.original_question]
        for question in [brief.rewritten_question] + list(brief.alternate_questions or []):
            question = (question or "").strip()
            if question and normalize_text(question) not in {normalize_text(item) for item in candidates}:
                candidates.append(question)
        return candidates[:4]

    def refine_interpretation(
        self,
        interpretation: InterpretationResult,
        brief: PlanningBrief,
        schema_context: ProjectSchemaContext,
        context_memory: Optional[ReportContextMemory] = None,
    ) -> InterpretationResult:
        if interpretation is None:
            return interpretation

        result = copy.deepcopy(interpretation)
        if result.plan is not None:
            self._annotate_plan(result.plan, brief, schema_context, context_memory)

        ranked_candidates: List[Tuple[float, CandidateInterpretation]] = []
        for candidate in self._collect_candidates(result):
            if candidate.plan is None:
                continue
            self._annotate_plan(candidate.plan, brief, schema_context, context_memory)
            score = self._plan_score(candidate.plan, brief, schema_context, context_memory)
            label = self._semantic_label(candidate.plan, brief, schema_context)
            ranked_candidates.append(
                (
                    score,
                    CandidateInterpretation(
                        label=label,
                        reason=self._merge_reasons(candidate.reason, self._semantic_reason(candidate.plan, brief, schema_context)),
                        confidence=max(float(candidate.confidence or 0.0), score),
                        plan=candidate.plan,
                    ),
                )
            )

        if ranked_candidates:
            ranked_candidates.sort(key=lambda item: (item[0], item[1].label.lower()), reverse=True)
            result.candidate_interpretations = [item[1] for item in ranked_candidates[:4]]
            best_score, best_candidate = ranked_candidates[0]
            if result.plan is None or best_score >= float(result.confidence or 0.0) + 0.05:
                result.plan = copy.deepcopy(best_candidate.plan)
                result.confidence = best_score
                if result.status in {"unsupported", "ambiguous"} and best_score >= 0.72:
                    result.status = "confirm"
                    result.needs_confirmation = True
                    result.message = ""
                    result.clarification_question = f"Voce quis dizer {best_candidate.label.lower()}?"
            else:
                result.confidence = max(float(result.confidence or 0.0), best_score)

        if result.plan is not None and result.status in {"ok", "confirm"}:
            semantic_label = self._semantic_label(result.plan, brief, schema_context)
            if float(result.confidence or 0.0) < 0.78 and not result.needs_confirmation:
                result.status = "confirm"
                result.needs_confirmation = True
                result.clarification_question = f"Voce quis dizer {semantic_label.lower()}?"
            elif result.status == "confirm" and not result.clarification_question:
                result.clarification_question = f"Voce quis dizer {semantic_label.lower()}?"
        return result

    def choose_best_interpretation(
        self,
        results: Sequence[InterpretationResult],
        brief: PlanningBrief,
        schema_context: ProjectSchemaContext,
        context_memory: Optional[ReportContextMemory] = None,
    ) -> InterpretationResult:
        if not results:
            return InterpretationResult(status="unsupported", message="Nao foi possivel interpretar essa pergunta.")
        scored: List[Tuple[float, InterpretationResult]] = []
        for item in results:
            refined = self.refine_interpretation(item, brief, schema_context, context_memory=context_memory)
            score = float(refined.confidence or 0.0)
            if refined.status == "ok":
                score += 0.08
            elif refined.status == "confirm":
                score += 0.03
            elif refined.status == "ambiguous":
                score -= 0.02
            else:
                score -= 0.2
            if refined.plan is not None:
                score += self._plan_score(refined.plan, brief, schema_context, context_memory) * 0.25
            scored.append((score, refined))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    def candidate_layer_ids(self, brief: PlanningBrief) -> List[str]:
        return [item.layer_id for item in brief.likely_layers[:4] if item.layer_id]

    def _annotate_plan(
        self,
        plan: QueryPlan,
        brief: PlanningBrief,
        schema_context: ProjectSchemaContext,
        context_memory: Optional[ReportContextMemory],
    ) -> None:
        planning_trace = dict(plan.planning_trace or {})
        planning_trace.update(
            {
                "planner_intent": brief.intent_label,
                "planner_metric_hint": brief.metric_hint,
                "planner_subject_hint": brief.subject_hint,
                "planner_group_hint": brief.group_hint,
                "planner_attribute_hint": brief.attribute_hint,
                "planner_filters": list(brief.extracted_filters or []),
                "planner_follow_up": brief.follow_up,
                "planner_alternate_questions": list(brief.alternate_questions or []),
            }
        )
        if context_memory is not None and context_memory.last_plan() is not None:
            planning_trace["planner_has_context"] = True
        plan.planning_trace = planning_trace
        if not plan.rewritten_question and brief.rewritten_question:
            plan.rewritten_question = brief.rewritten_question
        if not plan.intent_label and brief.intent_label:
            plan.intent_label = brief.intent_label
        if not plan.understanding_text:
            plan.understanding_text = self._semantic_label(plan, brief, schema_context)

    def _is_follow_up(
        self,
        preprocessed: PreprocessedQuestion,
        context_memory: Optional[ReportContextMemory],
    ) -> bool:
        text = normalize_text(preprocessed.corrected_text or preprocessed.original_text)
        if not text or context_memory is None or context_memory.last_plan() is None:
            return False
        if any(text.startswith(prefix) for prefix in FOLLOW_UP_PREFIXES):
            return True
        tokens = tokenize_text(text)
        return len(tokens) <= 4 and preprocessed.intent_label in {"contexto", "filtro_simples", "filtro_composto"}

    def _extract_filters(self, question: str) -> List[Dict[str, str]]:
        normalized = normalize_text(question)
        filters: List[Dict[str, str]] = []

        for match in re.finditer(r"\bdn\s+(\d{2,4})\b", normalized):
            filters.append({"kind": "diameter", "value": match.group(1), "source_text": match.group(0)})
        if not any(item["kind"] == "diameter" for item in filters):
            for match in re.finditer(r"\b(\d{2,4})\s*mm\b", normalized):
                filters.append({"kind": "diameter", "value": match.group(1), "source_text": match.group(0)})

        for material in MATERIAL_VALUES:
            if re.search(rf"\b{re.escape(material)}\b", normalized):
                filters.append({"kind": "material", "value": material.upper(), "source_text": material})

        location = self._extract_location(normalized)
        if location:
            filters.append({"kind": "location", "value": location.title(), "source_text": location})
        return filters

    def _extract_location(self, normalized_question: str) -> str:
        for pattern in LOCATION_INTRO_PATTERNS:
            match = re.search(pattern, normalized_question)
            if not match:
                continue
            value = normalize_text(match.group(1))
            value = re.sub(
                r"\b(dn\s+\d{2,4}|\d{2,4}\s*mm|pvc|pead|fofo|ferro|aco|fibrocimento|por\s+\w+|qual\s+\w+)\b",
                "",
                value,
            )
            value = re.sub(r"\s+", " ", value).strip()
            if value and len(value) >= 3 and value not in LOCATION_REJECT_TOKENS:
                return value
        return ""

    def _rank_layers(
        self,
        preprocessed: PreprocessedQuestion,
        extracted_filters: Sequence[Dict[str, str]],
        schema_context: ProjectSchemaContext,
        context_memory: Optional[ReportContextMemory],
    ) -> List[LayerPlanningCandidate]:
        candidates: List[LayerPlanningCandidate] = []
        last_plan = context_memory.last_plan() if context_memory is not None else None
        for layer in schema_context.layers:
            score = 0.0
            reasons: List[str] = []

            if preprocessed.subject_hint:
                if preprocessed.subject_hint in normalize_text(" ".join(layer.entity_terms + [layer.name])):
                    score += 0.34
                    reasons.append("camada alinhada ao assunto")
                elif preprocessed.subject_hint == "rede" and layer.geometry_type == "line":
                    score += 0.22
                    reasons.append("camada linear compativel com rede")

            if preprocessed.metric_hint and layer.supports_metric(preprocessed.metric_hint):
                score += 0.24
                reasons.append("camada suporta a metrica")

            if preprocessed.group_hint and any(
                contains_hint_tokens(field_name, GROUP_HINTS.get(preprocessed.group_hint, (preprocessed.group_hint,)))
                for field_name in layer.location_field_names + layer.categorical_field_names
            ):
                score += 0.18
                reasons.append("camada possui campo de agrupamento compativel")

            if preprocessed.attribute_hint == "diameter" and any(
                contains_hint_tokens(field_name, ("dn", "diametro", "diam", "bitola"))
                for field_name in layer.filter_field_names + layer.numeric_field_names
            ):
                score += 0.16
                reasons.append("camada possui campo de diametro")

            if preprocessed.attribute_hint == "material" and any(
                contains_hint_tokens(field_name, ("material", "classe", "tipo"))
                for field_name in layer.filter_field_names + layer.categorical_field_names
            ):
                score += 0.16
                reasons.append("camada possui campo de material")

            for filter_item in extracted_filters:
                if filter_item["kind"] == "location" and layer.location_field_names:
                    score += 0.09
                    reasons.append("camada possui filtro geografico")
                elif filter_item["kind"] == "diameter" and any(
                    contains_hint_tokens(field_name, ("dn", "diametro", "diam", "bitola"))
                    for field_name in layer.filter_field_names + layer.numeric_field_names
                ):
                    score += 0.08
                elif filter_item["kind"] == "material" and any(
                    contains_hint_tokens(field_name, ("material", "classe", "tipo"))
                    for field_name in layer.filter_field_names + layer.categorical_field_names
                ):
                    score += 0.08

            question_text = normalize_text(
                " ".join(
                    filter(
                        None,
                        [
                            preprocessed.corrected_text,
                            preprocessed.subject_hint,
                            preprocessed.group_hint,
                            preprocessed.metric_hint,
                            preprocessed.attribute_hint,
                        ],
                    )
                )
            )
            overlap = len(set(tokenize_text(question_text)) & set(tokenize_text(layer.search_text)))
            score += min(0.18, overlap * 0.03)

            if last_plan is not None and layer.layer_id in {
                last_plan.target_layer_id,
                last_plan.source_layer_id,
                last_plan.boundary_layer_id,
            }:
                score += 0.10
                reasons.append("aproveitando contexto recente")

            if score > 0:
                candidates.append(
                    LayerPlanningCandidate(
                        layer_id=layer.layer_id,
                        layer_name=layer.name,
                        score=round(score, 4),
                        reasons=reasons,
                    )
                )

        candidates.sort(key=lambda item: (item.score, item.layer_name.lower()), reverse=True)
        return candidates[:5]

    def _build_alternate_questions(
        self,
        question: str,
        preprocessed: PreprocessedQuestion,
        extracted_filters: Sequence[Dict[str, str]],
        likely_layers: Sequence[LayerPlanningCandidate],
        context_memory: Optional[ReportContextMemory],
    ) -> List[str]:
        variants: List[str] = []
        rewritten = (preprocessed.rewritten_text or "").strip()
        if rewritten and normalize_text(rewritten) != normalize_text(question):
            variants.append(rewritten)

        if self._is_follow_up(preprocessed, context_memory):
            base = self._base_context_phrase(context_memory)
            merged = self._merge_follow_up(base, preprocessed.corrected_text or question)
            if merged and normalize_text(merged) != normalize_text(question):
                variants.append(merged)

        if preprocessed.subject_hint == "rede" and preprocessed.metric_hint == "length":
            location = next((item["value"] for item in extracted_filters if item["kind"] == "location"), "")
            diameter = next((item["value"] for item in extracted_filters if item["kind"] == "diameter"), "")
            material = next((item["value"] for item in extracted_filters if item["kind"] == "material"), "")
            semantic_parts = ["quantos metros de rede"]
            if diameter:
                semantic_parts.append(f"dn {diameter}")
            if material:
                semantic_parts.append(f"de {material}")
            if location:
                semantic_parts.append(f"em {location}")
            variants.append(" ".join(semantic_parts))

        top_layer = likely_layers[0].layer_name if likely_layers else ""
        if top_layer and preprocessed.subject_hint and normalize_text(top_layer) not in normalize_text(question):
            variants.append(f"{preprocessed.rewritten_text or question} na camada {top_layer}")

        deduped: List[str] = []
        seen = set()
        for item in variants:
            normalized = normalize_text(item)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(item)
        return deduped[:3]

    def _base_context_phrase(self, context_memory: Optional[ReportContextMemory]) -> str:
        if context_memory is None:
            return ""
        last_plan = context_memory.last_plan()
        if last_plan is None:
            return ""
        if last_plan.understanding_text:
            return last_plan.understanding_text
        if last_plan.rewritten_question:
            return last_plan.rewritten_question
        return last_plan.original_question

    def _merge_follow_up(self, base_question: str, follow_up_question: str) -> str:
        base = normalize_text(base_question)
        follow_up = normalize_text(follow_up_question)
        if not base:
            return follow_up_question
        if follow_up.startswith("e "):
            follow_up = follow_up[2:].strip()
        if any(token in follow_up for token in ("pizza", "barra", "linha", "grafico")):
            return f"{base} {follow_up}"
        if re.search(r"\b(top\s+\d+|municipio|bairro|localidade|cidade)\b", follow_up):
            return f"{base} {follow_up}"
        return f"{base} com {follow_up}"

    def _collect_candidates(self, interpretation: InterpretationResult) -> List[CandidateInterpretation]:
        candidates: List[CandidateInterpretation] = list(interpretation.candidate_interpretations or [])
        if interpretation.plan is not None:
            candidates.append(
                CandidateInterpretation(
                    label="interpretacao principal",
                    reason=interpretation.message or "",
                    confidence=float(interpretation.confidence or 0.0),
                    plan=copy.deepcopy(interpretation.plan),
                )
            )
        return candidates

    def _plan_score(
        self,
        plan: QueryPlan,
        brief: PlanningBrief,
        schema_context: ProjectSchemaContext,
        context_memory: Optional[ReportContextMemory],
    ) -> float:
        score = 0.35
        layer_ids = {
            plan.target_layer_id,
            plan.source_layer_id,
            plan.boundary_layer_id,
        }
        for index, candidate in enumerate(brief.likely_layers[:4]):
            if candidate.layer_id in layer_ids:
                score += max(0.22 - (index * 0.04), 0.08)
                break

        if brief.metric_hint:
            if brief.metric_hint == plan.metric.operation:
                score += 0.16
            elif brief.metric_hint == "length" and plan.metric.use_geometry and plan.metric.operation == "length":
                score += 0.16
            elif brief.metric_hint == "count" and plan.metric.operation == "count":
                score += 0.12

        if brief.group_hint:
            plan_group_text = normalize_text(" ".join([plan.group_field, plan.group_label, plan.boundary_layer_name]))
            if any(token in plan_group_text for token in GROUP_HINTS.get(brief.group_hint, (brief.group_hint,))):
                score += 0.12

        if brief.attribute_hint == "diameter":
            diameter_text = normalize_text(
                " ".join(
                    [plan.metric.field or "", plan.metric.field_label or "", plan.group_field]
                    + [filter_item.field for filter_item in plan.filters]
                )
            )
            if any(token in diameter_text for token in ("dn", "diam", "diametro", "bitola")):
                score += 0.12

        if brief.attribute_hint == "material":
            material_text = normalize_text(
                " ".join(
                    [plan.metric.field or "", plan.metric.field_label or "", plan.group_field]
                    + [filter_item.field for filter_item in plan.filters]
                )
            )
            if any(token in material_text for token in ("material", "classe", "tipo")):
                score += 0.12

        for filter_item in brief.extracted_filters:
            if any(normalize_text(filter_item["value"]) == normalize_text(spec.value) for spec in plan.filters):
                score += 0.08

        if brief.follow_up and context_memory is not None and context_memory.last_plan() is not None:
            last_plan = context_memory.last_plan()
            if last_plan is not None and any(
                layer_id in {last_plan.target_layer_id, last_plan.source_layer_id, last_plan.boundary_layer_id}
                for layer_id in layer_ids
            ):
                score += 0.06

        return min(0.99, score)

    def _semantic_label(
        self,
        plan: QueryPlan,
        brief: PlanningBrief,
        schema_context: ProjectSchemaContext,
    ) -> str:
        metric_label = {
            "count": "Quantidade",
            "sum": "Total",
            "avg": "Media",
            "length": "Extensao total",
            "area": "Area total",
            "max": "Maior valor",
            "min": "Menor valor",
        }.get(plan.metric.operation, "Consulta")
        entity = brief.subject_hint or self._entity_from_plan(plan, schema_context) or "dados"
        entity_label = {
            "rede": "da rede",
            "ligacao": "das ligacoes",
            "lote": "dos lotes",
        }.get(entity, f"de {entity}")

        if plan.intent == "value_insight":
            attribute = brief.attribute_hint or normalize_text(plan.metric.field_label or plan.metric.field or "valor")
            attribute_label = {
                "diameter": "o maior diametro",
                "material": "o material",
            }.get(attribute, metric_label.lower())
            return self._append_filters(f"{attribute_label} {entity_label}", plan.filters)

        base = metric_label
        if plan.metric.operation in {"length", "area", "sum", "avg", "count"}:
            base = f"{base} {entity_label}"
        if plan.group_label:
            base = f"{base} por {normalize_text(plan.group_label)}"
        return self._append_filters(base, plan.filters)

    def _append_filters(self, base_label: str, filters) -> str:
        fragments = []
        for filter_spec in filters[:3]:
            value = str(filter_spec.value or "").strip()
            if not value:
                continue
            if filter_spec.layer_role == "boundary":
                fragments.append(f"em {value}")
            elif contains_hint_tokens(filter_spec.field, ("dn", "diametro", "bitola")):
                fragments.append(f"DN {value}")
            else:
                fragments.append(f"{normalize_text(filter_spec.field)} {value}")
        text = base_label.strip()
        if fragments:
            text = f"{text} com {' | '.join(fragments)}"
        return re.sub(r"\s+", " ", text).strip().capitalize()

    def _semantic_reason(
        self,
        plan: QueryPlan,
        brief: PlanningBrief,
        schema_context: ProjectSchemaContext,
    ) -> str:
        reasons = []
        if brief.metric_hint and brief.metric_hint == plan.metric.operation:
            reasons.append("metrica alinhada")
        if brief.group_hint and any(token in normalize_text(plan.group_label or plan.group_field) for token in GROUP_HINTS.get(brief.group_hint, ())):
            reasons.append("agrupamento alinhado")
        if brief.extracted_filters and plan.filters:
            reasons.append("filtros reconhecidos")
        if not reasons:
            reasons.append("plano semantico compativel")
        return ", ".join(reasons)

    def _entity_from_plan(self, plan: QueryPlan, schema_context: ProjectSchemaContext) -> str:
        for layer_id in (plan.target_layer_id, plan.source_layer_id, plan.boundary_layer_id):
            layer = schema_context.layer_by_id(layer_id)
            if layer is None:
                continue
            for term in ("rede", "ligacao", "lote", "bairro", "municipio"):
                if term in layer.entity_terms:
                    return term
        return normalize_text(plan.target_layer_name or plan.source_layer_name or plan.boundary_layer_name or "")

    def _merge_reasons(self, left: str, right: str) -> str:
        values = [item.strip() for item in [left, right] if item and item.strip()]
        unique: List[str] = []
        for item in values:
            if item not in unique:
                unique.append(item)
        return "; ".join(unique)
