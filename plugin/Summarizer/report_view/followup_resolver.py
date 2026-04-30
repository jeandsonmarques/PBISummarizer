from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .conversation_state import ConversationState
from .domain_packs import ProjectPack
from .query_preprocessor import (
    LOCATION_PREFIXES,
    LOCATION_QUALIFIER_PATTERNS,
    LOCATION_STOP_WORDS,
    QueryPreprocessor,
    SERVICE_TERMS,
)
from .text_utils import normalize_text


FOLLOWUP_TYPES = {
    "ADD_FILTER",
    "CHANGE_LOCATION",
    "CHANGE_GROUP",
    "CHANGE_METRIC",
    "DRILL_DOWN",
    "RESET_CONTEXT",
}
FOLLOWUP_PREFIXES = ("e ", "agora", "dessas", "desses", "destas", "destes", "usa", "mostra")
RESET_PREFIXES = ("agora sobre", "mude para", "troque para", "outro assunto", "agora falando de")
GROUP_TERMS = ("bairro", "municipio", "cidade", "localidade", "setor", "tipo", "classe", "material", "diametro", "dn")
METRIC_CHANGE_TERMS = ("quantidade", "quantos", "quantas", "metros", "metro", "extensao", "area", "media", "soma", "total")
STATUS_VALUES = {
    "Ativo": ("ativo", "ativa", "ativos", "ativas"),
    "Inativo": ("inativo", "inativa", "inativos", "inativas"),
    "Cancelado": ("cancelado", "cancelada", "cancelados", "canceladas"),
    "Suspenso": ("suspenso", "suspensa", "suspensos", "suspensas"),
}
MATERIAL_VALUES = ()
ENTITY_RESET_TERMS = ()


