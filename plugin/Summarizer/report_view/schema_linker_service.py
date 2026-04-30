from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import log, sqrt
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .domain_packs import (
    DEFAULT_DOMAIN_PACK,
    ProjectPack,
    aliases_for_target,
    build_semantic_catalog,
    project_pack_signature,
)
from .query_preprocessor import PreprocessedQuestion, QueryPreprocessor
from .result_models import FieldSchema, FilterSpec, LayerSchema, ProjectSchema, ProjectSchemaContext
from .text_utils import normalize_compact, normalize_text, tokenize_text

LOCATION_ROLES = {"location"}
FILTER_ROLES = {"filter", "location", "material", "status", "diameter", "categorical"}
GROUP_ROLES = {"location", "categorical", "status", "material", "generic"}
METRIC_HINTS = {"sum", "avg", "max", "min"}
STATUS_TERMS = set(DEFAULT_DOMAIN_PACK.status_terms.get("ativo", ())) | set(DEFAULT_DOMAIN_PACK.status_terms.get("inativo", ())) | set(DEFAULT_DOMAIN_PACK.status_terms.get("cancelado", ())) | set(DEFAULT_DOMAIN_PACK.status_terms.get("suspenso", ()))
SERVICE_TERMS = set(DEFAULT_DOMAIN_PACK.service_terms)
MATERIAL_TERMS = set(DEFAULT_DOMAIN_PACK.material_terms)
DIAMETER_TERMS = set(DEFAULT_DOMAIN_PACK.diameter_terms)
NETWORK_TERMS = set(DEFAULT_DOMAIN_PACK.network_terms)
CONNECTION_TERMS = set(DEFAULT_DOMAIN_PACK.connection_terms)
FIELD_STOP_TERMS = {"id", "codigo", "cod", "uuid", "guid", "geom", "geometry"}


@dataclass
class SchemaLinkLayerCandidate:
    layer_id: str
    layer_name: str
    geometry_type: str
    score: float
    reasons: List[str] = field(default_factory=list)


@dataclass
class SchemaLinkFieldCandidate:
    layer_id: str
    layer_name: str
    field_name: str
    field_label: str
    field_kind: str
    roles: List[str] = field(default_factory=list)
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)


@dataclass
class SchemaLinkValueCandidate:
    layer_id: str
    layer_name: str
    field_name: str
    field_label: str
    field_kind: str
    value: str
    roles: List[str] = field(default_factory=list)
    source: str = "profile"
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)


@dataclass
class SchemaLinkResult:
    normalized_question: str
    corrected_question: str
    layer_candidates: List[SchemaLinkLayerCandidate] = field(default_factory=list)
    field_candidates: List[SchemaLinkFieldCandidate] = field(default_factory=list)
    value_candidates: List[SchemaLinkValueCandidate] = field(default_factory=list)
    preprocessed: Optional[PreprocessedQuestion] = None


@dataclass
class _IndexedDocument:
    kind: str
    layer_id: str
    layer_name: str
    geometry_type: str = ""
    field_name: str = ""
    field_label: str = ""
    field_kind: str = ""
    value: str = ""
    roles: Tuple[str, ...] = ()
    text: str = ""
    semantic_terms: Tuple[str, ...] = ()
    vector: Dict[str, float] = field(default_factory=dict)
    norm: float = 0.0


@dataclass
class _SchemaIndex:
    idf: Dict[str, float]
    layer_docs: List[_IndexedDocument] = field(default_factory=list)
    field_docs: List[_IndexedDocument] = field(default_factory=list)
    value_docs: List[_IndexedDocument] = field(default_factory=list)


