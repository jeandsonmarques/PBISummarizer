import re
from collections import Counter, defaultdict
from time import perf_counter
from typing import Dict, List, Optional, Sequence, Tuple

from qgis.PyQt.QtCore import QVariant
from qgis.core import QgsFeatureRequest, QgsProject, QgsVectorLayer, QgsWkbTypes

from .report_logging import log_info
from .result_models import FieldSchema, FilterSpec, LayerSchema, ProjectSchema
from .text_utils import contains_hint_tokens, normalize_compact, normalize_text, tokenize_text

LOCATION_FIELD_HINTS = (
    "municipio",
    "cidade",
    "bairro",
    "localidade",
    "distrito",
    "setor",
    "logradouro",
    "comunidade",
    "povoado",
)

FILTER_FIELD_HINTS = (
    "dn",
    "diametro",
    "diam",
    "bitola",
    "material",
    "classe",
    "tipo",
    "categoria",
    "municipio",
    "cidade",
    "bairro",
    "localidade",
    "setor",
    "status",
)

ENGINEERING_VALUE_HINTS = (
    "pvc",
    "pead",
    "fofo",
    "ferro",
    "aco",
    "dn",
    "mm",
)

GENERIC_NAME_FIELD_HINTS = (
    "nome",
    "name",
    "nm",
    "nm_nome",
    "descricao",
    "desc",
)

def _contains_hint_tokens(value: str, hints: Sequence[str]) -> bool:
    return contains_hint_tokens(value, hints)


