import copy
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .domain_packs import DEFAULT_DOMAIN_PACK, DomainPack, ProjectPack
from .query_preprocessor import PreprocessedQuestion, QueryPreprocessor
from .report_context_memory import ReportContextMemory
from .report_logging import log_info
from .result_models import CandidateInterpretation, InterpretationResult, ProjectSchemaContext, QueryPlan
from .schema_linker_service import (
    SchemaLinkFieldCandidate,
    SchemaLinkLayerCandidate,
    SchemaLinkResult,
    SchemaLinkValueCandidate,
)
from .text_utils import contains_hint_tokens, normalize_compact, normalize_text, tokenize_text


MATERIAL_VALUES = DEFAULT_DOMAIN_PACK.material_terms
SERVICE_VALUES = DEFAULT_DOMAIN_PACK.service_terms
STATUS_VALUES = DEFAULT_DOMAIN_PACK.status_terms
WATER_TERMS = DEFAULT_DOMAIN_PACK.water_terms
SEWER_TERMS = DEFAULT_DOMAIN_PACK.sewer_terms
NETWORK_TERMS = DEFAULT_DOMAIN_PACK.network_terms
CONNECTION_TERMS = DEFAULT_DOMAIN_PACK.connection_terms
LENGTH_TERMS = ("extensao", "comprimento", "metragem", "metro", "metros", "tamanho")
COUNT_TERMS = ("quantidade", "quantos", "quantas", "numero", "número", "total")
METRIC_HINTS = {"sum", "avg", "max", "min"}
LOCATION_INTRO_PATTERNS = (
    r"\bem\s+([a-z0-9_ ]{2,50})",
    r"\bde\s+([a-z0-9_ ]{2,50})$",
    r"\bno municipio de\s+([a-z0-9_ ]{2,50})",
    r"\bna cidade de\s+([a-z0-9_ ]{2,50})",
    r"\bno bairro\s+([a-z0-9_ ]{2,50})",
)
FOLLOW_UP_PREFIXES = ("agora", "e ", "e de", "so", "somente", "apenas", "usa", "mostra", "troca", "mantem")
GROUP_HINTS = DEFAULT_DOMAIN_PACK.group_hints
SUBJECT_HINTS = DEFAULT_DOMAIN_PACK.subject_hints
LOCATION_REJECT_TOKENS = set(DEFAULT_DOMAIN_PACK.location_reject_tokens)


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
    group_phrase: str
    attribute_hint: str
    excel_mode: str
    value_mode: str
    top_n: Optional[int]
    follow_up: bool
    extracted_filters: List[Dict[str, str]] = field(default_factory=list)
    likely_layers: List[LayerPlanningCandidate] = field(default_factory=list)
    linked_layers: List[SchemaLinkLayerCandidate] = field(default_factory=list)
    linked_fields: List[SchemaLinkFieldCandidate] = field(default_factory=list)
    linked_values: List[SchemaLinkValueCandidate] = field(default_factory=list)
    alternate_questions: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


