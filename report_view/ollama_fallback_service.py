from __future__ import annotations

import json
import os
import re
from time import perf_counter, time
from typing import Any, Dict, Optional, Sequence
from urllib.request import Request, urlopen

try:
    from qgis.PyQt.QtCore import QSettings
except Exception:  # pragma: no cover - smoke tests can run without QGIS
    QSettings = None

from .report_logging import log_info, log_warning
from .result_models import ChartSpec, FilterSpec, InterpretationResult, MetricSpec, ProjectSchema, QueryPlan
from .text_utils import normalize_text


DEFAULT_OLLAMA_URL = os.getenv("POWERBISUMMARIZER_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_OLLAMA_MODEL = os.getenv("POWERBISUMMARIZER_OLLAMA_MODEL", "mistral")
DEFAULT_OLLAMA_THRESHOLD = float(os.getenv("POWERBISUMMARIZER_OLLAMA_THRESHOLD", "0.65") or 0.65)
DEFAULT_OLLAMA_TIMEOUT_S = float(os.getenv("POWERBISUMMARIZER_OLLAMA_TIMEOUT_S", "1.6") or 1.6)

ENABLE_OLLAMA_KEY = "PowerBISummarizer/reports/enable_ollama"
OLLAMA_MODEL_KEY = "PowerBISummarizer/reports/ollama_model"
OLLAMA_THRESHOLD_KEY = "PowerBISummarizer/reports/ollama_threshold"

OLLAMA_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "aggregate_chart",
                "spatial_aggregate",
                "value_insight",
                "unsupported",
            ],
        },
        "rewritten_question": {"type": "string"},
        "target_layer": {"type": "string"},
        "source_layer": {"type": "string"},
        "boundary_layer": {"type": "string"},
        "group_by": {
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ]
        },
        "top_n": {"type": "integer"},
        "metric": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["count", "sum", "avg", "length", "area", "max", "min"],
                },
                "field": {"type": "string"},
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "value": {"type": "string"},
                    "operator": {"type": "string"},
                    "layer_role": {"type": "string"},
                    "kind": {"type": "string"},
                },
                "required": ["field", "value"],
                "additionalProperties": False,
            },
        },
        "chart": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "title": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "confidence": {"type": "number"},
        "needs_confirmation": {"type": "boolean"},
        "clarification_question": {"type": "string"},
    },
    "required": ["intent", "metric", "confidence", "needs_confirmation"],
    "additionalProperties": False,
}

OLLAMA_SYSTEM_PROMPT = """
Voce e um fallback local de interpretacao para um plugin QGIS.
Nao calcule nenhum resultado. Nao invente campos, camadas ou valores.
Use apenas nomes presentes no schema fornecido.
Se a pergunta for sobre total simples sem agrupamento, use intent="value_insight".
Se a pergunta for sobre agregacao por categoria, use intent="aggregate_chart".
Se a pergunta for sobre relacao espacial entre camadas, use intent="spatial_aggregate".
Se nao houver seguranca suficiente, use intent="unsupported" e needs_confirmation=true.
Sua resposta deve ser um JSON valido seguindo exatamente o schema pedido.
""".strip()