class LayerSchemaService:
    def __init__(
        self,
        profile_feature_limit: int = 120,
        top_values_limit: int = 6,
        profile_field_limit: int = 6,
        feature_scan_limit: int = 60,
    ):
        self.profile_feature_limit = max(40, int(profile_feature_limit))
        self.top_values_limit = max(3, int(top_values_limit))
        self.profile_field_limit = max(3, int(profile_field_limit))
        self.feature_scan_limit = max(30, int(feature_scan_limit))
        self._cache: Dict[Tuple, ProjectSchema] = {}

    def clear_cache(self):
        self._cache = {}

    def read_project_schema(
        self,
        force_refresh: bool = False,
        include_profiles: bool = False,
        layer_ids: Optional[Sequence[str]] = None,
    ) -> ProjectSchema:
        started_at = perf_counter()
        structure_key = self._build_cache_key()
        selected_layer_ids = tuple(sorted(str(layer_id) for layer_id in (layer_ids or []) if layer_id))
        cache_key = (include_profiles, structure_key, selected_layer_ids)
        if not force_refresh and cache_key in self._cache:
            log_info(
                "[Relatorios] schema "
                f"level={'enriched' if include_profiles else 'light'} cache=hit "
                f"layers={len(self._cache[cache_key].layers)} duration_ms={((perf_counter() - started_at) * 1000):.1f}"
            )
            return self._cache[cache_key]

        layers: List[LayerSchema] = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not layer.isValid():
                continue
            should_profile = include_profiles and (not selected_layer_ids or layer.id() in selected_layer_ids)
            layers.append(self._build_layer_schema(layer, include_profiles=should_profile))
        layers.sort(key=lambda item: item.name.lower())
        schema = ProjectSchema(layers=layers)
        self._cache[cache_key] = schema
        profiled_layers = len([layer for layer in layers if any(getattr(field, "top_values", []) for field in layer.fields)])
        log_info(
            "[Relatorios] schema "
            f"level={'enriched' if include_profiles else 'light'} cache=miss "
            f"layers={len(layers)} profiled_layers={profiled_layers} duration_ms={((perf_counter() - started_at) * 1000):.1f}"
        )
        return schema

    def match_query_filters(
        self,
        layer_schema: LayerSchema,
        raw_candidates: Sequence[Dict],
        allow_feature_scan: bool = False,
    ) -> Tuple[List[FilterSpec], List[Dict]]:
        started_at = perf_counter()
        layer = self._get_layer(layer_schema.layer_id)
        if layer is None:
            return [], []

        filters: List[FilterSpec] = []
        recognized: List[Dict] = []
        seen = set()
        for candidate in raw_candidates:
            if not isinstance(candidate, dict):
                continue
            best_field = None
            best_match = None
            for field in self._candidate_fields_for_kind(layer_schema, candidate.get("kind")):
                match = self._match_candidate_on_field(
                    layer,
                    field,
                    candidate,
                    allow_feature_scan=allow_feature_scan,
                )
                if match is None:
                    continue
                key = (field.name, normalize_text(str(match["value"])), candidate.get("kind"))
                if key in seen:
                    continue
                if best_match is None or float(match.get("score", 0.0)) > float(best_match.get("score", 0.0)):
                    best_field = field
                    best_match = dict(match)
                    if float(best_match.get("score", 0.0)) >= 0.98:
                        break
            if best_field is None or best_match is None:
                continue
            key = (best_field.name, normalize_text(str(best_match["value"])), candidate.get("kind"))
            if key in seen:
                continue
            if candidate.get("kind") == "location":
                normalized_value = normalize_text(str(best_match["value"]))
                if any(
                    item.get("kind") == "location"
                    and normalize_text(str(item.get("value"))) == normalized_value
                    for item in recognized
                ):
                    continue
            seen.add(key)
            filters.append(
                FilterSpec(
                    field=best_field.name,
                    value=best_match["value"],
                    operator="eq",
                    layer_role="target",
                )
            )
            recognized.append(
                {
                    "kind": candidate.get("kind"),
                    "field": best_field.name,
                    "field_label": best_field.label,
                    "value": best_match["value"],
                    "score": best_match["score"],
                    "source_text": candidate.get("source_text"),
                    "match_mode": best_match.get("mode", "semantic"),
                }
            )
        log_info(
            "[Relatorios] filtros "
            f"layer={layer_schema.name} allow_feature_scan={allow_feature_scan} "
            f"candidates={list(raw_candidates)} recognized={recognized} duration_ms={((perf_counter() - started_at) * 1000):.1f}"
        )
        return filters, recognized

    def validate_filter_value(
        self,
        layer_schema: LayerSchema,
        field_name: str,
        candidate_value,
        kind: Optional[str] = None,
        allow_feature_scan: bool = True,
    ) -> Optional[Dict]:
        layer = self._get_layer(layer_schema.layer_id)
        if layer is None:
            return None

        field_schema = layer_schema.field_by_name(field_name)
        if field_schema is None:
            return None

        candidate = {
            "kind": kind or "generic",
            "text": str(candidate_value or "").strip(),
            "source_text": str(candidate_value or "").strip(),
            "numeric_value": self._coerce_numeric(candidate_value),
        }
        return self._match_candidate_on_field(
            layer,
            field_schema,
            candidate,
            allow_feature_scan=allow_feature_scan,
        )

    def choose_group_field_for_filters(self, layer_schema: LayerSchema, recognized_filters: Sequence[Dict]) -> Optional[str]:
        if not layer_schema.fields:
            return None
        location_fields = [field for field in layer_schema.fields if field.is_location_candidate]
        if recognized_filters:
            for item in recognized_filters:
                field_name = item.get("field")
                if field_name and any(field.name == field_name and field.is_location_candidate for field in layer_schema.fields):
                    return str(field_name)
        if location_fields:
            return location_fields[0].name
        text_fields = [field for field in layer_schema.fields if field.kind == "text"]
        if text_fields:
            return text_fields[0].name
        integer_fields = [field for field in layer_schema.fields if field.kind == "integer"]
        return integer_fields[0].name if integer_fields else None

    def find_semantic_fields(
        self,
        layer_schema: LayerSchema,
        semantic_kind: str,
        limit: int = 5,
    ) -> List[FieldSchema]:
        semantic_kind = normalize_text(semantic_kind)
        scored: List[Tuple[int, FieldSchema]] = []
        for field in layer_schema.fields:
            score = 0
            search_text = field.search_text
            if semantic_kind == "location":
                if getattr(field, "is_location_candidate", False):
                    score += 8
                elif layer_schema.geometry_type == "polygon" and field.kind == "text" and _contains_hint_tokens(field.search_text, GENERIC_NAME_FIELD_HINTS):
                    score += 5
                if field.kind == "text":
                    score += 2
            elif semantic_kind == "diameter":
                if _contains_hint_tokens(search_text, ("dn", "diametro", "diam", "bitola")):
                    score += 8
                if field.kind in {"integer", "numeric"}:
                    score += 3
                elif field.kind == "text":
                    score += 1
            elif semantic_kind == "material":
                if _contains_hint_tokens(search_text, ("material", "classe", "tipo")):
                    score += 8
                if field.kind == "text":
                    score += 3
            elif semantic_kind == "category":
                if _contains_hint_tokens(search_text, ("categoria", "tipo", "classe", "material", "grupo")):
                    score += 6
                if field.kind == "text":
                    score += 2

            if score > 0:
                scored.append((score, field))

        scored.sort(key=lambda item: (item[0], item[1].label.lower(), item[1].name.lower()), reverse=True)
        return [field for _score, field in scored[: max(1, int(limit))]]

    def _build_layer_schema(self, layer: QgsVectorLayer, include_profiles: bool = False) -> LayerSchema:
        fields: List[FieldSchema] = []
        geometry_type = self._geometry_type(layer)
        layer_name_norm = normalize_text(layer.name())
        profiles = self._collect_field_profiles(layer) if include_profiles else {}
        qgs_fields = layer.fields()
        for index, field in enumerate(qgs_fields):
            alias = layer.attributeAlias(index) or ""
            field_name_norm = normalize_text(" ".join([field.name(), alias]))
            field_kind = self._field_kind(field)
            sample_values = list(profiles.get(field.name(), {}).get("sample_values", []))
            top_values = list(profiles.get(field.name(), {}).get("top_values", []))
            field_schema = FieldSchema(
                name=field.name(),
                alias=alias,
                kind=field_kind,
                sample_values=sample_values,
            )
            setattr(field_schema, "top_values", top_values)
            setattr(
                field_schema,
                "is_filter_candidate",
                self._is_filter_candidate(field_name_norm, field_kind, layer_name_norm=layer_name_norm, geometry_type=geometry_type),
            )
            setattr(
                field_schema,
                "is_location_candidate",
                self._is_location_candidate(
                    field_name_norm,
                    field_kind=field_kind,
                    geometry_type=geometry_type,
                    layer_name_norm=layer_name_norm,
                ),
            )
            profile_tokens = []
            if getattr(field_schema, "is_filter_candidate", False) or getattr(field_schema, "is_location_candidate", False):
                profile_tokens = list(getattr(field_schema, "top_values", []) or [])[:3] + list(field_schema.sample_values or [])[:2]
            search_parts = [field_schema.name, field_schema.alias] + profile_tokens
            field_schema.search_text = normalize_text(" ".join(part for part in search_parts if part))
            fields.append(field_schema)

        search_terms = [layer.name(), self._geometry_type(layer)]
        for field in fields:
            search_terms.extend([field.name, field.alias])

        return LayerSchema(
            layer_id=layer.id(),
            name=layer.name(),
            geometry_type=geometry_type,
            feature_count=max(0, int(layer.featureCount())),
            fields=fields,
            search_text=normalize_text(" ".join(term for term in search_terms if term)),
        )

    def _collect_field_profiles(self, layer: QgsVectorLayer) -> Dict[str, Dict[str, List[str]]]:
        profiles: Dict[str, Dict[str, List[str]]] = {}
        candidate_fields = []
        geometry_type = self._geometry_type(layer)
        layer_name_norm = normalize_text(layer.name())
        for index, field in enumerate(layer.fields()):
            alias = layer.attributeAlias(index) or ""
            field_name_norm = normalize_text(" ".join([field.name(), alias]))
            field_kind = self._field_kind(field)
            is_location_candidate = self._is_location_candidate(
                field_name_norm,
                field_kind=field_kind,
                geometry_type=geometry_type,
                layer_name_norm=layer_name_norm,
            )
            if self._is_filter_candidate(
                field_name_norm,
                field_kind,
                layer_name_norm=layer_name_norm,
                geometry_type=geometry_type,
            ) or is_location_candidate:
                candidate_fields.append(
                    (
                        self._profile_field_priority(
                            field_name_norm,
                            field_kind=field_kind,
                            geometry_type=geometry_type,
                            layer_name_norm=layer_name_norm,
                        ),
                        field.name(),
                        field_kind,
                    )
                )

        if not candidate_fields:
            return profiles

        candidate_fields.sort(key=lambda item: (item[0], item[1]))
        candidate_fields = candidate_fields[: self.profile_field_limit]
        selected_fields = [(field_name, field_kind) for _priority, field_name, field_kind in candidate_fields]

        counters = {field_name: Counter() for field_name, _ in selected_fields}
        samples = defaultdict(list)
        request = QgsFeatureRequest().setLimit(self.profile_feature_limit)
        request.setSubsetOfAttributes([field_name for field_name, _ in selected_fields], layer.fields())
        if hasattr(request, "setNoGeometry"):
            request.setNoGeometry(True)
        for feature in layer.getFeatures(request):
            for field_name, field_kind in selected_fields:
                value = feature[field_name]
                if value in (None, ""):
                    continue
                rendered = self._render_profile_value(value, field_kind)
                if not rendered:
                    continue
                counters[field_name][rendered] += 1
                if rendered not in samples[field_name] and len(samples[field_name]) < self.top_values_limit:
                    samples[field_name].append(rendered)

        for field_name, _ in selected_fields:
            top_values = [value for value, _count in counters[field_name].most_common(self.top_values_limit)]
            profiles[field_name] = {
                "top_values": top_values,
                "sample_values": samples[field_name][: self.top_values_limit],
            }
        return profiles

    def _build_cache_key(self) -> Tuple:
        items = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not layer.isValid():
                continue
            fields = tuple(
                (
                    field.name(),
                    self._field_kind(field),
                    normalize_text(layer.attributeAlias(index) or ""),
                )
                for index, field in enumerate(layer.fields())
            )
            items.append(
                (
                    layer.id(),
                    layer.name(),
                    self._geometry_type(layer),
                    fields,
                )
            )
        items.sort(key=lambda item: (str(item[1]).lower(), item[0]))
        return tuple(items)

    def _candidate_fields_for_kind(self, layer_schema: LayerSchema, kind: str) -> List[FieldSchema]:
        kind = str(kind or "").lower()
        fields = [field for field in layer_schema.fields if getattr(field, "is_filter_candidate", False) or getattr(field, "is_location_candidate", False)]
        preferred = []
        if kind == "location":
            preferred = [field for field in fields if getattr(field, "is_location_candidate", False)]
            if layer_schema.geometry_type == "polygon":
                polygon_text_fields = [
                    field
                    for field in layer_schema.fields
                    if field.kind == "text"
                    and field not in preferred
                    and (_contains_hint_tokens(field.search_text, GENERIC_NAME_FIELD_HINTS) or not fields)
                ]
                preferred.extend(polygon_text_fields[:4])
        elif kind == "diameter":
            preferred = [field for field in fields if _contains_hint_tokens(field.search_text, ("dn", "diametro", "diam", "bitola"))]
        elif kind == "material":
            preferred = [field for field in fields if _contains_hint_tokens(field.search_text, ("material", "tipo", "classe"))]
        elif kind == "generic":
            preferred = [field for field in fields if not getattr(field, "is_location_candidate", False)]
        elif layer_schema.geometry_type == "polygon":
            preferred = [field for field in layer_schema.fields if field.kind == "text"][:4]
        if preferred:
            return preferred + [field for field in fields if field not in preferred]
        return fields

    def _match_candidate_on_field(
        self,
        layer: QgsVectorLayer,
        field_schema: FieldSchema,
        candidate: Dict,
        allow_feature_scan: bool = False,
    ) -> Optional[Dict]:
        if layer.fields().indexFromName(field_schema.name) < 0:
            return None

        target_text = normalize_text(candidate.get("text") or candidate.get("source_text") or "")
        compact_target = normalize_compact(candidate.get("text") or candidate.get("source_text") or "")
        numeric_target = candidate.get("numeric_value")

        profile_match = self._match_candidate_in_profile_values(
            field_schema,
            target_text,
            compact_target,
            numeric_target,
        )
        if profile_match is not None and profile_match["score"] >= 0.96:
            return profile_match
        if not allow_feature_scan:
            return profile_match or self._semantic_candidate_match(field_schema, candidate)

        request = QgsFeatureRequest()
        request.setSubsetOfAttributes([field_schema.name], layer.fields())
        request.setLimit(self.feature_scan_limit)
        if hasattr(request, "setNoGeometry"):
            request.setNoGeometry(True)
        best = None

        for feature in layer.getFeatures(request):
            value = feature[field_schema.name]
            if value in (None, ""):
                continue
            score = self._score_field_value_match(value, field_schema, target_text, compact_target, numeric_target)
            if score <= 0:
                continue
            rendered = self._render_profile_value(value, field_schema.kind)
            if not rendered:
                continue
            if best is None or score > best["score"]:
                best = {"value": rendered, "score": score}
                if score >= 0.98:
                    break
        return best or profile_match or self._semantic_candidate_match(field_schema, candidate)

    def _match_candidate_in_profile_values(
        self,
        field_schema: FieldSchema,
        target_text: str,
        compact_target: str,
        numeric_target: Optional[float],
    ) -> Optional[Dict]:
        best = None
        for value in list(field_schema.top_values or []) + list(field_schema.sample_values or []):
            score = self._score_field_value_match(
                value,
                field_schema,
                target_text,
                compact_target,
                numeric_target,
            )
            if score <= 0:
                continue
            rendered = self._render_profile_value(value, field_schema.kind)
            if not rendered:
                continue
            if best is None or score > best["score"]:
                best = {"value": rendered, "score": score}
        return best

    def _semantic_candidate_match(self, field_schema: FieldSchema, candidate: Dict) -> Optional[Dict]:
        kind = str(candidate.get("kind") or "").lower()
        candidate_text = str(candidate.get("text") or candidate.get("source_text") or "").strip()
        if not candidate_text:
            return None

        if kind == "location" and getattr(field_schema, "is_location_candidate", False):
            return {"value": self._render_candidate_value(candidate), "score": 0.72, "mode": "semantic"}
        if kind == "diameter" and _contains_hint_tokens(field_schema.search_text, ("dn", "diametro", "diam", "bitola")):
            return {"value": self._render_candidate_value(candidate), "score": 0.76, "mode": "semantic"}
        if kind == "material" and _contains_hint_tokens(field_schema.search_text, ("material", "tipo", "classe")):
            return {"value": self._render_candidate_value(candidate), "score": 0.70, "mode": "semantic"}
        if kind == "generic" and getattr(field_schema, "is_filter_candidate", False):
            return {"value": self._render_candidate_value(candidate), "score": 0.58, "mode": "semantic"}
        return None

    def _render_candidate_value(self, candidate: Dict) -> str:
        numeric_value = candidate.get("numeric_value")
        if numeric_value is not None:
            if abs(float(numeric_value) - round(float(numeric_value))) < 0.0001:
                return str(int(round(float(numeric_value))))
            return str(float(numeric_value))
        return str(candidate.get("text") or candidate.get("source_text") or "").strip()

    def _score_field_value_match(
        self,
        value,
        field_schema: FieldSchema,
        target_text: str,
        compact_target: str,
        numeric_target: Optional[float],
    ) -> float:
        value_text = normalize_text(value)
        compact_value = normalize_compact(value)
        if not value_text and not compact_value:
            return 0.0

        if numeric_target is not None:
            numeric_value = self._coerce_numeric(value)
            if numeric_value is not None and abs(numeric_value - float(numeric_target)) < 0.0001:
                return 0.99
            if compact_target and compact_target in compact_value:
                return 0.84

        if target_text and value_text == target_text:
            return 0.97
        if compact_target and compact_value == compact_target:
            return 0.95
        if target_text and (f" {target_text} " in f" {value_text} " or f" {value_text} " in f" {target_text} "):
            return 0.90
        if target_text and target_text in value_text:
            return 0.80
        if compact_target and compact_target in compact_value:
            return 0.78

        if getattr(field_schema, "is_location_candidate", False):
            target_tokens = set(target_text.split())
            value_tokens = set(value_text.split())
            if target_tokens and target_tokens.issubset(value_tokens):
                return 0.86

        if any(hint in target_text for hint in ENGINEERING_VALUE_HINTS) and compact_target and compact_target in compact_value:
            return 0.82
        return 0.0

    def _coerce_numeric(self, value) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            cleaned = re.sub(r"[^0-9\.,-]+", "", str(value))
            cleaned = cleaned.replace(",", ".")
            if cleaned.count(".") > 1:
                cleaned = cleaned.replace(".", "", cleaned.count(".") - 1)
            return float(cleaned)
        except Exception:
            return None

    def _render_profile_value(self, value, field_kind: str) -> str:
        if value in (None, ""):
            return ""
        if field_kind in {"integer", "numeric"}:
            numeric = self._coerce_numeric(value)
            if numeric is None:
                return ""
            if abs(numeric - round(numeric)) < 0.0001:
                return str(int(round(numeric)))
            return str(numeric)
        return str(value).strip()

    def _get_layer(self, layer_id: str) -> Optional[QgsVectorLayer]:
        layer = QgsProject.instance().mapLayer(layer_id)
        if isinstance(layer, QgsVectorLayer) and layer.isValid():
            return layer
        return None

    def _geometry_type(self, layer: QgsVectorLayer) -> str:
        geom_type = QgsWkbTypes.geometryType(layer.wkbType())
        if geom_type == QgsWkbTypes.PointGeometry:
            return "point"
        if geom_type == QgsWkbTypes.LineGeometry:
            return "line"
        if geom_type == QgsWkbTypes.PolygonGeometry:
            return "polygon"
        return "table"

    def _field_kind(self, field) -> str:
        variant_type = field.type()
        if variant_type in (QVariant.Int, QVariant.UInt, QVariant.LongLong, QVariant.ULongLong):
            return "integer"
        if variant_type in (QVariant.Double,):
            return "numeric"
        if variant_type == QVariant.Date:
            return "date"
        if variant_type == QVariant.DateTime:
            return "datetime"
        if variant_type == QVariant.Bool:
            return "boolean"
        if variant_type == QVariant.String:
            return "text"

        type_name = str(field.typeName() or "").lower()
        if any(token in type_name for token in ("char", "text", "string")):
            return "text"
        if any(token in type_name for token in ("int", "serial")):
            return "integer"
        if any(token in type_name for token in ("double", "float", "real", "numeric", "decimal")):
            return "numeric"
        if "date" in type_name and "time" in type_name:
            return "datetime"
        if "date" in type_name:
            return "date"
        return "other"

    def _is_filter_candidate(
        self,
        normalized_name: str,
        field_kind: str,
        layer_name_norm: str = "",
        geometry_type: str = "",
    ) -> bool:
        if field_kind not in {"text", "integer", "numeric", "date", "datetime"}:
            return False
        if _contains_hint_tokens(normalized_name, FILTER_FIELD_HINTS):
            return True
        return self._is_location_candidate(
            normalized_name,
            field_kind=field_kind,
            geometry_type=geometry_type,
            layer_name_norm=layer_name_norm,
        )

    def _is_location_candidate(
        self,
        normalized_name: str,
        field_kind: str = "other",
        geometry_type: str = "",
        layer_name_norm: str = "",
    ) -> bool:
        if field_kind not in {"text", "integer", "numeric"}:
            return False
        if _contains_hint_tokens(normalized_name, LOCATION_FIELD_HINTS):
            return True
        if geometry_type == "polygon" and field_kind == "text":
            if _contains_hint_tokens(normalized_name, GENERIC_NAME_FIELD_HINTS):
                return True
            if _contains_hint_tokens(layer_name_norm, LOCATION_FIELD_HINTS) and _contains_hint_tokens(normalized_name, ("nome", "name", "nm")):
                return True
        return False

    def _profile_field_priority(
        self,
        normalized_name: str,
        field_kind: str = "text",
        geometry_type: str = "",
        layer_name_norm: str = "",
    ) -> int:
        if self._is_location_candidate(
            normalized_name,
            field_kind=field_kind,
            geometry_type=geometry_type,
            layer_name_norm=layer_name_norm,
        ):
            return 0
        if _contains_hint_tokens(normalized_name, ("dn", "diametro", "diam", "bitola")):
            return 1
        if _contains_hint_tokens(normalized_name, ("material", "classe", "tipo", "categoria")):
            return 2
        if _contains_hint_tokens(normalized_name, ("status",)):
            return 3
        return 9