class OperationPlanner:
    def __init__(
        self,
        domain_pack: Optional[DomainPack] = None,
        project_pack: Optional[ProjectPack] = None,
    ):
        self.domain_pack = domain_pack or DEFAULT_DOMAIN_PACK
        self.project_pack = project_pack
        self.preprocessor = QueryPreprocessor(self.domain_pack, project_pack)
        self.entity_priority_terms = tuple(self.domain_pack.entity_priority_terms or ())
        self.semantic_metric_labels = dict(self.domain_pack.semantic_metric_labels or {})
        self.entity_label_suffixes = dict(self.domain_pack.entity_label_suffixes or {})
        self.value_insight_labels = dict(self.domain_pack.value_insight_labels or {})
        self.derived_intent_labels = dict(self.domain_pack.derived_intent_labels or {})

    def build_brief(
        self,
        question: str,
        schema_context: ProjectSchemaContext,
        context_memory: Optional[ReportContextMemory] = None,
        schema_link_result: Optional[SchemaLinkResult] = None,
    ) -> PlanningBrief:
        preprocessed = self.preprocessor.preprocess(question)
        follow_up = self._is_follow_up(preprocessed, context_memory)
        extracted_filters = self._extract_filters(preprocessed.corrected_text or question)
        likely_layers = self._rank_layers(
            preprocessed,
            extracted_filters,
            schema_context,
            context_memory,
            schema_link_result,
        )
        alternate_questions = self._build_alternate_questions(
            question,
            preprocessed,
            extracted_filters,
            likely_layers,
            context_memory,
        )
        log_info(
            "[Relatorios][debug][planner] "
            f"question='{question}' corrected='{preprocessed.corrected_text}' "
            f"extracted_filters={extracted_filters} "
            f"explicit_locations={self._explicit_location_values_from_filters(extracted_filters)}"
        )
        return PlanningBrief(
            original_question=question,
            normalized_question=preprocessed.corrected_text or preprocessed.normalized_text,
            rewritten_question=preprocessed.rewritten_text,
            intent_label=preprocessed.intent_label,
            metric_hint=preprocessed.metric_hint,
            subject_hint=preprocessed.subject_hint,
            group_hint=preprocessed.group_hint,
            group_phrase=preprocessed.group_phrase,
            attribute_hint=preprocessed.attribute_hint,
            excel_mode=preprocessed.excel_mode,
            value_mode=preprocessed.value_mode,
            top_n=preprocessed.top_n,
            follow_up=follow_up,
            extracted_filters=extracted_filters,
            likely_layers=likely_layers,
            linked_layers=list((schema_link_result.layer_candidates if schema_link_result is not None else [])[:5]),
            linked_fields=list((schema_link_result.field_candidates if schema_link_result is not None else [])[:8]),
            linked_values=list((schema_link_result.value_candidates if schema_link_result is not None else [])[:8]),
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
        layer_ids = [item.layer_id for item in brief.likely_layers[:4] if item.layer_id]
        for item in brief.linked_layers[:4]:
            if item.layer_id and item.layer_id not in layer_ids:
                layer_ids.append(item.layer_id)
        return layer_ids

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
                "planner_group_phrase": brief.group_phrase,
                "planner_attribute_hint": brief.attribute_hint,
                "planner_excel_mode": brief.excel_mode,
                "planner_filters": list(brief.extracted_filters or []),
                "planner_follow_up": brief.follow_up,
                "planner_alternate_questions": list(brief.alternate_questions or []),
                "planner_linked_layers": [item.layer_name for item in brief.linked_layers[:4]],
                "planner_linked_fields": [f"{item.layer_name}:{item.field_label or item.field_name}" for item in brief.linked_fields[:4]],
                "planner_linked_values": [f"{item.layer_name}:{item.field_label or item.field_name}={item.value}" for item in brief.linked_values[:4]],
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
        if preprocessed.subject_hint:
            return False
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

        for canonical_status, variants in STATUS_VALUES.items():
            if any(re.search(rf"\b{re.escape(variant)}\b", normalized) for variant in variants):
                filters.append(
                    {
                        "kind": "status",
                        "value": canonical_status.title(),
                        "source_text": canonical_status,
                    }
                )
                break

        for service_value in SERVICE_VALUES:
            if re.search(rf"\b{re.escape(service_value)}\b", normalized):
                filters.append(
                    {
                        "kind": "generic",
                        "value": service_value.title(),
                        "source_text": service_value,
                    }
                )

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
        schema_link_result: Optional[SchemaLinkResult],
    ) -> List[LayerPlanningCandidate]:
        candidates: List[LayerPlanningCandidate] = []
        last_plan = context_memory.last_plan() if context_memory is not None else None
        use_recent_context = self._is_follow_up(preprocessed, context_memory)
        followup_has_new_filter_signal = any(
            item.get("kind") in {"location", "status", "material", "diameter", "generic"}
            for item in (extracted_filters or [])
        )
        link_score_map = {
            item.layer_id: float(item.score or 0.0)
            for item in (schema_link_result.layer_candidates if schema_link_result is not None else [])
        }
        linked_field_counts: Dict[str, int] = {}
        linked_value_counts: Dict[str, int] = {}
        if schema_link_result is not None:
            for item in schema_link_result.field_candidates:
                linked_field_counts[item.layer_id] = linked_field_counts.get(item.layer_id, 0) + 1
            for item in schema_link_result.value_candidates:
                linked_value_counts[item.layer_id] = linked_value_counts.get(item.layer_id, 0) + 1
        for layer in schema_context.layers:
            score = 0.0
            reasons: List[str] = []
            layer_name_score, layer_name_reasons = self._score_layer_name_alignment(preprocessed, layer)
            score += layer_name_score
            reasons.extend(layer_name_reasons)

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

            group_tokens = tuple(token for token in tokenize_text(preprocessed.group_phrase) if token)
            if group_tokens and any(
                contains_hint_tokens(field_name, group_tokens)
                for field_name in layer.filter_field_names + layer.categorical_field_names + layer.location_field_names
            ):
                score += 0.14
                reasons.append("camada possui campo proximo ao agrupamento pedido")

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
                elif filter_item["kind"] == "status" and any(
                    contains_hint_tokens(field_name, ("status", "situacao", "sit"))
                    for field_name in layer.filter_field_names + layer.categorical_field_names
                ):
                    score += 0.10
                elif filter_item["kind"] == "generic" and contains_hint_tokens(layer.search_text, (normalize_text(filter_item["value"]),)):
                    score += 0.06

            question_text = normalize_text(
                " ".join(
                    filter(
                        None,
                        [
                            preprocessed.corrected_text,
                            preprocessed.subject_hint,
                            preprocessed.group_hint,
                            preprocessed.group_phrase,
                            preprocessed.metric_hint,
                            preprocessed.attribute_hint,
                        ],
                    )
                )
            )
            overlap = len(set(tokenize_text(question_text)) & set(tokenize_text(layer.search_text)))
            score += min(0.18, overlap * 0.03)

            link_score = float(link_score_map.get(layer.layer_id, 0.0))
            if link_score > 0:
                score += min(0.34, link_score * 0.34)
                reasons.append("schema linker reforcou a camada")
            if linked_field_counts.get(layer.layer_id):
                score += min(0.12, linked_field_counts[layer.layer_id] * 0.02)
            if linked_value_counts.get(layer.layer_id):
                score += min(0.12, linked_value_counts[layer.layer_id] * 0.03)
            semantic_link_bonus = self._linked_semantic_bonus(layer.layer_id, preprocessed, schema_link_result)
            if semantic_link_bonus > 0:
                score += semantic_link_bonus
                reasons.append("campos e valores linkados reforcaram a semantica")

            if use_recent_context and last_plan is not None and layer.layer_id in {
                last_plan.target_layer_id,
                last_plan.source_layer_id,
                last_plan.boundary_layer_id,
            }:
                score += 0.04 if followup_has_new_filter_signal else 0.10
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

    def _linked_semantic_bonus(
        self,
        layer_id: str,
        preprocessed: PreprocessedQuestion,
        schema_link_result: Optional[SchemaLinkResult],
    ) -> float:
        if schema_link_result is None or not layer_id:
            return 0.0

        score = 0.0
        for candidate in schema_link_result.field_candidates[:8]:
            if candidate.layer_id != layer_id:
                continue
            roles = set(candidate.roles or [])
            if preprocessed.group_hint and roles & {"location", "categorical"}:
                score += 0.03
            if preprocessed.attribute_hint == "diameter" and "diameter" in roles:
                score += 0.06
            if preprocessed.attribute_hint == "material" and "material" in roles:
                score += 0.06
            if preprocessed.attribute_hint == "status" and "status" in roles:
                score += 0.05
            if preprocessed.metric_hint in METRIC_HINTS and candidate.field_kind in {"integer", "numeric"}:
                score += 0.03

        for candidate in schema_link_result.value_candidates[:8]:
            if candidate.layer_id != layer_id:
                continue
            roles = set(candidate.roles or [])
            if preprocessed.attribute_hint == "diameter" and "diameter" in roles:
                score += 0.05
            if preprocessed.attribute_hint == "material" and "material" in roles:
                score += 0.05
            if preprocessed.attribute_hint == "status" and "status" in roles:
                score += 0.04
            if preprocessed.group_hint and "location" in roles:
                score += 0.02

        return min(0.18, score)

    def _score_layer_name_alignment(
        self,
        preprocessed: PreprocessedQuestion,
        layer,
    ) -> Tuple[float, List[str]]:
        question_text = normalize_text(preprocessed.corrected_text or preprocessed.original_text)
        layer_text = normalize_text(" ".join([layer.name, layer.search_text] + list(layer.entity_terms or []) + list(layer.semantic_tags or [])))
        score = 0.0
        reasons: List[str] = []

        asks_network = contains_hint_tokens(question_text, NETWORK_TERMS)
        asks_connections = contains_hint_tokens(question_text, CONNECTION_TERMS)
        asks_length = preprocessed.metric_hint == "length" or contains_hint_tokens(question_text, LENGTH_TERMS)
        asks_count = preprocessed.metric_hint == "count" or contains_hint_tokens(question_text, COUNT_TERMS)

        layer_is_network = contains_hint_tokens(layer_text, NETWORK_TERMS) or layer.geometry_type == "line"
        layer_is_connections = contains_hint_tokens(layer_text, CONNECTION_TERMS) or layer.geometry_type == "point"

        if asks_network:
            if layer_is_network:
                score += 0.22
                reasons.append("camada compativel com a pergunta")
            elif layer.geometry_type == "point":
                score -= 0.10

        if asks_connections:
            if layer_is_connections:
                score += 0.22
                reasons.append("camada compativel com a entidade perguntada")
            elif layer.geometry_type == "line":
                score -= 0.10

        if asks_length:
            if layer.geometry_type == "line":
                score += 0.18
                reasons.append("pergunta de extensao favorece camada linear")
            elif layer.geometry_type == "point":
                score -= 0.12

        if asks_count and asks_connections and layer.geometry_type == "point":
            score += 0.10
            reasons.append("pergunta de quantidade favorece camada de registros")

        return score, reasons

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

        for index, candidate in enumerate(brief.linked_layers[:4]):
            if candidate.layer_id in layer_ids:
                score += max(0.18 - (index * 0.03), 0.06)
                break

        if brief.metric_hint:
            if brief.metric_hint == plan.metric.operation:
                score += 0.16
            elif brief.metric_hint == "length" and plan.metric.use_geometry and plan.metric.operation == "length":
                score += 0.16
            elif brief.metric_hint == "length" and plan.intent == "derived_ratio":
                score += 0.16
            elif brief.metric_hint == "length" and plan.intent == "composite_metric":
                score += 0.12
            elif brief.metric_hint == "count" and plan.metric.operation == "count":
                score += 0.12

        if brief.excel_mode in {"countif", "sumif", "averageif"}:
            if brief.excel_mode == "countif" and plan.metric.operation == "count":
                score += 0.10
            elif brief.excel_mode == "sumif" and plan.metric.operation in {"sum", "length", "area"}:
                score += 0.08
            elif brief.excel_mode == "averageif" and plan.metric.operation == "avg":
                score += 0.10
            if plan.filters:
                score += 0.06

        if brief.group_hint:
            plan_group_text = normalize_text(" ".join([plan.group_field, plan.group_label, plan.boundary_layer_name]))
            if any(token in plan_group_text for token in GROUP_HINTS.get(brief.group_hint, (brief.group_hint,))):
                score += 0.12

        if brief.group_phrase:
            plan_group_text = normalize_text(" ".join([plan.group_field, plan.group_label, plan.boundary_layer_name]))
            group_tokens = tuple(token for token in tokenize_text(brief.group_phrase) if token)
            if group_tokens and contains_hint_tokens(plan_group_text, group_tokens):
                score += 0.10

        linked_group_fields = [
            item
            for item in brief.linked_fields
            if item.layer_id in layer_ids and any(role in {"location", "categorical", "status", "material"} for role in item.roles)
        ]
        if linked_group_fields and plan.group_field and any(item.field_name == plan.group_field for item in linked_group_fields[:4]):
            score += 0.10

        if brief.attribute_hint == "diameter":
            diameter_text = normalize_text(
                " ".join(
                    [plan.metric.field or "", plan.metric.field_label or "", plan.group_field]
                    + [filter_item.field for filter_item in plan.filters]
                )
            )
            if any(token in diameter_text for token in ("dn", "diam", "diametro", "bitola")):
                score += 0.12

        if brief.linked_values and plan.filters:
            matched_filter_links = 0
            for filter_item in plan.filters:
                for linked_value in brief.linked_values[:8]:
                    if linked_value.layer_id not in layer_ids:
                        continue
                    if linked_value.field_name != filter_item.field:
                        continue
                    if normalize_text(linked_value.value) == normalize_text(filter_item.value):
                        matched_filter_links += 1
                        break
            if matched_filter_links:
                score += min(0.12, matched_filter_links * 0.04)

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

        explicit_locations = self._explicit_location_values(brief)
        if explicit_locations:
            if self._plan_has_resolved_explicit_location(plan, explicit_locations, schema_context):
                score += 0.14
            else:
                score -= 0.28

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
        metric_label = self.semantic_metric_labels.get(plan.metric.operation, {
            "count": "Quantidade",
            "sum": "Total",
            "avg": "Media",
            "length": "Extensao total",
            "area": "Area total",
            "max": "Maior valor",
            "min": "Menor valor",
            "ratio": "Razao entre metricas",
            "difference": "Diferenca",
            "percentage": "Percentual",
            "comparison": "Comparacao",
        }.get(plan.metric.operation, "Consulta"))
        entity = brief.subject_hint or self._entity_from_plan(plan, schema_context) or "dados"
        entity_label = self.entity_label_suffixes.get(entity, f"de {entity}")

        if plan.intent == "derived_ratio":
            return self._append_filters(
                self.derived_intent_labels.get("ratio_label", "Razao entre metricas"),
                plan.filters,
            )

        if plan.intent == "composite_metric":
            base = {
                "ratio": "Razao entre metricas",
                "difference": "Diferenca entre metricas",
                "percentage": "Percentual entre metricas",
                "comparison": "Comparacao entre metricas",
            }.get(plan.metric.operation, "Operacao composta")
            if plan.composite is not None and plan.composite.operands:
                operand_labels = [item.label for item in plan.composite.operands[:2] if item.label]
                if operand_labels:
                    base = f"{base}: {' x '.join(operand_labels)}"
            return self._append_filters(base, plan.filters)

        if plan.intent == "value_insight":
            attribute = brief.attribute_hint or normalize_text(plan.metric.field_label or plan.metric.field or "valor")
            attribute_label = self.value_insight_labels.get(attribute, metric_label.lower())
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
            elif contains_hint_tokens(filter_spec.field, ("status", "situacao", "sit")):
                fragments.append(f"status {value}")
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
            for term in self.entity_priority_terms:
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

    def _explicit_location_values(self, brief: PlanningBrief) -> List[str]:
        return self._explicit_location_values_from_filters(
            brief.extracted_filters,
            getattr(brief, "linked_values", []) or [],
        )

    def _explicit_location_values_from_filters(
        self,
        filters: Sequence[Dict[str, str]],
        linked_values: Sequence[SchemaLinkValueCandidate] = (),
    ) -> List[str]:
        values: List[str] = []
        linked_value_keys = {
            normalize_compact(getattr(item, "value", "") or "")
            for item in (linked_values or [])
            if normalize_compact(getattr(item, "value", "") or "")
        }
        if not linked_value_keys:
            return values
        for item in filters or []:
            if str(item.get("kind") or "").lower() != "location":
                continue
            value = normalize_text(item.get("value") or item.get("source_text") or "")
            value_key = normalize_compact(value)
            if not value_key:
                continue
            if not any(value_key == linked_key or value_key in linked_key or linked_key in value_key for linked_key in linked_value_keys):
                continue
            if value and value not in values:
                values.append(value)
        return values

    def _plan_has_resolved_explicit_location(
        self,
        plan: QueryPlan,
        explicit_locations: Sequence[str],
        schema_context: ProjectSchemaContext,
    ) -> bool:
        normalized_locations = {normalize_text(value) for value in explicit_locations if normalize_text(value)}
        if not normalized_locations:
            return True

        layer_context_by_role = {
            "target": schema_context.layer_by_id(plan.target_layer_id),
            "source": schema_context.layer_by_id(plan.source_layer_id),
            "boundary": schema_context.layer_by_id(plan.boundary_layer_id),
        }

        for filter_spec in plan.filters or []:
            filter_value = normalize_text(filter_spec.value or "")
            if filter_value not in normalized_locations:
                continue
            if (filter_spec.layer_role or "target") == "boundary":
                return True
            filter_field = normalize_text(filter_spec.field or "")
            if any(token in filter_field for token in self.domain_pack.location_field_hints or ()):
                return True
            layer_context = layer_context_by_role.get(filter_spec.layer_role or "target")
            if layer_context is None:
                continue
            location_field_names = {
                normalize_text(field_name)
                for field_name in (
                    list(layer_context.location_field_names or [])
                    + list(layer_context.categorical_field_names or [])
                )
            }
            if filter_field in location_field_names:
                return True
        return False