class SchemaLinkerService:
    def __init__(
        self,
        max_layer_candidates: int = 6,
        max_field_candidates: int = 10,
        max_value_candidates: int = 12,
        project_pack: Optional[ProjectPack] = None,
    ):
        self.max_layer_candidates = max(3, int(max_layer_candidates))
        self.max_field_candidates = max(4, int(max_field_candidates))
        self.max_value_candidates = max(6, int(max_value_candidates))
        self.project_pack = project_pack
        self.preprocessor = QueryPreprocessor(project_pack=project_pack)
        self.semantic_catalog = build_semantic_catalog(DEFAULT_DOMAIN_PACK, project_pack)
        self._index_cache: Dict[Tuple, _SchemaIndex] = {}

    def clear_cache(self):
        self._index_cache = {}

    def link(
        self,
        question: str,
        schema: ProjectSchema,
        schema_context: ProjectSchemaContext,
        preprocessed: Optional[PreprocessedQuestion] = None,
    ) -> SchemaLinkResult:
        preprocessed = preprocessed or self.preprocessor.preprocess(question)
        query_text = self._build_query_text(question, preprocessed)
        normalized_question = normalize_text(question)
        query_semantic_terms = self._query_semantic_terms(preprocessed, query_text)
        index = self._get_or_build_index(schema, schema_context)
        query_vector, query_norm = self._vectorize_text(query_text, index.idf)

        layer_candidates = self._rank_layers(
            index.layer_docs,
            schema_context,
            preprocessed,
            query_text,
            query_vector,
            query_norm,
            query_semantic_terms,
        )
        field_candidates = self._rank_fields(
            index.field_docs,
            schema_context,
            preprocessed,
            query_text,
            query_vector,
            query_norm,
            query_semantic_terms,
        )
        value_candidates = self._rank_values(
            index.value_docs,
            preprocessed,
            query_text,
            query_vector,
            query_norm,
            query_semantic_terms,
        )

        return SchemaLinkResult(
            normalized_question=normalized_question,
            corrected_question=preprocessed.corrected_text or normalized_question,
            layer_candidates=layer_candidates,
            field_candidates=field_candidates,
            value_candidates=value_candidates,
            preprocessed=preprocessed,
        )

    def layer_score_map(self, link_result: Optional[SchemaLinkResult]) -> Dict[str, float]:
        scores: Dict[str, float] = {}
        if link_result is None:
            return scores
        for candidate in link_result.layer_candidates:
            scores[candidate.layer_id] = max(scores.get(candidate.layer_id, 0.0), float(candidate.score or 0.0))
        return scores

    def choose_group_field(
        self,
        link_result: Optional[SchemaLinkResult],
        layer_schema: LayerSchema,
        preferred_roles: Sequence[str] = (),
    ) -> Optional[str]:
        if link_result is None:
            return None
        role_priority = tuple(preferred_roles or ("location", "categorical", "status", "material"))
        best_field = None
        best_score = 0.0
        for candidate in link_result.field_candidates:
            if candidate.layer_id != layer_schema.layer_id:
                continue
            if candidate.field_kind not in {"text", "date", "datetime", "integer"}:
                continue
            roles = set(candidate.roles)
            if role_priority and not any(role in roles for role in role_priority):
                continue
            score = float(candidate.score or 0.0)
            for index, role in enumerate(role_priority):
                if role in roles:
                    score += max(0.08 - (index * 0.01), 0.03)
                    break
            if score > best_score:
                best_field = candidate.field_name
                best_score = score
        return best_field

    def suggest_filters(
        self,
        link_result: Optional[SchemaLinkResult],
        layer_schema: LayerSchema,
        raw_filters: Sequence[Dict],
        recognized_filters: Sequence[Dict],
        limit: int = 3,
    ) -> Tuple[List[FilterSpec], List[Dict]]:
        if link_result is None or not raw_filters:
            return [], []

        recognized_keys = {
            (
                normalize_text(item.get("field") or ""),
                normalize_text(item.get("value") or ""),
            )
            for item in recognized_filters
        }
        additions: List[FilterSpec] = []
        addition_logs: List[Dict] = []
        seen_fields = set()

        for raw_candidate in raw_filters:
            best_candidate = None
            best_score = 0.0
            for value_candidate in link_result.value_candidates:
                if value_candidate.layer_id != layer_schema.layer_id:
                    continue
                score = self._score_filter_candidate(raw_candidate, value_candidate)
                if score > best_score:
                    best_candidate = value_candidate
                    best_score = score
            if best_candidate is None or best_score < 0.48:
                continue
            field_key = (
                normalize_text(best_candidate.field_name),
                normalize_text(best_candidate.value),
            )
            if field_key in recognized_keys or field_key in seen_fields:
                continue
            field_schema = layer_schema.field_by_name(best_candidate.field_name)
            if field_schema is None:
                continue
            additions.append(
                FilterSpec(
                    field=field_schema.name,
                    value=best_candidate.value,
                    operator="eq",
                    layer_role="target",
                )
            )
            addition_logs.append(
                {
                    "kind": raw_candidate.get("kind"),
                    "field": field_schema.name,
                    "field_label": field_schema.label,
                    "value": best_candidate.value,
                    "score": round(best_score, 4),
                    "source_text": raw_candidate.get("source_text") or raw_candidate.get("text"),
                    "match_mode": "schema_linker",
                }
            )
            seen_fields.add(field_key)
            if len(additions) >= max(1, int(limit)):
                break
        return additions, addition_logs

    def _score_filter_candidate(self, raw_candidate: Dict, value_candidate: SchemaLinkValueCandidate) -> float:
        raw_kind = str(raw_candidate.get("kind") or "").lower()
        raw_text = normalize_text(raw_candidate.get("source_text") or raw_candidate.get("text") or raw_candidate.get("value") or "")
        raw_compact = normalize_compact(raw_text)
        candidate_text = normalize_text(value_candidate.value)
        candidate_compact = normalize_compact(candidate_text)
        roles = set(value_candidate.roles)
        score = float(value_candidate.score or 0.0) * 0.45

        if not self._is_role_compatible(raw_kind, roles):
            return 0.0
        if raw_text and raw_text == candidate_text:
            score += 0.45
        elif raw_compact and raw_compact == candidate_compact:
            score += 0.42
        elif raw_text and raw_text in candidate_text:
            score += 0.26
        elif raw_text and candidate_text in raw_text:
            score += 0.22
        else:
            raw_tokens = set(tokenize_text(raw_text))
            value_tokens = set(tokenize_text(candidate_text))
            overlap = len(raw_tokens & value_tokens)
            if overlap:
                score += min(0.20, overlap * 0.08)

        if raw_kind == "diameter":
            raw_digits = "".join(char for char in raw_compact if char.isdigit())
            value_digits = "".join(char for char in candidate_compact if char.isdigit())
            if raw_digits and raw_digits == value_digits:
                score += 0.30
        return score

    def _is_role_compatible(self, raw_kind: str, roles: Sequence[str]) -> bool:
        role_set = set(roles)
        if raw_kind == "location":
            return bool(role_set & LOCATION_ROLES) or "categorical" in role_set
        if raw_kind == "status":
            return "status" in role_set or "categorical" in role_set
        if raw_kind == "material":
            return "material" in role_set or "categorical" in role_set
        if raw_kind == "diameter":
            return "diameter" in role_set or "numeric" in role_set
        return bool(role_set & FILTER_ROLES)

    def _rank_layers(
        self,
        documents: Sequence[_IndexedDocument],
        schema_context: ProjectSchemaContext,
        preprocessed: PreprocessedQuestion,
        query_text: str,
        query_vector: Dict[str, float],
        query_norm: float,
        query_semantic_terms: Sequence[str],
    ) -> List[SchemaLinkLayerCandidate]:
        items: List[SchemaLinkLayerCandidate] = []
        for document in documents:
            similarity = self._cosine(query_vector, query_norm, document.vector, document.norm)
            reasons: List[str] = []
            score = similarity
            if similarity > 0.08:
                reasons.append("similaridade semantica")
            semantic_bonus, semantic_matches = self._semantic_overlap_score(query_semantic_terms, document.semantic_terms)
            if semantic_bonus > 0:
                score += min(0.24, semantic_bonus)
                reasons.append(
                    f"alinhamento semantico ({', '.join(match.split(':', 1)[-1] for match in semantic_matches[:2])})"
                )
            if preprocessed.subject_hint and preprocessed.subject_hint in document.text:
                score += 0.16
                reasons.append("assunto proximo da camada")
            if preprocessed.metric_hint == "length" and document.geometry_type == "line":
                score += 0.11
                reasons.append("geometria compativel com extensao")
            if preprocessed.metric_hint == "area" and document.geometry_type == "polygon":
                score += 0.11
                reasons.append("geometria compativel com area")
            if preprocessed.group_hint:
                context_layer = schema_context.layer_by_id(document.layer_id)
                if context_layer is not None and any(
                    preprocessed.group_hint in normalize_text(item)
                    for item in context_layer.location_field_names + context_layer.categorical_field_names
                ):
                    score += 0.08
                    reasons.append("camada possui dimensao de agrupamento")
            if any(token in document.text for token in tokenize_text(query_text)):
                score += 0.04
            if score >= 0.14:
                items.append(
                    SchemaLinkLayerCandidate(
                        layer_id=document.layer_id,
                        layer_name=document.layer_name,
                        geometry_type=document.geometry_type,
                        score=round(min(score, 0.99), 4),
                        reasons=reasons,
                    )
                )
        items.sort(key=lambda item: (item.score, item.layer_name.lower()), reverse=True)
        return items[: self.max_layer_candidates]

    def _rank_fields(
        self,
        documents: Sequence[_IndexedDocument],
        schema_context: ProjectSchemaContext,
        preprocessed: PreprocessedQuestion,
        query_text: str,
        query_vector: Dict[str, float],
        query_norm: float,
        query_semantic_terms: Sequence[str],
    ) -> List[SchemaLinkFieldCandidate]:
        items: List[SchemaLinkFieldCandidate] = []
        query_tokens = set(tokenize_text(query_text))
        for document in documents:
            similarity = self._cosine(query_vector, query_norm, document.vector, document.norm)
            roles = set(document.roles)
            score = similarity
            reasons: List[str] = []
            if similarity > 0.08:
                reasons.append("similaridade semantica")
            semantic_bonus, semantic_matches = self._semantic_overlap_score(query_semantic_terms, document.semantic_terms)
            if semantic_bonus > 0:
                score += min(0.26, semantic_bonus)
                reasons.append(
                    f"papel semantico alinhado ({', '.join(match.split(':', 1)[-1] for match in semantic_matches[:2])})"
                )
            if preprocessed.group_phrase and ("location" in roles or "categorical" in roles):
                phrase_tokens = set(tokenize_text(preprocessed.group_phrase))
                overlap = len(phrase_tokens & set(tokenize_text(document.text)))
                if overlap:
                    score += min(0.18, overlap * 0.08)
                    reasons.append("campo proximo do agrupamento")
            if preprocessed.group_hint and ("location" in roles or "categorical" in roles):
                if preprocessed.group_hint in document.text:
                    score += 0.15
                    reasons.append("campo alinhado ao agrupamento")
            if preprocessed.attribute_hint:
                if preprocessed.attribute_hint == "diameter" and "diameter" in roles:
                    score += 0.20
                    reasons.append("campo de diametro")
                elif preprocessed.attribute_hint == "material" and "material" in roles:
                    score += 0.20
                    reasons.append("campo de material")
                elif preprocessed.attribute_hint == "status" and "status" in roles:
                    score += 0.18
                    reasons.append("campo de status")
            if preprocessed.metric_hint in METRIC_HINTS and "numeric" in roles:
                score += 0.14
                reasons.append("campo numerico para agregacao")
            if query_tokens & set(tokenize_text(document.field_label or document.field_name)):
                score += 0.07
            if score >= 0.15:
                items.append(
                    SchemaLinkFieldCandidate(
                        layer_id=document.layer_id,
                        layer_name=document.layer_name,
                        field_name=document.field_name,
                        field_label=document.field_label,
                        field_kind=document.field_kind,
                        roles=list(document.roles),
                        score=round(min(score, 0.99), 4),
                        reasons=reasons,
                    )
                )
        items.sort(key=lambda item: (item.score, item.layer_name.lower(), item.field_label.lower()), reverse=True)
        return items[: self.max_field_candidates]

    def _rank_values(
        self,
        documents: Sequence[_IndexedDocument],
        preprocessed: PreprocessedQuestion,
        query_text: str,
        query_vector: Dict[str, float],
        query_norm: float,
        query_semantic_terms: Sequence[str],
    ) -> List[SchemaLinkValueCandidate]:
        items: List[SchemaLinkValueCandidate] = []
        normalized_query = normalize_text(query_text)
        compact_query = normalize_compact(query_text)
        query_tokens = set(tokenize_text(query_text))
        for document in documents:
            similarity = self._cosine(query_vector, query_norm, document.vector, document.norm)
            value_text = normalize_text(document.value)
            value_compact = normalize_compact(document.value)
            value_tokens = set(tokenize_text(document.value))
            score = similarity
            reasons: List[str] = []
            semantic_bonus, semantic_matches = self._semantic_overlap_score(query_semantic_terms, document.semantic_terms)
            if semantic_bonus > 0:
                score += min(0.20, semantic_bonus)
                reasons.append(
                    f"contexto semantico alinhado ({', '.join(match.split(':', 1)[-1] for match in semantic_matches[:2])})"
                )
            if value_text and value_text in normalized_query:
                score += 0.42
                reasons.append("valor encontrado na pergunta")
            elif value_compact and value_compact in compact_query:
                score += 0.36
                reasons.append("valor encontrado na pergunta")
            else:
                overlap = len(query_tokens & value_tokens)
                if overlap:
                    score += min(0.18, overlap * 0.07)
                    reasons.append("tokens do valor presentes na pergunta")
            if "status" in document.roles and query_tokens & STATUS_TERMS:
                score += 0.08
            if "material" in document.roles and query_tokens & MATERIAL_TERMS:
                score += 0.08
            if "generic" in document.roles and query_tokens & SERVICE_TERMS:
                score += 0.06
            if preprocessed.attribute_hint == "diameter" and "diameter" in document.roles:
                score += 0.10
            if score >= 0.17:
                items.append(
                    SchemaLinkValueCandidate(
                        layer_id=document.layer_id,
                        layer_name=document.layer_name,
                        field_name=document.field_name,
                        field_label=document.field_label,
                        field_kind=document.field_kind,
                        value=document.value,
                        roles=list(document.roles),
                        source="profile",
                        score=round(min(score, 0.99), 4),
                        reasons=reasons,
                    )
                )
        items.sort(
            key=lambda item: (
                item.score,
                item.layer_name.lower(),
                item.field_label.lower(),
                normalize_text(item.value),
            ),
            reverse=True,
        )
        deduped: List[SchemaLinkValueCandidate] = []
        seen = set()
        for item in items:
            key = (item.layer_id, normalize_text(item.field_name), normalize_text(item.value))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[: self.max_value_candidates]

    def _get_or_build_index(
        self,
        schema: ProjectSchema,
        schema_context: ProjectSchemaContext,
    ) -> _SchemaIndex:
        signature = (self._schema_signature(schema), project_pack_signature(self.project_pack))
        if signature not in self._index_cache:
            self._index_cache[signature] = self._build_index(schema, schema_context)
        return self._index_cache[signature]

    def _build_index(
        self,
        schema: ProjectSchema,
        schema_context: ProjectSchemaContext,
    ) -> _SchemaIndex:
        layer_docs: List[_IndexedDocument] = []
        field_docs: List[_IndexedDocument] = []
        value_docs: List[_IndexedDocument] = []
        raw_feature_sets: List[set] = []

        for layer in schema.layers:
            context_layer = schema_context.layer_by_id(layer.layer_id)
            layer_aliases = self._project_layer_aliases(layer.name)
            layer_text = normalize_text(
                " ".join(
                    filter(
                        None,
                        [
                            layer.name,
                            " ".join(layer_aliases),
                            layer.geometry_type,
                            layer.search_text,
                            getattr(context_layer, "summary_text", ""),
                            getattr(context_layer, "search_text", ""),
                            " ".join(getattr(context_layer, "entity_terms", [])),
                            " ".join(getattr(context_layer, "semantic_tags", [])),
                        ],
                    )
                )
            )
            layer_doc = _IndexedDocument(
                kind="layer",
                layer_id=layer.layer_id,
                layer_name=layer.name,
                geometry_type=layer.geometry_type,
                text=layer_text,
                semantic_terms=self._layer_semantic_terms(layer, context_layer),
            )
            layer_docs.append(layer_doc)
            raw_feature_sets.append(set(self._raw_features(layer_text).keys()))

            for field in layer.fields:
                field_roles = tuple(self._field_roles(layer, context_layer, field))
                field_aliases = self._project_field_aliases(field.name)
                field_text = normalize_text(
                    " ".join(
                        filter(
                            None,
                            [
                                layer.name,
                                layer.geometry_type,
                                field.name,
                                field.label,
                                " ".join(field_aliases),
                                field.search_text,
                                " ".join(field_roles),
                            ],
                        )
                    )
                )
                field_doc = _IndexedDocument(
                    kind="field",
                    layer_id=layer.layer_id,
                    layer_name=layer.name,
                    geometry_type=layer.geometry_type,
                    field_name=field.name,
                    field_label=field.label,
                    field_kind=field.kind,
                    roles=field_roles,
                    text=field_text,
                    semantic_terms=self._field_semantic_terms(layer, context_layer, field, field_roles),
                )
                field_docs.append(field_doc)
                raw_feature_sets.append(set(self._raw_features(field_text).keys()))

                values = []
                for value in list(field.top_values or [])[:6] + list(field.sample_values or [])[:4]:
                    normalized_value = str(value or "").strip()
                    if not normalized_value:
                        continue
                    if normalize_text(normalized_value) in FIELD_STOP_TERMS:
                        continue
                    values.append(normalized_value)
                for value in values:
                    value_aliases = self._project_value_aliases(value)
                    value_text = normalize_text(
                        " ".join(
                            filter(
                                None,
                                [
                                    layer.name,
                                    field.name,
                                    field.label,
                                    value,
                                    " ".join(value_aliases),
                                    " ".join(field_roles),
                                ],
                            )
                        )
                    )
                    value_doc = _IndexedDocument(
                        kind="value",
                        layer_id=layer.layer_id,
                        layer_name=layer.name,
                        geometry_type=layer.geometry_type,
                        field_name=field.name,
                        field_label=field.label,
                        field_kind=field.kind,
                        value=value,
                        roles=field_roles,
                        text=value_text,
                        semantic_terms=self._value_semantic_terms(layer, context_layer, field, value, field_roles),
                    )
                    value_docs.append(value_doc)
                    raw_feature_sets.append(set(self._raw_features(value_text).keys()))

        total_docs = max(1, len(raw_feature_sets))
        document_frequency: Counter = Counter()
        for feature_set in raw_feature_sets:
            for feature in feature_set:
                document_frequency[feature] += 1
        idf = {
            feature: log((total_docs + 1.0) / (float(count) + 1.0)) + 1.0
            for feature, count in document_frequency.items()
        }
        for document in layer_docs + field_docs + value_docs:
            document.vector, document.norm = self._vectorize_text(document.text, idf)
        return _SchemaIndex(
            idf=idf,
            layer_docs=layer_docs,
            field_docs=field_docs,
            value_docs=value_docs,
        )

    def _project_layer_aliases(self, layer_name: str) -> Tuple[str, ...]:
        if self.project_pack is None:
            return ()
        return aliases_for_target(self.project_pack.layer_aliases, layer_name)

    def _project_field_aliases(self, field_name: str) -> Tuple[str, ...]:
        if self.project_pack is None:
            return ()
        return aliases_for_target(self.project_pack.field_aliases, field_name)

    def _project_value_aliases(self, value: str) -> Tuple[str, ...]:
        if self.project_pack is None:
            return ()
        return aliases_for_target(self.project_pack.value_aliases, value)

    def _query_semantic_terms(
        self,
        preprocessed: PreprocessedQuestion,
        query_text: str,
    ) -> Tuple[str, ...]:
        terms = list(getattr(preprocessed, "semantic_terms", []) or [])
        terms.extend(self._semantic_labels_from_text(query_text))
        return tuple(dict.fromkeys(term for term in terms if term))

    def _layer_semantic_terms(
        self,
        layer: LayerSchema,
        context_layer,
    ) -> Tuple[str, ...]:
        terms = list(
            self._semantic_labels_from_text(
                " ".join(
                    filter(
                        None,
                        [
                            layer.name,
                            layer.search_text,
                            getattr(context_layer, "search_text", ""),
                            " ".join(getattr(context_layer, "entity_terms", [])),
                            " ".join(getattr(context_layer, "semantic_tags", [])),
                        ],
                    )
                )
            )
        )
        if layer.geometry_type == "line":
            terms.extend(["metric:length", "subject:network"])
        elif layer.geometry_type == "polygon":
            terms.extend(["metric:area", "group:location"])
        elif layer.geometry_type == "point":
            terms.append("subject:connection")

        if context_layer is not None:
            if getattr(context_layer, "location_field_names", []):
                terms.append("group:location")
            if any(term in normalize_text(" ".join(getattr(context_layer, "entity_terms", []))) for term in NETWORK_TERMS):
                terms.append("subject:network")
            if any(term in normalize_text(" ".join(getattr(context_layer, "entity_terms", []))) for term in CONNECTION_TERMS):
                terms.append("subject:connection")

        for field in layer.fields:
            roles = set(getattr(field, "semantic_roles", []) or [])
            if "diameter_field" in roles:
                terms.append("attribute:diameter")
            if "material_field" in roles:
                terms.append("attribute:material")
            if "status_field" in roles:
                terms.append("attribute:status")
            if getattr(field, "is_location_candidate", False):
                terms.append("group:location")
        return tuple(dict.fromkeys(term for term in terms if term))

    def _field_semantic_terms(
        self,
        layer: LayerSchema,
        context_layer,
        field: FieldSchema,
        field_roles: Sequence[str],
    ) -> Tuple[str, ...]:
        terms = list(
            self._semantic_labels_from_text(
                " ".join(
                    filter(
                        None,
                        [
                            layer.name,
                            field.name,
                            field.label,
                            field.search_text,
                            getattr(context_layer, "search_text", ""),
                        ],
                    )
                )
            )
        )
        roles = set(field_roles)
        if "location" in roles:
            terms.append("group:location")
        if "diameter" in roles:
            terms.append("attribute:diameter")
        if "material" in roles:
            terms.append("attribute:material")
        if "status" in roles:
            terms.append("attribute:status")
        if "numeric" in roles:
            terms.append("field:numeric")
        if "categorical" in roles:
            terms.append("field:categorical")
        if layer.geometry_type == "line":
            terms.append("subject:network")
        elif layer.geometry_type == "point":
            terms.append("subject:connection")
        return tuple(dict.fromkeys(term for term in terms if term))

    def _value_semantic_terms(
        self,
        layer: LayerSchema,
        context_layer,
        field: FieldSchema,
        value: str,
        field_roles: Sequence[str],
    ) -> Tuple[str, ...]:
        terms = list(
            self._semantic_labels_from_text(
                " ".join(
                    filter(
                        None,
                        [
                            layer.name,
                            field.name,
                            field.label,
                            value,
                            getattr(context_layer, "search_text", ""),
                        ],
                    )
                )
            )
        )
        roles = set(field_roles)
        if "location" in roles:
            terms.append("group:location")
        if "diameter" in roles:
            terms.append("attribute:diameter")
        if "material" in roles:
            terms.append("attribute:material")
        if "status" in roles:
            terms.append("attribute:status")
        return tuple(dict.fromkeys(term for term in terms if term))

    def _semantic_labels_from_text(self, text: str) -> Tuple[str, ...]:
        normalized = normalize_text(text)
        padded = f" {normalized} "
        labels = []
        for semantic_label, aliases in self.semantic_catalog.items():
            if not aliases:
                continue
            matched = False
            for term in aliases:
                normalized_term = normalize_text(term)
                if not normalized_term:
                    continue
                if f" {normalized_term} " in padded:
                    matched = True
                    break
                if len(normalized_term) > 4 and normalized_term in normalized:
                    matched = True
                    break
            if matched:
                labels.append(semantic_label)
        return tuple(dict.fromkeys(labels))

    def _semantic_overlap_score(
        self,
        query_terms: Sequence[str],
        document_terms: Sequence[str],
    ) -> Tuple[float, List[str]]:
        if not query_terms or not document_terms:
            return 0.0, []
        document_set = set(document_terms)
        overlap = [term for term in query_terms if term in document_set]
        if not overlap:
            return 0.0, []
        weights = {
            "subject:": 0.12,
            "attribute:": 0.11,
            "group:": 0.09,
            "context:": 0.08,
            "metric:": 0.07,
            "field:": 0.05,
        }
        score = 0.0
        for term in overlap:
            for prefix, weight in weights.items():
                if term.startswith(prefix):
                    score += weight
                    break
            else:
                score += 0.05
        return score, overlap

    def _schema_signature(self, schema: ProjectSchema) -> Tuple:
        return tuple(
            (
                layer.layer_id,
                layer.name,
                layer.geometry_type,
                layer.feature_count,
                tuple(
                    (
                        field.name,
                        field.kind,
                        field.alias,
                        len(field.top_values or []),
                        len(field.sample_values or []),
                    )
                    for field in layer.fields
                ),
            )
            for layer in schema.layers
        )

    def _field_roles(
        self,
        layer: LayerSchema,
        context_layer,
        field: FieldSchema,
    ) -> List[str]:
        roles = []
        search_text = normalize_text(" ".join(filter(None, [field.name, field.label, field.search_text])))
        if field.kind in {"integer", "numeric"}:
            roles.append("numeric")
        else:
            roles.append("categorical")
        if getattr(field, "is_filter_candidate", False):
            roles.append("filter")
        if getattr(field, "is_location_candidate", False):
            roles.extend(["filter", "location"])
        if context_layer is not None:
            if field.name in getattr(context_layer, "location_field_names", []):
                roles.append("location")
            if field.name in getattr(context_layer, "filter_field_names", []):
                roles.append("filter")
        if any(term in search_text for term in DIAMETER_TERMS):
            roles.append("diameter")
        if any(term in search_text for term in MATERIAL_TERMS):
            roles.append("material")
        if any(term in search_text for term in ("status", "situacao", "sit")):
            roles.append("status")
        if any(term in search_text for term in SERVICE_TERMS):
            roles.append("generic")
        return sorted(set(roles))

    def _build_query_text(self, question: str, preprocessed: PreprocessedQuestion) -> str:
        return normalize_text(
            " ".join(
                filter(
                    None,
                    [
                        question,
                        preprocessed.corrected_text,
                        preprocessed.rewritten_text,
                        preprocessed.subject_hint,
                        preprocessed.metric_hint,
                        preprocessed.group_hint,
                        preprocessed.group_phrase,
                        preprocessed.attribute_hint,
                    ],
                )
            )
        )

    def _raw_features(self, text: str) -> Counter:
        normalized = normalize_text(text)
        features: Counter = Counter()
        for token in tokenize_text(normalized):
            features[f"tok:{token}"] += 1.0
        compact = normalize_compact(normalized)
        if len(compact) >= 3:
            for index in range(len(compact) - 2):
                features[f"ng:{compact[index:index + 3]}"] += 0.35
        return features

    def _vectorize_text(self, text: str, idf: Dict[str, float]) -> Tuple[Dict[str, float], float]:
        raw = self._raw_features(text)
        vector: Dict[str, float] = {}
        for feature, weight in raw.items():
            vector[feature] = weight * idf.get(feature, 1.0)
        norm = sqrt(sum(value * value for value in vector.values()))
        return vector, norm

    def _cosine(
        self,
        left_vector: Dict[str, float],
        left_norm: float,
        right_vector: Dict[str, float],
        right_norm: float,
    ) -> float:
        if left_norm <= 0 or right_norm <= 0:
            return 0.0
        if len(left_vector) > len(right_vector):
            left_vector, right_vector = right_vector, left_vector
            left_norm, right_norm = right_norm, left_norm
        dot = 0.0
        for feature, weight in left_vector.items():
            dot += weight * right_vector.get(feature, 0.0)
        return dot / (left_norm * right_norm)
