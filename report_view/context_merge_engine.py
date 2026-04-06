from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from .conversation_state import ConversationState, query_plan_from_payload
from .result_models import FilterSpec, InterpretationResult, QueryPlan
from .text_utils import normalize_text


ENTITY_LABELS = {
    "rede": "rede",
    "ligacao": "ligacoes",
    "lote": "lotes",
    "parcela": "parcelas",
    "hidrante": "hidrantes",
    "cliente": "clientes",
}


class ContextMergeEngine:
    def build_merged_question(
        self,
        previous_state: Optional[ConversationState],
        delta: Optional[Dict[str, Any]],
        new_input: str,
    ) -> str:
        if previous_state is None or previous_state.active_query is None:
            return new_input
        delta = dict(delta or {})
        if delta.get("reset_context"):
            return new_input
        base = previous_state.active_query.copy()
        semantic_filters = dict(base.filters or {})
        for key in list(delta.get("remove_filter_kinds") or []):
            semantic_filters.pop(key, None)
        semantic_filters.update(dict(delta.get("add_filters") or {}))
        semantic_filters.update(dict(delta.get("replace_filters") or {}))

        entity = delta.get("entity") or base.entity or ""
        group_by = delta.get("group_by") or base.group_by or ""
        aggregation = delta.get("aggregation") or base.aggregation or base.metric or ""
        metric = delta.get("metric") or base.metric or aggregation
        target_field = delta.get("target_field") or base.target_field or ""
        return self._compose_query(
            entity=entity,
            metric=metric,
            aggregation=aggregation,
            target_field=target_field,
            group_by=group_by,
            semantic_filters=semantic_filters,
        )

    def merge(
        self,
        previous_state: Optional[ConversationState],
        delta: Optional[Dict[str, Any]],
        new_interpretation: InterpretationResult,
    ) -> InterpretationResult:
        result = copy.deepcopy(new_interpretation)
        delta = dict(delta or {})
        if previous_state is None or previous_state.active_query is None:
            return self._annotate_trace(result, None, delta)
        if delta.get("reset_context"):
            return self._annotate_trace(result, previous_state, delta)
        if result.plan is None:
            return self._annotate_trace(result, previous_state, delta)

        base_plan = previous_state.active_query.to_plan() or query_plan_from_payload(previous_state.active_query.plan_payload)
        if base_plan is None:
            return self._annotate_trace(result, previous_state, delta)

        plan = result.plan
        followup_type = delta.get("followup_type") or ""
        if followup_type in {"ADD_FILTER", "CHANGE_LOCATION", "DRILL_DOWN"}:
            self._merge_layers(base_plan, plan)
            self._merge_filters(base_plan, plan, delta)
            if not delta.get("group_by") and base_plan.group_field and not plan.group_field:
                plan.group_field = base_plan.group_field
                plan.group_label = base_plan.group_label
                plan.group_field_kind = base_plan.group_field_kind
            if not delta.get("metric") and not delta.get("aggregation"):
                plan.metric = copy.deepcopy(base_plan.metric)
            if plan.top_n is None:
                plan.top_n = base_plan.top_n
        elif followup_type == "CHANGE_GROUP":
            self._merge_layers(base_plan, plan)
            self._merge_filters(base_plan, plan, delta)
            if not delta.get("metric") and not delta.get("aggregation"):
                plan.metric = copy.deepcopy(base_plan.metric)
        elif followup_type == "CHANGE_METRIC":
            self._merge_layers(base_plan, plan)
            self._merge_filters(base_plan, plan, delta)
            if not plan.group_field and base_plan.group_field:
                plan.group_field = base_plan.group_field
                plan.group_label = base_plan.group_label
                plan.group_field_kind = base_plan.group_field_kind

        if not plan.intent_label:
            plan.intent_label = base_plan.intent_label
        result.plan = plan
        if result.status in {"unsupported", "ambiguous"} and result.plan is not None:
            result.status = "confirm"
            result.needs_confirmation = True
        return self._annotate_trace(result, previous_state, delta)

    def _merge_layers(self, base_plan: QueryPlan, plan: QueryPlan):
        if not plan.target_layer_id:
            plan.target_layer_id = base_plan.target_layer_id
            plan.target_layer_name = base_plan.target_layer_name
        if not plan.source_layer_id:
            plan.source_layer_id = base_plan.source_layer_id
            plan.source_layer_name = base_plan.source_layer_name
        if not plan.boundary_layer_id and not any(item.field == plan.group_field for item in plan.filters):
            plan.boundary_layer_id = plan.boundary_layer_id or base_plan.boundary_layer_id
            plan.boundary_layer_name = plan.boundary_layer_name or base_plan.boundary_layer_name
        if not plan.spatial_relation:
            plan.spatial_relation = base_plan.spatial_relation

    def _merge_filters(self, base_plan: QueryPlan, plan: QueryPlan, delta: Dict[str, Any]):
        plan.filters = list(plan.filters or [])
        remove_kinds = set(delta.get("remove_filter_kinds") or [])
        replace_kinds = set(dict(delta.get("replace_filters") or {}).keys())
        existing_signatures = {
            self._filter_signature(item)
            for item in plan.filters
        }
        merged_filters: List[FilterSpec] = []
        for item in base_plan.filters or []:
            semantic_kind = self._filter_semantic_kind(item)
            if semantic_kind in remove_kinds or semantic_kind in replace_kinds:
                continue
            signature = self._filter_signature(item)
            if signature in existing_signatures:
                continue
            merged_filters.append(copy.deepcopy(item))
            existing_signatures.add(signature)
        merged_filters.extend(plan.filters)
        plan.filters = merged_filters

    def _filter_signature(self, item: FilterSpec) -> str:
        return "|".join(
            [
                normalize_text(item.layer_role or "target"),
                normalize_text(item.field or ""),
                normalize_text(item.operator or "eq"),
                normalize_text(item.value),
            ]
        )

    def _filter_semantic_kind(self, item: FilterSpec) -> str:
        field_text = normalize_text(item.field)
        if any(token in field_text for token in ("municipio", "cidade", "bairro", "localidade")):
            return "location"
        if any(token in field_text for token in ("situacao", "status")):
            return "status"
        if any(token in field_text for token in ("material",)):
            return "material"
        if any(token in field_text for token in ("diam", "bitola", "dn")):
            return "diameter"
        if any(token in field_text for token in ("agua", "esgoto", "servico", "sistema")):
            return "service"
        return ""

    def _annotate_trace(
        self,
        interpretation: InterpretationResult,
        previous_state: Optional[ConversationState],
        delta: Dict[str, Any],
    ) -> InterpretationResult:
        if interpretation.plan is None:
            return interpretation
        plan = interpretation.plan
        trace = dict(plan.planning_trace or {})
        debug = list(trace.get("conversation_debug") or [])
        if previous_state is not None and previous_state.active_query is not None and not delta.get("reset_context"):
            debug.append("Entendi como continuacao da consulta anterior")
        for note in list(delta.get("notes") or []):
            normalized_note = str(note).strip()
            if normalized_note:
                debug.append(normalized_note.rstrip("."))
        deduped_debug: List[str] = []
        seen = set()
        for item in debug:
            normalized = normalize_text(item)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped_debug.append(item)
        trace["conversation_is_followup"] = bool(delta.get("followup_type"))
        trace["conversation_followup_type"] = delta.get("followup_type") or ""
        trace["conversation_delta"] = dict(delta or {})
        trace["conversation_debug"] = deduped_debug[:5]
        plan.planning_trace = trace
        return interpretation

    def _compose_query(
        self,
        entity: str,
        metric: str,
        aggregation: str,
        target_field: str,
        group_by: str,
        semantic_filters: Dict[str, str],
    ) -> str:
        subject = ENTITY_LABELS.get(normalize_text(entity), entity or "registros")
        metric_key = normalize_text(metric or aggregation or "")
        target_key = normalize_text(target_field)

        if metric_key in {"max", "min"}:
            adjective = "maior" if metric_key == "max" else "menor"
            if target_key in {"diametro", "dn", "bitola"}:
                base = f"qual o {adjective} diametro"
            elif target_field:
                base = f"qual o {adjective} {target_field}"
            else:
                base = f"qual o valor {adjective}"
        elif metric_key in {"length", "extensao"}:
            base = f"quantos metros de {subject}"
        elif metric_key == "area":
            base = f"qual a area total de {subject}"
        elif metric_key in {"avg", "media"}:
            base = f"qual a media de {subject}"
        elif metric_key in {"sum", "total"}:
            base = f"qual o total de {subject}"
        else:
            base = f"quantidade de {subject}"

        parts = [base]
        if semantic_filters.get("service"):
            parts.append(f"de {semantic_filters['service']}")
        if semantic_filters.get("material"):
            parts.append(f"de {semantic_filters['material']}")
        if semantic_filters.get("diameter") and target_key not in {"diametro", "dn", "bitola"}:
            parts.append(f"dn {semantic_filters['diameter']}")
        if semantic_filters.get("status"):
            parts.append(f"com status {semantic_filters['status']}")
        for key in sorted(semantic_filters.keys()):
            if key.startswith("generic_"):
                parts.append(f"com {semantic_filters[key]}")
        if semantic_filters.get("location"):
            parts.append(f"em {semantic_filters['location']}")
        if group_by:
            parts.append(f"por {group_by}")
        return " ".join(part for part in parts if str(part or "").strip()).strip()
