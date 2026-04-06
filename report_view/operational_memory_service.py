from __future__ import annotations

import copy
import re
import unicodedata
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Dict, List, Optional

from .operational_memory_models import (
    ApprovedExampleRecord,
    QueryHistoryHandle,
    QueryHistoryRecord,
    SemanticAliasRecord,
    SimilarQueryMatch,
)
from .operational_memory_repository import (
    ApprovedExampleRepository,
    FeedbackRepository,
    IApprovedExampleRepository,
    IFeedbackRepository,
    IQueryMemoryRepository,
    ISemanticAliasRepository,
    QueryMemoryRepository,
    SemanticAliasRepository,
)
from .operational_memory_store import OperationalMemoryStore
from .report_logging import log_info, log_warning
from .result_models import CandidateInterpretation, InterpretationResult, QueryPlan, QueryResult
from .conversation_memory_service import ConversationMemoryService


DEFAULT_SEMANTIC_ALIASES = (
    ("mt", "metros", "unit", 0.95, "seed", "abreviacao comum"),
    ("mts", "metros", "unit", 0.95, "seed", "abreviacao comum"),
    ("metragem", "metros", "metric", 0.90, "seed", "variacao de metrica"),
    ("150 mm", "dn150", "diameter", 1.00, "seed", "diametro equivalente"),
    ("200 mm", "dn200", "diameter", 1.00, "seed", "diametro equivalente"),
    ("300 mm", "dn300", "diameter", 1.00, "seed", "diametro equivalente"),
    ("400 mm", "dn400", "diameter", 1.00, "seed", "diametro equivalente"),
    ("agua brnca", "agua branca", "location", 0.85, "seed", "erro comum"),
    ("cidade", "municipio", "location", 0.75, "seed", "sinonimo de agrupamento"),
    ("municipio", "cidade", "location", 0.75, "seed", "sinonimo de agrupamento"),
)