class FollowupResolver:
    def __init__(self, project_pack: Optional[ProjectPack] = None):
        self.project_pack = project_pack
        self.preprocessor = QueryPreprocessor(project_pack=project_pack)

    def is_followup(self, query: str, conversation_state: Optional[ConversationState] = None) -> bool:
        if conversation_state is None or conversation_state.active_query is None:
            return False
        normalized = normalize_text(query)
        if not normalized:
            return False
        if any(normalized.startswith(prefix) for prefix in RESET_PREFIXES):
            return True
        if any(normalized.startswith(prefix) for prefix in FOLLOWUP_PREFIXES):
            return True
        preprocessed = self.preprocessor.preprocess(query)
        current_entity = normalize_text(preprocessed.subject_hint or self._extract_entity(normalized))
        previous_entity = normalize_text(conversation_state.active_query.entity or "")
        if current_entity and previous_entity and current_entity != previous_entity:
            return False
        tokens = [token for token in normalized.split() if token]
        if len(tokens) <= 4 and not current_entity:
            return True
        followup_type = self.classify_followup_type(query, conversation_state)
        if not followup_type:
            return False
        if current_entity:
            return False
        return len(tokens) <= 4

    def classify_followup_type(self, query: str, conversation_state: Optional[ConversationState] = None) -> str:
        if conversation_state is None or conversation_state.active_query is None:
            return ""
        normalized = normalize_text(query)
        if not normalized:
            return ""
        if any(normalized.startswith(prefix) for prefix in RESET_PREFIXES):
            return "RESET_CONTEXT"
        if any(term in normalized for term in ("dessas", "desses", "destas", "destes")):
            return "DRILL_DOWN"
        if re.search(r"\bpor\s+([a-z0-9_ ]+)$", normalized):
            return "CHANGE_GROUP"
        if any(term in normalized for term in ("maior", "menor", "maximo", "minimo", "media", "soma", "total")):
            return "CHANGE_METRIC"
        extracted = self.extract_delta(query, conversation_state)
        if extracted.get("reset_context"):
            return "RESET_CONTEXT"
        if extracted.get("group_by"):
            return "CHANGE_GROUP"
        if extracted.get("metric") or extracted.get("aggregation") or extracted.get("target_field"):
            return "CHANGE_METRIC"
        if extracted.get("replace_filters", {}).get("location"):
            return "CHANGE_LOCATION"
        if extracted.get("add_filters") or extracted.get("replace_filters"):
            return "ADD_FILTER"
        return ""

    def extract_delta(self, query: str, conversation_state: Optional[ConversationState] = None) -> Dict[str, Any]:
        state = conversation_state.active_query if conversation_state is not None else None
        preprocessed = self.preprocessor.preprocess(query)
        normalized = normalize_text(preprocessed.corrected_text or query)
        delta: Dict[str, Any] = {
            "followup_type": "",
            "add_filters": {},
            "replace_filters": {},
            "remove_filter_kinds": [],
            "group_by": "",
            "aggregation": "",
            "metric": "",
            "target_field": "",
            "entity": "",
            "reset_context": False,
            "confidence": 0.0,
            "notes": [],
        }

        if any(normalized.startswith(prefix) for prefix in RESET_PREFIXES):
            delta["followup_type"] = "RESET_CONTEXT"
            delta["reset_context"] = True
            delta["entity"] = preprocessed.subject_hint or self._extract_entity(normalized)
            delta["confidence"] = 0.96
            delta["notes"].append("Contexto anterior limpo para novo assunto.")
            return delta

        location = self._extract_location(normalized)
        status = self._extract_status(normalized)
        material = self._extract_material(normalized)
        service = self._extract_service(normalized)
        diameter = self._extract_diameter(normalized)
        if location:
            normalized_location = normalize_text(location)
            if normalized_location in {
                normalize_text(material),
                normalize_text(service),
                normalize_text(status),
                normalize_text(diameter),
            }:
                location = ""

        if preprocessed.group_phrase:
            delta["followup_type"] = "CHANGE_GROUP"
            delta["group_by"] = preprocessed.group_phrase
            delta["confidence"] = 0.94
            delta["notes"].append(f"Agrupamento alterado para {preprocessed.group_phrase}.")
        elif preprocessed.group_hint:
            delta["followup_type"] = "CHANGE_GROUP"
            delta["group_by"] = preprocessed.group_hint
            delta["confidence"] = 0.92
            delta["notes"].append(f"Agrupamento alterado para {preprocessed.group_hint}.")

        if any(term in normalized for term in ("maior", "maximo", "ate qual")):
            delta["followup_type"] = "CHANGE_METRIC"
            delta["aggregation"] = "max"
            delta["metric"] = "max"
            delta["target_field"] = "diametro" if "diam" in normalized or "dn" in normalized else preprocessed.attribute_hint or preprocessed.metric_hint
            delta["confidence"] = max(float(delta["confidence"] or 0.0), 0.92)
            if delta["target_field"] == "diametro":
                delta["remove_filter_kinds"] = ["diameter"]
            delta["notes"].append("Metrica alterada para valor maximo.")
        elif any(term in normalized for term in ("menor", "minimo")):
            delta["followup_type"] = "CHANGE_METRIC"
            delta["aggregation"] = "min"
            delta["metric"] = "min"
            delta["target_field"] = "diametro" if "diam" in normalized or "dn" in normalized else preprocessed.attribute_hint or preprocessed.metric_hint
            delta["confidence"] = max(float(delta["confidence"] or 0.0), 0.92)
            if delta["target_field"] == "diametro":
                delta["remove_filter_kinds"] = ["diameter"]
            delta["notes"].append("Metrica alterada para valor minimo.")
        elif (
            preprocessed.metric_hint in {"count", "length", "area", "sum", "avg"}
            and len((normalized or "").split()) <= 8
            and any(term in normalized for term in METRIC_CHANGE_TERMS)
        ):
            delta["followup_type"] = "CHANGE_METRIC"
            delta["metric"] = preprocessed.metric_hint
            delta["aggregation"] = preprocessed.metric_hint
            delta["target_field"] = preprocessed.attribute_hint or ""
            delta["confidence"] = max(float(delta["confidence"] or 0.0), 0.86)
            delta["notes"].append(f"Metrica alterada para {preprocessed.metric_hint}.")

        if location:
            target = delta["replace_filters"] if state is not None and state.filters.get("location") else delta["add_filters"]
            target["location"] = location.title()
            if not delta["followup_type"]:
                delta["followup_type"] = "CHANGE_LOCATION"
            delta["confidence"] = max(float(delta["confidence"] or 0.0), 0.90)

        if status:
            target = delta["replace_filters"] if state is not None and state.filters.get("status") else delta["add_filters"]
            target["status"] = status
            if not delta["followup_type"]:
                delta["followup_type"] = "ADD_FILTER"
            delta["confidence"] = max(float(delta["confidence"] or 0.0), 0.88)

        if material:
            target = delta["replace_filters"] if state is not None and state.filters.get("material") else delta["add_filters"]
            target["material"] = material
            if not delta["followup_type"]:
                delta["followup_type"] = "ADD_FILTER"
            delta["confidence"] = max(float(delta["confidence"] or 0.0), 0.88)

        if service:
            target = delta["replace_filters"] if state is not None and state.filters.get("service") else delta["add_filters"]
            target["service"] = service
            if not delta["followup_type"]:
                delta["followup_type"] = "ADD_FILTER"
            delta["confidence"] = max(float(delta["confidence"] or 0.0), 0.88)

        if diameter:
            target = delta["replace_filters"] if state is not None and state.filters.get("diameter") else delta["add_filters"]
            target["diameter"] = diameter
            if not delta["followup_type"]:
                delta["followup_type"] = "ADD_FILTER"
            delta["confidence"] = max(float(delta["confidence"] or 0.0), 0.88)

        if not delta["reset_context"] and not delta["followup_type"]:
            if len((normalized or "").split()) <= 4:
                delta["followup_type"] = "ADD_FILTER"
                delta["confidence"] = 0.72

        if delta["followup_type"] == "CHANGE_GROUP":
            delta["notes"].append(f"Agrupamento alterado: {delta['group_by']}.")
        for key, value in delta["add_filters"].items():
            delta["notes"].append(f"Filtro adicionado: {key} = {value}.")
        for key, value in delta["replace_filters"].items():
            delta["notes"].append(f"Filtro atualizado: {key} = {value}.")
        return delta

    def _extract_diameter(self, normalized: str) -> str:
        match = re.search(r"\bdn\s+(\d{2,4})\b", normalized)
        if match:
            return match.group(1)
        match = re.search(r"\b(\d{2,4})\s*mm\b", normalized)
        if match:
            return match.group(1)
        return ""

    def _extract_status(self, normalized: str) -> str:
        for canonical, values in STATUS_VALUES.items():
            if any(re.search(rf"\b{re.escape(value)}\b", normalized) for value in values):
                return canonical
        return ""

    def _extract_material(self, normalized: str) -> str:
        for material in MATERIAL_VALUES:
            if re.search(rf"\b{re.escape(material)}\b", normalized):
                return material.upper()
        return ""

    def _extract_service(self, normalized: str) -> str:
        for service in SERVICE_TERMS:
            if re.search(rf"\b{re.escape(service)}\b", normalized):
                return service.title()
        return ""

    def _extract_entity(self, normalized: str) -> str:
        for entity in ENTITY_RESET_TERMS:
            if re.search(rf"\b{re.escape(entity)}\b", normalized):
                if entity.endswith("s"):
                    return entity[:-1]
                return entity
        return ""

    def _extract_location(self, normalized: str) -> str:
        for pattern in LOCATION_QUALIFIER_PATTERNS:
            match = re.search(pattern, normalized)
            if not match:
                continue
            candidate = self._clean_location(match.group(1))
            if candidate:
                return candidate

        for prefix in LOCATION_PREFIXES:
            match = re.search(rf"\b(?:em|de|do|da|no|na|sob|sobre)\s+(.+)$", normalized)
            if not match:
                continue
            candidate = self._clean_location(match.group(1))
            if candidate:
                return candidate
        return ""

    def _clean_location(self, value: str) -> str:
        cleaned = normalize_text(value)
        cleaned = re.sub(r"\b(agora|sobre|dessas|desses|destas|destes)\b", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        tokens = [token for token in cleaned.split() if token and token not in LOCATION_STOP_WORDS]
        if len(tokens) == 1 and tokens[0] in set(MATERIAL_VALUES) | set(SERVICE_TERMS):
            return ""
        return " ".join(tokens).strip()