class _FallbackPlanHelper:
    def _resolve_layer_name(self, schema: ProjectSchema, layer_name, allowed_geometry: Optional[Sequence[str]] = None):
        if not layer_name:
            return None
        target = normalize_text(layer_name)
        candidates = []
        for layer in schema.layers:
            if allowed_geometry and layer.geometry_type not in allowed_geometry:
                continue
            layer_text = normalize_text(layer.name)
            if layer_text == target:
                return layer
            if target and (target in layer_text or layer_text in target):
                candidates.append(layer)
        return candidates[0] if candidates else None

    def _resolve_group_field(self, layer, group_value, current_name: str):
        tokens = []
        first_value = self._string_or_first(group_value)
        if first_value:
            tokens.append(first_value)
        if current_name:
            tokens.append(current_name)
        for token in tokens:
            match = self._resolve_field(layer, token)
            if match is not None:
                return match
        return None

    def _resolve_field(self, layer, field_name, allowed_kinds: Optional[Sequence[str]] = None):
        target = normalize_text(field_name)
        if not target:
            return None
        exact = None
        partial = None
        for field in layer.fields:
            if allowed_kinds and field.kind not in allowed_kinds:
                continue
            candidates = [normalize_text(field.name), normalize_text(field.alias or "")]
            if target in candidates:
                exact = field
                break
            if any(target and (target in candidate or candidate in target) for candidate in candidates if candidate):
                partial = partial or field
        return exact or partial

    def _resolve_metric(self, layer, raw_metric: Dict, current_metric: MetricSpec) -> Optional[MetricSpec]:
        operation = str(raw_metric.get("operation") or current_metric.operation or "count").lower()
        if operation not in {"count", "sum", "avg", "length", "area", "max", "min"}:
            return None

        metric = MetricSpec(
            operation=operation,
            field=None,
            field_label="",
            use_geometry=operation in {"length", "area"},
            label=self._metric_label(operation),
            source_geometry_hint=current_metric.source_geometry_hint,
        )
        if operation == "length":
            if layer.geometry_type != "line":
                return None
            metric.source_geometry_hint = "line"
            return metric
        if operation == "area":
            if layer.geometry_type != "polygon":
                return None
            metric.source_geometry_hint = "polygon"
            return metric
        if operation == "count":
            return metric

        allowed_kinds = {"integer", "numeric"}
        if operation in {"max", "min"}:
            allowed_kinds = {"integer", "numeric", "text"}
        metric_field = self._resolve_field(layer, raw_metric.get("field"), allowed_kinds=allowed_kinds)
        if metric_field is None:
            return None
        metric.field = metric_field.name
        metric.field_label = metric_field.label
        return metric

    def _resolve_spatial_metric(self, source_layer, raw_metric: Dict, current_metric: MetricSpec) -> Optional[MetricSpec]:
        operation = str(raw_metric.get("operation") or current_metric.operation or "count").lower()
        metric = MetricSpec(
            operation=operation,
            field=None,
            field_label="",
            use_geometry=operation in {"length", "area"},
            label=self._metric_label(operation),
            source_geometry_hint=current_metric.source_geometry_hint,
        )
        if operation == "count":
            return metric
        if operation == "length" and source_layer.geometry_type == "line":
            metric.source_geometry_hint = "line"
            return metric
        if operation == "area" and source_layer.geometry_type == "polygon":
            metric.source_geometry_hint = "polygon"
            return metric
        return None

    def _resolve_chart(self, raw_chart: Dict, plan: QueryPlan) -> ChartSpec:
        chart_type = normalize_text(raw_chart.get("type") or plan.chart.type or "auto")
        chart_type = {
            "pizza": "pie",
            "pie": "pie",
            "barra": "bar",
            "barras": "bar",
            "bar": "bar",
            "linha": "line",
            "line": "line",
            "auto": "auto",
        }.get(chart_type, "auto")
        default_title = plan.metric.label
        if plan.intent != "value_insight":
            default_title = f"{plan.metric.label} por {plan.group_label or plan.group_field}"
        title = str(raw_chart.get("title") or plan.chart.title or default_title)
        return ChartSpec(type=chart_type, title=title)

    def _resolve_filters(
        self,
        raw_filters,
        plan: QueryPlan,
        schema: ProjectSchema,
        schema_service=None,
        allow_feature_scan: bool = True,
    ):
        results = []
        if not isinstance(raw_filters, list):
            return results

        layer_map = self._plan_layer_map(plan, schema)
        for raw_filter in raw_filters:
            if not isinstance(raw_filter, dict):
                continue
            layer_role = str(raw_filter.get("layer_role") or "").lower().strip() or self._default_filter_role(plan)
            layer = layer_map.get(layer_role)
            if layer is None:
                continue
            field = self._resolve_field(layer, raw_filter.get("field"))
            if field is None:
                continue
            value = raw_filter.get("value")
            if value in (None, ""):
                continue
            operator = str(raw_filter.get("operator") or "eq").lower()
            resolved_value = str(value).strip()
            if schema_service is not None:
                validation = schema_service.validate_filter_value(
                    layer,
                    field.name,
                    resolved_value,
                    kind=self._guess_filter_kind(field, raw_filter),
                    allow_feature_scan=allow_feature_scan,
                )
                if validation is None:
                    continue
                resolved_value = str(validation.get("value") or resolved_value).strip()
            results.append(
                FilterSpec(
                    field=field.name,
                    value=resolved_value,
                    operator=operator if operator in {"eq", "neq", "contains", "is_null"} else "eq",
                    layer_role=layer_role,
                )
            )
        return results

    def _guess_filter_kind(self, field, raw_filter: Dict) -> str:
        explicit_kind = normalize_text(raw_filter.get("kind") or "")
        if explicit_kind:
            return explicit_kind
        search_text = normalize_text(" ".join([field.name, field.alias or ""]))
        if any(token in search_text for token in ("municipio", "cidade", "bairro", "localidade", "setor", "distrito")):
            return "location"
        if any(token in search_text for token in ("dn", "diam", "diametro")):
            return "diameter"
        if any(token in search_text for token in ("material", "classe", "tipo")):
            return "material"
        return "generic"

    def _plan_layer_map(self, plan: QueryPlan, schema: ProjectSchema):
        return {
            "target": schema.layer_by_id(plan.target_layer_id) if plan.target_layer_id else None,
            "source": schema.layer_by_id(plan.source_layer_id) if plan.source_layer_id else None,
            "boundary": schema.layer_by_id(plan.boundary_layer_id) if plan.boundary_layer_id else None,
        }

    def _default_filter_role(self, plan: QueryPlan) -> str:
        if plan.intent == "spatial_aggregate":
            return "boundary"
        return "target"

    def _coerce_top_n(self, value, current_value: Optional[int]) -> Optional[int]:
        try:
            if value is None:
                return current_value
            return max(1, int(value))
        except Exception:
            return current_value

    def _metric_label(self, operation: str) -> str:
        if operation == "count":
            return "Quantidade"
        if operation == "sum":
            return "Total"
        if operation == "avg":
            return "Media"
        if operation == "length":
            return "Extensao"
        if operation == "area":
            return "Area"
        if operation == "max":
            return "Maior valor"
        if operation == "min":
            return "Menor valor"
        return "Valor"

    def _string_or_first(self, value) -> str:
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str):
            return value
        return ""