RERANK_IGNORED_TOKENS = {
    "a",
    "com",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "extensao",
    "grafico",
    "maior",
    "mais",
    "menor",
    "menos",
    "metros",
    "municipio",
    "municipios",
    "na",
    "no",
    "nos",
    "o",
    "os",
    "pizza",
    "por",
    "qual",
    "quais",
    "quantidade",
    "quantos",
    "quantas",
    "rede",
    "redes",
    "top",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    text = re.sub(r"[^a-z0-9_]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_query(text: str) -> str:
    normalized = _normalize_text(text)
    replacements = (
        (r"\bdn\s*[-/]?\s*(\d{2,4})\b", r"dn \1"),
        (r"\b(\d{2,4})\s*mm\b", r"\1 mm"),
        (r"\bqtd\b", "quantidade"),
        (r"\bqtde\b", "quantidade"),
        (r"\bmun\b", "municipio"),
        (r"\bmunic\b", "municipio"),
        (r"\bcid\b", "cidade"),
        (r"\bbair\b", "bairro"),
        (r"\bmts\b", "metros"),
        (r"\bmt\b", "metros"),
        (r"\bcomp\b", "comprimento"),
        (r"\bext\b", "extensao"),
        (r"\bdiam\b", "diametro"),
    )
    updated = normalized
    for pattern, replacement in replacements:
        updated = re.sub(pattern, replacement, updated)
    return re.sub(r"\s+", " ", updated).strip()


def _tokenize(value: str) -> List[str]:
    return [token for token in _normalize_text(value).split() if token]


def _similarity_score(left: str, right: str) -> float:
    left_tokens = set(_tokenize(left))
    right_tokens = set(_tokenize(right))
    if not left_tokens or not right_tokens:
        return 0.0
    if left == right:
        return 1.0
    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    score = overlap / max(1, union)
    if left in right or right in left:
        score += 0.15
    return min(1.0, score)


def _meaningful_query_tokens(value: str) -> List[str]:
    tokens = []
    for token in _tokenize(value):
        if token in RERANK_IGNORED_TOKENS:
            continue
        tokens.append(token)
    return tokens


def _candidate_to_payload(candidate: CandidateInterpretation) -> Dict[str, Any]:
    return {
        "label": candidate.label,
        "reason": candidate.reason,
        "confidence": float(candidate.confidence or 0.0),
        "plan": candidate.plan.to_dict() if candidate.plan is not None else {},
    }


class QueryFeedbackService:
    def __init__(self, repository: IFeedbackRepository):
        self.repository = repository

    def register_explicit_feedback(
        self,
        query_history_id: int,
        feedback_type: str,
        corrected_intent: str = "",
        corrected_metric: str = "",
        corrected_entity: str = "",
        corrected_filters_json: Optional[List[Dict[str, Any]]] = None,
        notes: str = "",
        user_action_json: Optional[Dict[str, Any]] = None,
    ):
        if not query_history_id:
            return None
        from .operational_memory_models import QueryFeedbackRecord

        return self.repository.create(
            QueryFeedbackRecord(
                query_history_id=int(query_history_id),
                created_utc=_utc_now(),
                feedback_type=feedback_type,
                corrected_intent=corrected_intent,
                corrected_metric=corrected_metric,
                corrected_entity=corrected_entity,
                corrected_filters_json=list(corrected_filters_json or []),
                notes=notes,
                user_action_json=dict(user_action_json or {}),
            )
        )

    def register_implicit_feedback(
        self,
        query_history_id: int,
        feedback_type: str,
        notes: str = "",
        user_action_json: Optional[Dict[str, Any]] = None,
    ):
        return self.register_explicit_feedback(
            query_history_id=query_history_id,
            feedback_type=feedback_type,
            notes=notes,
            user_action_json=user_action_json,
        )

    def register_correction(
        self,
        query_history_id: int,
        corrected_intent: str = "",
        corrected_metric: str = "",
        corrected_entity: str = "",
        corrected_filters_json: Optional[List[Dict[str, Any]]] = None,
        notes: str = "",
        user_action_json: Optional[Dict[str, Any]] = None,
    ):
        return self.register_explicit_feedback(
            query_history_id=query_history_id,
            feedback_type="correction",
            corrected_intent=corrected_intent,
            corrected_metric=corrected_metric,
            corrected_entity=corrected_entity,
            corrected_filters_json=corrected_filters_json,
            notes=notes,
            user_action_json=user_action_json,
        )


class SemanticAliasService:
    def __init__(self, repository: ISemanticAliasRepository):
        self.repository = repository
        self._defaults_seeded = False

    def ensure_defaults(self):
        if self._defaults_seeded:
            return
        for alias_term, canonical_term, alias_type, weight, source, notes in DEFAULT_SEMANTIC_ALIASES:
            self.repository.upsert(
                SemanticAliasRecord(
                    created_utc=_utc_now(),
                    alias_term=_normalize_text(alias_term),
                    canonical_term=_normalize_text(canonical_term),
                    alias_type=alias_type,
                    weight=float(weight),
                    active=True,
                    source=source,
                    notes=notes,
                )
            )
        self._defaults_seeded = True

    def list_active_aliases(self, alias_type: str = "", limit: int = 200) -> List[SemanticAliasRecord]:
        self.ensure_defaults()
        return self.repository.list_active(alias_type=alias_type, limit=limit)

    def upsert_alias(
        self,
        alias_term: str,
        canonical_term: str,
        alias_type: str,
        weight: float = 1.0,
        active: bool = True,
        source: str = "manual",
        notes: str = "",
    ) -> SemanticAliasRecord:
        self.ensure_defaults()
        return self.repository.upsert(
            SemanticAliasRecord(
                created_utc=_utc_now(),
                alias_term=_normalize_text(alias_term),
                canonical_term=_normalize_text(canonical_term),
                alias_type=alias_type,
                weight=float(weight),
                active=bool(active),
                source=source,
                notes=notes,
            )
        )

    def apply_aliases(self, text: str) -> str:
        normalized = _normalize_text(text)
        if not normalized:
            return ""
        self.ensure_defaults()
        aliases = sorted(
            self.repository.list_active(limit=500),
            key=lambda item: (len(item.alias_term), item.weight),
            reverse=True,
        )
        updated = f" {normalized} "
        for alias in aliases:
            alias_term = _normalize_text(alias.alias_term)
            canonical_term = _normalize_text(alias.canonical_term)
            if not alias_term or not canonical_term:
                continue
            pattern = rf"(?<![a-z0-9_]){re.escape(alias_term)}(?![a-z0-9_])"
            updated = re.sub(pattern, canonical_term, updated)
        return re.sub(r"\s+", " ", updated).strip()


class ApprovedExampleService:
    def __init__(self, repository: IApprovedExampleRepository, alias_service: SemanticAliasService):
        self.repository = repository
        self.alias_service = alias_service

    def add_example(
        self,
        example_query: str,
        normalized_query: str,
        intent: str,
        metric: str,
        entity: str,
        filters_json: Optional[List[Dict[str, Any]]] = None,
        notes: str = "",
        success_weight: float = 1.0,
        active: bool = True,
    ) -> ApprovedExampleRecord:
        return self.repository.create(
            ApprovedExampleRecord(
                created_utc=_utc_now(),
                example_query=example_query,
                normalized_query=normalized_query,
                intent=intent,
                metric=metric,
                entity=entity,
                filters_json=list(filters_json or []),
                notes=notes,
                success_weight=float(success_weight or 1.0),
                last_used_utc="",
                active=bool(active),
            )
        )

    def find_similar_examples(self, query: str, limit: int = 5) -> List[ApprovedExampleRecord]:
        normalized = self.alias_service.apply_aliases(_normalize_query(query))
        scored = []
        for record in self.repository.list_active(limit=200):
            score = _similarity_score(normalized, self.alias_service.apply_aliases(record.normalized_query))
            if score <= 0:
                continue
            scored.append((score + min(0.25, float(record.success_weight or 0.0) * 0.05), record))
        scored.sort(key=lambda item: (item[0], item[1].last_used_utc, item[1].id or 0), reverse=True)
        return [record for _score, record in scored[: max(1, int(limit))]]

    def mark_used(self, example_id: int):
        if example_id:
            self.repository.touch(example_id, _utc_now())

    def approve_query(self, query: str, plan: QueryPlan, notes: str = "") -> ApprovedExampleRecord:
        normalized_query = self.alias_service.apply_aliases(_normalize_query(query))
        entity = _normalize_text(
            plan.source_layer_name or plan.target_layer_name or plan.boundary_layer_name or ""
        )
        filters_json = [item.to_dict() for item in plan.filters]
        filters_key = _filters_signature(filters_json)
        for record in self.repository.list_active(limit=300):
            if (
                self.alias_service.apply_aliases(record.normalized_query) == normalized_query
                and _normalize_text(record.intent) == _normalize_text(plan.intent)
                and _normalize_text(record.metric) == _normalize_text(plan.metric.operation)
                and _normalize_text(record.entity) == entity
                and _filters_signature(record.filters_json) == filters_key
            ):
                updated_weight = float(record.success_weight or 0.0) + 1.0
                self.repository.update(
                    example_id=int(record.id or 0),
                    last_used_utc=_utc_now(),
                    success_weight=updated_weight,
                )
                record.success_weight = updated_weight
                record.last_used_utc = _utc_now()
                return record
        return self.repository.create(
            ApprovedExampleRecord(
                created_utc=_utc_now(),
                example_query=query,
                normalized_query=normalized_query,
                intent=plan.intent,
                metric=plan.metric.operation,
                entity=entity,
                filters_json=filters_json,
                notes=notes,
                success_weight=1.0,
                last_used_utc=_utc_now(),
                active=True,
            )
        )


class QueryMemoryService:
    def __init__(
        self,
        repository: IQueryMemoryRepository,
        feedback_service: QueryFeedbackService,
        alias_service: SemanticAliasService,
        approved_example_service: ApprovedExampleService,
    ):
        self.repository = repository
        self.feedback_service = feedback_service
        self.alias_service = alias_service
        self.approved_example_service = approved_example_service

    def start_query(
        self,
        raw_query: str,
        session_id: str,
        user_id: str = "",
        source_context_json: Optional[Dict[str, Any]] = None,
        normalized_query_override: str = "",
    ) -> QueryHistoryHandle:
        normalized_query = normalized_query_override or _normalize_query(raw_query)
        handle = QueryHistoryHandle(
            history_id=None,
            session_id=session_id,
            raw_query=raw_query,
            normalized_query=normalized_query,
            source_context_json=dict(source_context_json or {}),
            started_perf=perf_counter(),
        )
        record = self.repository.create(
            QueryHistoryRecord(
                created_utc=_utc_now(),
                user_id=user_id,
                session_id=session_id,
                raw_query=raw_query,
                normalized_query=normalized_query,
                source_context_json=handle.source_context_json,
            )
        )
        handle.history_id = record.id
        log_info(
            "[Relatorios] memoria "
            f"event=query_started query_id={handle.history_id} session_id={session_id} normalized='{normalized_query}'"
        )
        return handle

    def register_interpretation(
        self,
        handle: QueryHistoryHandle,
        interpretation: InterpretationResult,
        source_context_json: Optional[Dict[str, Any]] = None,
    ) -> None:
        if handle.history_id is None:
            return
        plan = interpretation.plan
        chosen = self._build_hypothesis_payload(plan, interpretation.confidence, interpretation.source) if plan is not None else {}
        self.repository.update(
            handle.history_id,
            {
                "intent": plan.intent if plan is not None else interpretation.status,
                "metric": plan.metric.operation if plan is not None else "",
                "entity": self._entity_from_plan(plan),
                "filters_json": [item.to_dict() for item in (plan.filters if plan is not None else [])],
                "hypotheses_json": self._build_hypotheses_payload(interpretation),
                "chosen_hypothesis_json": chosen,
                "confidence": float(interpretation.confidence or 0.0),
                "source_context_json": dict(source_context_json or handle.source_context_json or {}),
            },
        )

    def rerank_interpretation(
        self,
        question: str,
        interpretation: InterpretationResult,
        session_id: str = "",
    ) -> InterpretationResult:
        if interpretation is None:
            return interpretation

        candidate_interpretations = self._collect_rerank_candidates(interpretation)
        if not candidate_interpretations:
            return interpretation

        normalized_query = self.alias_service.apply_aliases(_normalize_query(question))
        similar_queries = self.find_similar_queries(question, session_id=session_id, limit=5)
        similar_examples = self.find_similar_examples(question, limit=5)
        active_aliases = self.list_active_aliases(limit=300)

        scored = []
        for candidate in candidate_interpretations:
            plan = candidate.plan
            if plan is None:
                continue
            base_score = float(candidate.confidence or interpretation.confidence or 0.0)
            memory_boost, reason = self._score_candidate_from_memory(
                normalized_query=normalized_query,
                plan=plan,
                similar_queries=similar_queries,
                similar_examples=similar_examples,
                aliases=active_aliases,
            )
            scored.append(
                (
                    min(0.99, base_score + memory_boost),
                    candidate,
                    reason,
                )
            )

        if not scored:
            return interpretation

        scored.sort(
            key=lambda item: (
                item[0],
                len(item[1].plan.filters if item[1].plan is not None else []),
                item[1].label.lower(),
            ),
            reverse=True,
        )

        primary_signature = self._plan_signature(interpretation.plan)
        best_score, best_candidate, best_reason = scored[0]
        sorted_candidates = []
        seen = set()
        for score, candidate, _reason in scored:
            signature = self._plan_signature(candidate.plan)
            if signature in seen:
                continue
            seen.add(signature)
            sorted_candidates.append(
                CandidateInterpretation(
                    label=candidate.label,
                    reason=self._merge_reason(candidate.reason, _reason),
                    confidence=score,
                    plan=copy.deepcopy(candidate.plan) if candidate.plan is not None else None,
                )
            )

        interpretation.candidate_interpretations = sorted_candidates
        current_score = float(interpretation.confidence or 0.0)
        should_promote = (
            best_candidate.plan is not None
            and self._plan_signature(best_candidate.plan) != primary_signature
            and (not primary_signature or best_score >= current_score + 0.05)
        )
        if should_promote:
            interpretation.plan = copy.deepcopy(best_candidate.plan)
            interpretation.confidence = best_score
            interpretation.source = f"{interpretation.source}+memory"
            if interpretation.status == "ok":
                interpretation.message = ""
            log_info(
                "[Relatorios] memoria rerank "
                f"question='{question}' promoted='{best_candidate.label}' reason='{best_reason}'"
            )
        else:
            interpretation.confidence = max(float(interpretation.confidence or 0.0), best_score)
            log_info(
                "[Relatorios] memoria rerank "
                f"question='{question}' kept='{best_candidate.label}' reason='{best_reason}'"
            )
        return interpretation

    def mark_query_success(
        self,
        handle: QueryHistoryHandle,
        plan: QueryPlan,
        result: QueryResult,
        duration_ms: Optional[int] = None,
    ) -> None:
        if handle.history_id is None:
            return
        elapsed_ms = self._elapsed_ms(handle, duration_ms)
        self.repository.update(
            handle.history_id,
            {
                "intent": plan.intent,
                "metric": plan.metric.operation,
                "entity": self._entity_from_plan(plan),
                "filters_json": [item.to_dict() for item in plan.filters],
                "chosen_hypothesis_json": self._build_hypothesis_payload(plan, 1.0, "executed"),
                "execution_payload_json": plan.to_dict(),
                "execution_result_summary": (result.summary.text or result.message or "").strip(),
                "success_flag": True,
                "error_message": "",
                "duration_ms": elapsed_ms,
            },
        )
        log_info(
            "[Relatorios] memoria "
            f"event=query_success query_id={handle.history_id} duration_ms={elapsed_ms}"
        )

    def mark_query_failure(
        self,
        handle: QueryHistoryHandle,
        error_message: str,
        duration_ms: Optional[int] = None,
        plan: Optional[QueryPlan] = None,
        execution_payload_json: Optional[Dict[str, Any]] = None,
    ) -> None:
        if handle.history_id is None:
            return
        elapsed_ms = self._elapsed_ms(handle, duration_ms)
        payload = execution_payload_json or (plan.to_dict() if plan is not None else {})
        self.repository.update(
            handle.history_id,
            {
                "intent": plan.intent if plan is not None else "",
                "metric": plan.metric.operation if plan is not None else "",
                "entity": self._entity_from_plan(plan),
                "filters_json": [item.to_dict() for item in (plan.filters if plan is not None else [])],
                "execution_payload_json": payload,
                "execution_result_summary": "",
                "success_flag": False,
                "error_message": error_message,
                "duration_ms": elapsed_ms,
            },
        )
        log_warning(
            "[Relatorios] memoria "
            f"event=query_failure query_id={handle.history_id} duration_ms={elapsed_ms} error='{error_message}'"
        )

    def register_explicit_feedback(
        self,
        query_history_id: int,
        feedback_type: str,
        plan: Optional[QueryPlan] = None,
        notes: str = "",
        user_action_json: Optional[Dict[str, Any]] = None,
    ):
        return self.feedback_service.register_explicit_feedback(
            query_history_id=query_history_id,
            feedback_type=feedback_type,
            corrected_intent=plan.intent if plan is not None else "",
            corrected_metric=plan.metric.operation if plan is not None else "",
            corrected_entity=self._entity_from_plan(plan),
            corrected_filters_json=[item.to_dict() for item in (plan.filters if plan is not None else [])],
            notes=notes,
            user_action_json=user_action_json,
        )

    def register_implicit_feedback(
        self,
        query_history_id: int,
        feedback_type: str,
        notes: str = "",
        user_action_json: Optional[Dict[str, Any]] = None,
    ):
        return self.feedback_service.register_implicit_feedback(
            query_history_id=query_history_id,
            feedback_type=feedback_type,
            notes=notes,
            user_action_json=user_action_json,
        )

    def register_correction(
        self,
        query_history_id: int,
        corrected_plan: Optional[QueryPlan] = None,
        notes: str = "",
        user_action_json: Optional[Dict[str, Any]] = None,
    ):
        return self.feedback_service.register_correction(
            query_history_id=query_history_id,
            corrected_intent=corrected_plan.intent if corrected_plan is not None else "",
            corrected_metric=corrected_plan.metric.operation if corrected_plan is not None else "",
            corrected_entity=self._entity_from_plan(corrected_plan),
            corrected_filters_json=[item.to_dict() for item in (corrected_plan.filters if corrected_plan is not None else [])],
            notes=notes,
            user_action_json=user_action_json,
        )

    def find_similar_queries(
        self,
        query: str,
        session_id: str = "",
        limit: int = 5,
    ) -> List[SimilarQueryMatch]:
        normalized = self.alias_service.apply_aliases(_normalize_query(query))
        records = self.repository.list_recent_by_session(session_id, limit=120) if session_id else self.repository.list_all(limit=240)
        scored = []
        for record in records:
            score = _similarity_score(normalized, self.alias_service.apply_aliases(record.normalized_query))
            if score <= 0:
                continue
            if record.success_flag is True:
                score += 0.08
            scored.append(
                SimilarQueryMatch(
                    query_history_id=int(record.id or 0),
                    raw_query=record.raw_query,
                    normalized_query=record.normalized_query,
                    intent=record.intent,
                    metric=record.metric,
                    entity=record.entity,
                    filters_json=list(record.filters_json or []),
                    execution_result_summary=record.execution_result_summary,
                    success_flag=record.success_flag,
                    score=min(1.0, score),
                )
            )
        scored.sort(key=lambda item: (item.score, item.query_history_id), reverse=True)
        return scored[: max(1, int(limit))]

    def list_recent_queries(self, session_id: str, limit: int = 10):
        return self.repository.list_recent_by_session(session_id=session_id, limit=limit)

    def find_similar_examples(self, query: str, limit: int = 5):
        return self.approved_example_service.find_similar_examples(query=query, limit=limit)

    def list_active_aliases(self, alias_type: str = "", limit: int = 200):
        return self.alias_service.list_active_aliases(alias_type=alias_type, limit=limit)

    def find_frequent_errors(self, limit: int = 10) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for record in self.repository.list_all(limit=500):
            if record.success_flag is not False or not record.error_message:
                continue
            key = record.error_message.strip()
            if not key:
                continue
            bucket = grouped.setdefault(
                key,
                {"error_message": key, "count": 0, "sample_query": record.raw_query},
            )
            bucket["count"] += 1
        items = sorted(grouped.values(), key=lambda item: (item["count"], item["error_message"]), reverse=True)
        return items[: max(1, int(limit))]

    def _elapsed_ms(self, handle: QueryHistoryHandle, duration_ms: Optional[int]) -> int:
        if duration_ms is not None:
            return max(0, int(duration_ms))
        return max(0, int((perf_counter() - float(handle.started_perf or perf_counter())) * 1000))

    def _entity_from_plan(self, plan: Optional[QueryPlan]) -> str:
        if plan is None:
            return ""
        if plan.source_layer_name:
            return plan.source_layer_name
        if plan.target_layer_name:
            return plan.target_layer_name
        if plan.boundary_layer_name:
            return plan.boundary_layer_name
        return ""

    def _build_hypothesis_payload(
        self,
        plan: Optional[QueryPlan],
        confidence: float,
        source: str,
    ) -> Dict[str, Any]:
        if plan is None:
            return {}
        return {
            "label": plan.understanding_text or plan.group_label or plan.intent,
            "confidence": float(confidence or 0.0),
            "source": source,
            "plan": plan.to_dict(),
        }

    def _build_hypotheses_payload(self, interpretation: InterpretationResult) -> List[Dict[str, Any]]:
        payloads: List[Dict[str, Any]] = []
        for candidate in getattr(interpretation, "candidate_interpretations", []) or []:
            payloads.append(_candidate_to_payload(candidate))
        if not payloads:
            for option in getattr(interpretation, "options", []) or []:
                payloads.append(
                    {
                        "label": str(getattr(option, "label", "") or ""),
                        "reason": str(getattr(option, "reason", "") or ""),
                        "confidence": float(getattr(option, "confidence", 0.0) or 0.0),
                        "plan": {},
                        "overrides": option.to_overrides(),
                    }
                )
        if not payloads and interpretation.plan is not None:
            payloads.append(self._build_hypothesis_payload(interpretation.plan, interpretation.confidence, interpretation.source))
        return payloads

    def _collect_rerank_candidates(self, interpretation: InterpretationResult) -> List[CandidateInterpretation]:
        candidates: List[CandidateInterpretation] = []
        seen = set()
        if interpretation.plan is not None:
            signature = self._plan_signature(interpretation.plan)
            seen.add(signature)
            candidates.append(
                CandidateInterpretation(
                    label=interpretation.plan.understanding_text or interpretation.plan.group_label or "Interpretacao principal",
                    reason="Hipotese atual",
                    confidence=float(interpretation.confidence or 0.0),
                    plan=copy.deepcopy(interpretation.plan),
                )
            )
        for candidate in interpretation.candidate_interpretations:
            if candidate.plan is None:
                continue
            signature = self._plan_signature(candidate.plan)
            if signature in seen:
                continue
            seen.add(signature)
            candidates.append(
                CandidateInterpretation(
                    label=candidate.label,
                    reason=candidate.reason,
                    confidence=float(candidate.confidence or 0.0),
                    plan=copy.deepcopy(candidate.plan),
                )
            )
        return candidates

    def _score_candidate_from_memory(
        self,
        normalized_query: str,
        plan: QueryPlan,
        similar_queries: List[SimilarQueryMatch],
        similar_examples: List[ApprovedExampleRecord],
        aliases: List[SemanticAliasRecord],
    ):
        query_support = self._query_plan_support_score(normalized_query, plan)
        if query_support <= 0.0:
            return 0.0, ""

        boost = 0.0
        reasons: List[str] = []
        for match in similar_queries:
            alignment = self._plan_alignment_score(
                plan,
                match.intent,
                match.metric,
                match.entity,
                match.filters_json,
            )
            if alignment <= 0:
                continue
            contribution = alignment * float(match.score or 0.0) * 0.30
            boost += contribution
            reasons.append(f"historico:{match.query_history_id}")
        for example in similar_examples:
            example_score = _similarity_score(
                normalized_query,
                self.alias_service.apply_aliases(example.normalized_query),
            )
            alignment = self._plan_alignment_score(
                plan,
                example.intent,
                example.metric,
                example.entity,
                example.filters_json,
            )
            if alignment <= 0 or example_score <= 0:
                continue
            contribution = alignment * example_score * min(0.35, 0.18 + float(example.success_weight or 0.0) * 0.04)
            boost += contribution
            reasons.append(f"exemplo:{example.id}")
        alias_hits = self._alias_hits_for_plan(normalized_query, plan, aliases)
        if alias_hits:
            boost += min(0.08, alias_hits * 0.02)
            reasons.append(f"aliases:{alias_hits}")
        boost *= max(0.20, query_support)
        if query_support < 0.75:
            reasons.append(f"suporte:{query_support:.2f}")
        return boost, ", ".join(reasons[:4])

    def _plan_alignment_score(
        self,
        plan: QueryPlan,
        intent: str,
        metric: str,
        entity: str,
        filters_json: Optional[List[Dict[str, Any]]] = None,
    ) -> float:
        score = 0.0
        if _normalize_text(plan.intent) and _normalize_text(plan.intent) == _normalize_text(intent):
            score += 0.30
        if _normalize_text(plan.metric.operation) and _normalize_text(plan.metric.operation) == _normalize_text(metric):
            score += 0.30
        if _normalize_text(self._entity_from_plan(plan)) and _normalize_text(self._entity_from_plan(plan)) == _normalize_text(entity):
            score += 0.18
        filter_alignment = self._filter_alignment_score([item.to_dict() for item in plan.filters], filters_json or [])
        score += filter_alignment * 0.22
        return min(1.0, score)

    def _filter_alignment_score(self, left_filters: List[Dict[str, Any]], right_filters: List[Dict[str, Any]]) -> float:
        left_signature = _filters_signature(left_filters)
        right_signature = _filters_signature(right_filters)
        if not left_signature or not right_signature:
            return 0.0
        left_set = set(left_signature.split("|"))
        right_set = set(right_signature.split("|"))
        overlap = len(left_set & right_set)
        union = len(left_set | right_set)
        return overlap / max(1, union)

    def _alias_hits_for_plan(
        self,
        normalized_query: str,
        plan: QueryPlan,
        aliases: List[SemanticAliasRecord],
    ) -> int:
        if not normalized_query:
            return 0
        plan_text = " ".join(
            [
                _normalize_text(plan.intent),
                _normalize_text(plan.metric.operation),
                _normalize_text(self._entity_from_plan(plan)),
                _normalize_text(plan.understanding_text),
                _normalize_text(" ".join(str(item.value) for item in plan.filters)),
            ]
        )
        hits = 0
        padded_query = f" {normalized_query} "
        for alias in aliases:
            alias_term = _normalize_text(alias.alias_term)
            canonical_term = _normalize_text(alias.canonical_term)
            if not alias_term or not canonical_term:
                continue
            if f" {alias_term} " in padded_query and canonical_term in plan_text:
                hits += 1
        return hits

    def _query_plan_support_score(self, normalized_query: str, plan: QueryPlan) -> float:
        query_tokens = _meaningful_query_tokens(normalized_query)
        if not query_tokens:
            return 1.0

        plan_text = self.alias_service.apply_aliases(
            " ".join(
                [
                    _normalize_text(plan.intent),
                    _normalize_text(plan.metric.operation),
                    _normalize_text(plan.metric.field),
                    _normalize_text(plan.metric.field_label),
                    _normalize_text(plan.group_field),
                    _normalize_text(plan.group_label),
                    _normalize_text(plan.understanding_text),
                    _normalize_text(plan.detected_filters_text),
                    _normalize_text(" ".join(str(item.value) for item in plan.filters)),
                ]
            )
        )
        plan_tokens = set(_tokenize(plan_text))
        if not plan_tokens:
            return 0.0

        supported = 0
        for token in query_tokens:
            if token in plan_tokens:
                supported += 1
                continue
            if len(token) >= 3 and any(plan_token.startswith(token) or token.startswith(plan_token) for plan_token in plan_tokens):
                supported += 1
        return supported / max(1, len(query_tokens))

    def _plan_signature(self, plan: Optional[QueryPlan]) -> str:
        if plan is None:
            return ""
        return "|".join(
            [
                _normalize_text(plan.intent),
                _normalize_text(plan.metric.operation),
                _normalize_text(self._entity_from_plan(plan)),
                _normalize_text(plan.group_field),
                _filters_signature([item.to_dict() for item in plan.filters]),
            ]
        )

    def _merge_reason(self, base: str, extra: str) -> str:
        parts = [part.strip() for part in [base, extra] if part and part.strip()]
        return " | ".join(parts[:3])


def build_operational_memory_services() -> Dict[str, Any]:
    store = OperationalMemoryStore()
    query_repository = QueryMemoryRepository(store)
    feedback_repository = FeedbackRepository(store)
    alias_repository = SemanticAliasRepository(store)
    approved_example_repository = ApprovedExampleRepository(store)

    alias_service = SemanticAliasService(alias_repository)
    feedback_service = QueryFeedbackService(feedback_repository)
    approved_example_service = ApprovedExampleService(approved_example_repository, alias_service)
    query_memory_service = QueryMemoryService(
        repository=query_repository,
        feedback_service=feedback_service,
        alias_service=alias_service,
        approved_example_service=approved_example_service,
    )
    conversation_memory_service = ConversationMemoryService(store)
    return {
        "store": store,
        "query_memory_service": query_memory_service,
        "feedback_service": feedback_service,
        "alias_service": alias_service,
        "approved_example_service": approved_example_service,
        "conversation_memory_service": conversation_memory_service,
    }


def _filters_signature(filters_json: List[Dict[str, Any]]) -> str:
    items = []
    for item in filters_json or []:
        field = _normalize_text(item.get("field"))
        value = _normalize_text(item.get("value"))
        operator = _normalize_text(item.get("operator") or "eq")
        role = _normalize_text(item.get("layer_role") or "target")
        if not field:
            continue
        items.append(f"{role}:{field}:{operator}:{value}")
    return "|".join(sorted(items))