class OllamaFallbackService:
    def __init__(
        self,
        settings=None,
        base_url: Optional[str] = None,
        timeout_s: Optional[float] = None,
    ):
        self.settings = settings or (QSettings() if QSettings is not None else None)
        self.base_url = (base_url or DEFAULT_OLLAMA_URL).rstrip("/")
        self.timeout_s = float(timeout_s or DEFAULT_OLLAMA_TIMEOUT_S)
        self._availability_cache: Optional[bool] = None
        self._availability_checked_at = 0.0
        self._availability_ttl_s = 45.0
        self._plan_parser = _FallbackPlanHelper()

    def clear_cache(self):
        self._availability_cache = None
        self._availability_checked_at = 0.0

    def load_config(self) -> Dict[str, Any]:
        enable_ollama = self._coerce_bool(
            self._settings_value(
                ENABLE_OLLAMA_KEY,
                os.getenv("POWERBISUMMARIZER_OLLAMA_ENABLED", "true"),
            ),
            default=True,
        )
        ollama_model = str(
            self._settings_value(
                OLLAMA_MODEL_KEY,
                os.getenv("POWERBISUMMARIZER_OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
            )
            or DEFAULT_OLLAMA_MODEL
        ).strip()
        ollama_threshold = self._coerce_float(
            self._settings_value(
                OLLAMA_THRESHOLD_KEY,
                os.getenv("POWERBISUMMARIZER_OLLAMA_THRESHOLD", str(DEFAULT_OLLAMA_THRESHOLD)),
            ),
            DEFAULT_OLLAMA_THRESHOLD,
        )
        return {
            "enable_ollama": enable_ollama,
            "ollama_model": ollama_model or DEFAULT_OLLAMA_MODEL,
            "ollama_threshold": min(max(float(ollama_threshold), 0.0), 1.0),
            "ollama_timeout_s": self.timeout_s,
            "ollama_url": self.base_url,
        }

    def is_available(self, force_refresh: bool = False) -> bool:
        config = self.load_config()
        if not config["enable_ollama"]:
            return False
        now = time()
        if (
            not force_refresh
            and self._availability_cache is not None
            and (now - self._availability_checked_at) <= self._availability_ttl_s
        ):
            return bool(self._availability_cache)

        available = False
        started_at = perf_counter()
        try:
            payload = self._http_get_json(f"{self.base_url}/api/tags")
            models = payload.get("models") or []
            available_names = [str(item.get("name") or "").strip() for item in models if isinstance(item, dict)]
            configured_model = str(config["ollama_model"] or "").strip().lower()
            if configured_model:
                available = any(self._model_matches(configured_model, item) for item in available_names)
            else:
                available = bool(available_names)
            if not available and available_names:
                log_warning(
                    "[Relatorios] ollama indisponivel para fallback "
                    f"model='{config['ollama_model']}' available={available_names[:6]}"
                )
        except Exception as exc:
            log_warning(f"[Relatorios] ollama indisponivel error={exc}")
            available = False

        self._availability_cache = bool(available)
        self._availability_checked_at = now
        log_info(
            "[Relatorios] ollama availability "
            f"available={bool(available)} duration_ms={((perf_counter() - started_at) * 1000):.1f}"
        )
        return bool(available)

    def should_use_fallback(self, confidence: float, query: str) -> bool:
        config = self.load_config()
        if not config["enable_ollama"]:
            return False
        text = str(query or "").strip()
        if len(text) < 4:
            return False
        return float(confidence or 0.0) < float(config["ollama_threshold"])

    def call_ollama(self, prompt: str) -> Optional[Dict[str, Any]]:
        config = self.load_config()
        if not self.is_available():
            return None

        body = {
            "model": config["ollama_model"],
            "prompt": prompt,
            "stream": False,
            "format": OLLAMA_RESPONSE_SCHEMA,
            "options": {
                "temperature": 0,
                "num_predict": 240,
            },
        }
        started_at = perf_counter()
        try:
            payload = self._http_post_json(f"{self.base_url}/api/generate", body)
            log_info(
                "[Relatorios] ollama fallback call "
                f"model='{config['ollama_model']}' duration_ms={((perf_counter() - started_at) * 1000):.1f}"
            )
            return payload
        except Exception as exc:
            log_warning(
                "[Relatorios] ollama fallback falhou "
                f"model='{config['ollama_model']}' error={exc}"
            )
            return None

    def parse_response(self, payload: Any) -> Dict[str, Any]:
        if payload is None:
            return {}
        if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
            return dict(payload.get("response") or {})
        if isinstance(payload, dict) and "response" in payload:
            return self._parse_json_like(payload.get("response"))
        if isinstance(payload, str):
            return self._parse_json_like(payload)
        if isinstance(payload, dict):
            return dict(payload)
        return {}

    def validate_response(
        self,
        response_payload: Dict[str, Any],
        schema: ProjectSchema,
        question: str = "",
        base_context_plan: Optional[QueryPlan] = None,
        schema_service=None,
        allow_feature_scan: bool = False,
    ) -> Optional[InterpretationResult]:
        if not isinstance(response_payload, dict):
            return None

        try:
            result = self._payload_to_result(
                payload=response_payload,
                question=question,
                schema=schema,
                base_context_plan=base_context_plan,
                schema_service=schema_service,
                allow_feature_scan=allow_feature_scan,
            )
        except Exception as exc:
            log_warning(f"[Relatorios] ollama payload invalido error={exc}")
            return None

        if result is None:
            return None
        if result.status not in {"ok", "confirm", "ambiguous"}:
            return None
        if result.plan is None and not result.candidate_interpretations:
            return None

        if result.plan is not None:
            trace = dict(result.plan.planning_trace or {})
            trace["ollama_fallback_used"] = True
            rewritten = str(response_payload.get("rewritten_question") or "").strip()
            if rewritten:
                result.plan.rewritten_question = rewritten
                trace["ollama_rewritten_question"] = rewritten
            trace["ollama_confidence"] = float(result.confidence or 0.0)
            result.plan.planning_trace = trace
        result.source = "ollama"
        return result

    def try_fallback(
        self,
        question: str,
        normalized_question: str,
        schema: ProjectSchema,
        current_interpretation: Optional[InterpretationResult] = None,
        context_payload: Optional[Dict[str, Any]] = None,
        base_context_plan: Optional[QueryPlan] = None,
        schema_service=None,
        allow_feature_scan: bool = False,
    ) -> Optional[InterpretationResult]:
        if not self.should_use_fallback(
            float(getattr(current_interpretation, "confidence", 0.0) or 0.0),
            question,
        ):
            return None
        raw_response = self.call_ollama(
            self._build_prompt(
                question=question,
                normalized_question=normalized_question,
                schema=schema,
                current_interpretation=current_interpretation,
                context_payload=context_payload or {},
            )
        )
        if raw_response is None:
            return None
        parsed = self.parse_response(raw_response)
        if not parsed:
            return None
        return self.validate_response(
            response_payload=parsed,
            schema=schema,
            question=question,
            base_context_plan=base_context_plan,
            schema_service=schema_service,
            allow_feature_scan=allow_feature_scan,
        )

    def _build_prompt(
        self,
        question: str,
        normalized_question: str,
        schema: ProjectSchema,
        current_interpretation: Optional[InterpretationResult],
        context_payload: Dict[str, Any],
    ) -> str:
        lines = [OLLAMA_SYSTEM_PROMPT, "", "Pergunta original:", question.strip(), ""]
        if normalized_question and normalized_question.strip() != question.strip():
            lines.extend(["Pergunta normalizada:", normalized_question.strip(), ""])
        if current_interpretation is not None:
            lines.extend(
                [
                    "Interpretacao atual com baixa confianca:",
                    json.dumps(current_interpretation.to_dict(), ensure_ascii=False),
                    "",
                ]
            )
        if context_payload:
            lines.extend(
                [
                    "Contexto curto:",
                    json.dumps(context_payload, ensure_ascii=False),
                    "",
                ]
            )
        lines.append("Schema resumido das camadas:")
        for layer in schema.layers:
            lines.append(
                f"- camada={layer.name} | geometria={layer.geometry_type} | feicoes={layer.feature_count}"
            )
            for field in layer.fields:
                flags = []
                if field.alias:
                    flags.append(f"alias={field.alias}")
                if field.is_location_candidate:
                    flags.append("location")
                elif field.is_filter_candidate:
                    flags.append("filter")
                sample_values = list(field.top_values or [])[:4] or list(field.sample_values or [])[:3]
                if sample_values:
                    flags.append("valores=" + ", ".join(str(value) for value in sample_values))
                suffix = f" | {' | '.join(flags)}" if flags else ""
                lines.append(f"  - campo={field.name} ({field.kind}){suffix}")
        return "\n".join(lines)

    def _payload_to_result(
        self,
        payload: Dict[str, Any],
        question: str,
        schema: ProjectSchema,
        base_context_plan: Optional[QueryPlan],
        schema_service,
        allow_feature_scan: bool,
    ) -> InterpretationResult:
        confidence = float(payload.get("confidence") or 0.0)
        clarification = str(payload.get("clarification_question") or "").strip()
        needs_confirmation = bool(payload.get("needs_confirmation"))
        intent = str(payload.get("intent") or "unsupported")

        plan = self._build_plan_from_payload(
            payload=payload,
            schema=schema,
            question=question,
            base_context_plan=base_context_plan,
            schema_service=schema_service,
            allow_feature_scan=allow_feature_scan,
        )
        if intent == "unsupported" and plan is None:
            return InterpretationResult(
                status="unsupported",
                message=clarification or "Nao encontrei uma interpretacao segura para essa pergunta.",
                confidence=confidence,
                source="ollama",
            )

        if plan is not None and needs_confirmation:
            return InterpretationResult(
                status="confirm",
                message=clarification or "Confirme a interpretacao antes de executar.",
                plan=plan,
                confidence=confidence,
                source="ollama",
                needs_confirmation=True,
                clarification_question=clarification,
            )

        if plan is not None and confidence >= 0.78 and not needs_confirmation:
            return InterpretationResult(
                status="ok",
                message="",
                plan=plan,
                confidence=confidence,
                source="ollama",
            )

        if plan is not None:
            return InterpretationResult(
                status="confirm",
                message=clarification or "Encontrei uma interpretacao possivel. Confirme antes de executar.",
                plan=plan,
                confidence=confidence,
                source="ollama",
                needs_confirmation=True,
                clarification_question=clarification,
            )

        return InterpretationResult(
            status="unsupported",
            message=clarification or "Nao encontrei uma interpretacao segura para essa pergunta.",
            confidence=confidence,
            source="ollama",
        )

    def _build_plan_from_payload(
        self,
        payload: Dict[str, Any],
        schema: ProjectSchema,
        question: str,
        base_context_plan: Optional[QueryPlan],
        schema_service,
        allow_feature_scan: bool,
    ) -> Optional[QueryPlan]:
        if not isinstance(payload, dict):
            return None

        intent = str(payload.get("intent") or "").strip().lower()
        if intent == "unsupported":
            return None

        parser = self._plan_parser
        if intent == "spatial_aggregate":
            source = parser._resolve_layer_name(schema, payload.get("source_layer"))
            boundary = parser._resolve_layer_name(schema, payload.get("boundary_layer"), allowed_geometry=("polygon",))
            if source is None or boundary is None:
                return None
            plan = QueryPlan(intent="spatial_aggregate", original_question=question)
            plan.source_layer_id = source.layer_id
            plan.source_layer_name = source.name
            plan.boundary_layer_id = boundary.layer_id
            plan.boundary_layer_name = boundary.name
            group_field = parser._resolve_group_field(boundary, payload.get("group_by"), plan.group_field)
            if not group_field:
                return None
            plan.group_field = group_field.name
            plan.group_label = parser._string_or_first(payload.get("group_by")) or group_field.label
            plan.group_field_kind = group_field.kind
            metric = parser._resolve_spatial_metric(source, payload.get("metric") or {}, plan.metric)
            if metric is None:
                return None
            plan.metric = metric
            plan.spatial_relation = "within" if source.geometry_type == "point" else "intersects"
        else:
            if intent == "context_refinement" and base_context_plan is not None:
                plan = base_context_plan
            else:
                resolved_intent = intent if intent in {"aggregate_chart", "value_insight"} else "value_insight"
                plan = QueryPlan(intent=resolved_intent, original_question=question)
            layer = parser._resolve_layer_name(schema, payload.get("target_layer"))
            if layer is None:
                return None
            plan.target_layer_id = layer.layer_id
            plan.target_layer_name = layer.name
            metric = parser._resolve_metric(layer, payload.get("metric") or {}, plan.metric)
            if metric is None:
                return None
            plan.metric = metric
            group_field = parser._resolve_group_field(layer, payload.get("group_by"), plan.group_field)
            if group_field is not None:
                plan.intent = "aggregate_chart"
                plan.group_field = group_field.name
                plan.group_label = parser._string_or_first(payload.get("group_by")) or group_field.label
                plan.group_field_kind = group_field.kind
            else:
                plan.intent = "value_insight"
                plan.group_field = ""
                plan.group_label = ""

        plan.top_n = parser._coerce_top_n(payload.get("top_n"), plan.top_n)
        plan.chart = parser._resolve_chart(payload.get("chart") or {}, plan)
        raw_filters = payload.get("filters") or []
        resolved_filters = parser._resolve_filters(
            raw_filters,
            plan,
            schema,
            schema_service,
            allow_feature_scan=allow_feature_scan,
        )
        if raw_filters and len(resolved_filters) < len(raw_filters):
            return None
        if resolved_filters or not plan.filters:
            plan.filters = resolved_filters
        return plan

    def _http_get_json(self, url: str) -> Dict[str, Any]:
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
        with urlopen(request, timeout=self.timeout_s) as response:
            payload = response.read().decode("utf-8", errors="replace")
        return json.loads(payload or "{}")

    def _http_post_json(self, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        request = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_s) as response:
            payload = response.read().decode("utf-8", errors="replace")
        return json.loads(payload or "{}")

    def _settings_value(self, key: str, default: Any) -> Any:
        if self.settings is None:
            return default
        try:
            return self.settings.value(key, default)
        except Exception:
            return default

    def _coerce_bool(self, value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "sim", "on"}:
            return True
        if text in {"0", "false", "no", "nao", "não", "off"}:
            return False
        return default

    def _coerce_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    def _parse_json_like(self, value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        text = str(value).strip()
        if not text:
            return {}
        for candidate in (text, self._extract_json_block(text)):
            if not candidate:
                continue
            try:
                payload = json.loads(candidate)
                if isinstance(payload, dict):
                    return payload
            except Exception:
                continue
        return {}

    def _extract_json_block(self, text: str) -> str:
        match = re.search(r"\{.*\}", text, flags=re.S)
        return match.group(0) if match else ""

    def _model_matches(self, configured_model: str, available_name: str) -> bool:
        current = str(available_name or "").strip().lower()
        if not current:
            return False
        if current == configured_model:
            return True
        if current.startswith(configured_model + ":"):
            return True
        return current.split(":", 1)[0] == configured_model.split(":", 1)[0]
