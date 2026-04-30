import traceback
from dataclasses import dataclass, field
import inspect
from time import perf_counter
from typing import Any, Callable, Dict, List, Optional, Sequence

from .chart_factory import ChartFactory
from .context_merge_engine import ContextMergeEngine
from .conversation_memory_service import ConversationMemoryService
from .conversation_state import ConversationState
from .domain_packs import ProjectPack
from .dictionary_service import DictionaryService
from .followup_resolver import FollowupResolver
from .hybrid_query_interpreter import HybridQueryInterpreter
from .layer_schema_service import LayerSchemaService
from .ollama_fallback_service import OllamaFallbackService
from .operation_planner import OperationPlanner, PlanningBrief
from .report_context_memory import ReportContextMemory
from .report_executor import ReportExecutionJob, ReportExecutor
from .report_logging import log_error, log_info, log_warning
from .result_models import InterpretationResult, ProjectSchemaContext, QueryPlan, QueryResult
from .schema_context_builder import SchemaContextBuilder
from .schema_linker_service import SchemaLinkResult, SchemaLinkerService
from .text_utils import normalize_compact, normalize_text


@dataclass
class EngineInterpretationPayload:
    interpretation: InterpretationResult
    brief: PlanningBrief
    schema_context: ProjectSchemaContext
    schema_level: str = "light"


@dataclass
class ConversationContextPayload:
    normalized_question: str
    effective_question: str
    previous_state: Optional[ConversationState] = None
    is_followup: bool = False
    followup_type: str = ""
    delta: Dict[str, Any] = field(default_factory=dict)
    debug: List[str] = field(default_factory=list)


class ReportAIEngine:
    def __init__(
        self,
        schema_service: Optional[LayerSchemaService] = None,
        query_interpreter: Optional[HybridQueryInterpreter] = None,
        report_executor: Optional[ReportExecutor] = None,
        chart_factory: Optional[ChartFactory] = None,
        dictionary_service: Optional[DictionaryService] = None,
        schema_linker_service: Optional[SchemaLinkerService] = None,
        context_memory: Optional[ReportContextMemory] = None,
        query_memory_service=None,
        conversation_memory_service: Optional[ConversationMemoryService] = None,
        followup_resolver: Optional[FollowupResolver] = None,
        context_merge_engine: Optional[ContextMergeEngine] = None,
        ollama_fallback_service: Optional[OllamaFallbackService] = None,
        project_pack: Optional[ProjectPack] = None,
        session_id: str = "",
    ):
        self.project_pack = project_pack
        self.schema_service = schema_service or LayerSchemaService(project_pack=project_pack)
        self.query_interpreter = query_interpreter or HybridQueryInterpreter(project_pack=project_pack)
        self.report_executor = report_executor or ReportExecutor()
        self.chart_factory = chart_factory or ChartFactory()
        self.dictionary_service = dictionary_service or DictionaryService().loadDictionary()
        self.schema_linker_service = schema_linker_service or SchemaLinkerService(project_pack=project_pack)
        self.context_memory = context_memory or ReportContextMemory()
        self.query_memory_service = query_memory_service
        self.conversation_memory_service = conversation_memory_service
        self.followup_resolver = followup_resolver or FollowupResolver(project_pack=project_pack)
        self.context_merge_engine = context_merge_engine or ContextMergeEngine()
        self.ollama_fallback_service = ollama_fallback_service or OllamaFallbackService()
        self.session_id = session_id or ""
        self.interface_mode = "auto"
        self.schema_context_builder = SchemaContextBuilder()
        self.operation_planner = OperationPlanner(project_pack=project_pack)
        self._schema_context_cache: Dict[tuple, ProjectSchemaContext] = {}

    def refresh(self):
        self.schema_service.clear_cache()
        self.schema_linker_service.clear_cache()
        self._schema_context_cache = {}
        if self.ollama_fallback_service is not None:
            self.ollama_fallback_service.clear_cache()

    def set_interface_mode(self, mode: str):
        normalized = str(mode or "auto").strip().lower()
        if normalized not in {"auto", "local", "analytic", "ollama"}:
            normalized = "auto"
        self.interface_mode = normalized

    def interpret_question(
        self,
        question: str,
        overrides: Optional[Dict[str, str]] = None,
        memory_handle=None,
        layer_ids: Optional[Sequence[str]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> EngineInterpretationPayload:
        started_at = perf_counter()
        interface_mode = str(self.interface_mode or "auto").strip().lower()
        raw_question = self._strip_ui_context_suffix(question)
        runtime_layer_ids = tuple(str(layer_id) for layer_id in (layer_ids or []) if str(layer_id).strip())
        use_deep_validation = interface_mode == "analytic" or bool(runtime_layer_ids)
        initial_include_profiles = bool(runtime_layer_ids)
        log_info(
            "[Relatorios][debug][engine] "
            f"runtime_engine_file='{__file__}' engine_class_file='{inspect.getsourcefile(self.__class__) or ''}' "
            f"question='{raw_question}' interface_mode='{interface_mode}' scoped_layers={list(runtime_layer_ids)}"
        )
        normalized_question = raw_question
        if self.dictionary_service is not None and getattr(self.dictionary_service, "entry_count", 0):
            self._emit_status(status_callback, "Normalizando a pergunta...")
            normalized_question = self.dictionary_service.normalize_query(raw_question) or raw_question
            if normalized_question != raw_question:
                log_info(
                    "[Relatorios] dicionario "
                    f"original='{raw_question}' normalized='{normalized_question}'"
                )
        conversation_context = self._resolve_conversation_context(raw_question, normalized_question)
        effective_question = conversation_context.effective_question or normalized_question
        effective_question = self._strip_ui_context_suffix(effective_question)
        if conversation_context.is_followup:
            self._emit_status(status_callback, "Aproveitando o contexto anterior...")
        self._emit_status(status_callback, "Lendo as camadas abertas...")
        light_schema = self._load_schema(
            include_profiles=initial_include_profiles,
            layer_ids=runtime_layer_ids or None,
        )
        self._emit_status(status_callback, "Montando o contexto das camadas...")
        light_context = self._load_schema_context(
            light_schema,
            include_profiles=initial_include_profiles,
            layer_ids=runtime_layer_ids or None,
        )
        active_schema = light_schema
        active_context = light_context
        self._emit_status(status_callback, "Conectando a pergunta ao schema...")
        light_links = self._build_schema_links(
            effective_question,
            light_schema,
            light_context,
        )
        self._emit_status(status_callback, "Pensando na melhor interpretacao...")
        brief = self.operation_planner.build_brief(
            question=effective_question,
            schema_context=light_context,
            context_memory=self.context_memory,
            schema_link_result=light_links,
        )
        log_info(
            "[Relatorios] planner "
            f"question='{raw_question}' normalized='{normalized_question}' effective='{effective_question}' intent={brief.intent_label} metric={brief.metric_hint} "
            f"subject={brief.subject_hint} group={brief.group_hint} group_phrase='{brief.group_phrase}' excel={brief.excel_mode} filters={brief.extracted_filters} "
            f"layers={[item.layer_name for item in brief.likely_layers[:3]]} "
            f"linked_layers={[item.layer_name for item in brief.linked_layers[:3]]}"
        )
        interpretation = self._interpret_with_variants(
            question=effective_question,
            schema=light_schema,
            schema_context=light_context,
            brief=brief,
            schema_link_result=light_links,
            overrides=overrides,
            deep_validation=use_deep_validation,
            status_callback=status_callback,
        )
        schema_level = "scoped_deep" if initial_include_profiles else "light_deep" if use_deep_validation else "light"

        should_enrich = interface_mode != "local" and (
            interface_mode == "analytic" or self._should_retry_with_enriched_schema(interpretation)
        )
        if should_enrich:
            self._emit_status(status_callback, "Aprofundando a analise dos dados...")
            layer_ids = list(runtime_layer_ids) or self._candidate_layer_ids_from_interpretation(interpretation, brief)
            log_info(
                "[Relatorios] ai-engine retry=enriched "
                f"question='{raw_question}' candidate_layer_ids={layer_ids}"
            )
            enriched_schema = self._load_schema(
                include_profiles=True,
                layer_ids=layer_ids,
            )
            enriched_context = self._load_schema_context(
                enriched_schema,
                include_profiles=True,
                layer_ids=layer_ids,
            )
            enriched_links = self._build_schema_links(
                effective_question,
                enriched_schema,
                enriched_context,
            )
            enriched_brief = self.operation_planner.build_brief(
                question=effective_question,
                schema_context=enriched_context,
                context_memory=self.context_memory,
                schema_link_result=enriched_links,
            )
            enriched_interpretation = self._interpret_with_variants(
                question=effective_question,
                schema=enriched_schema,
                schema_context=enriched_context,
                brief=enriched_brief,
                schema_link_result=enriched_links,
                overrides=overrides,
                deep_validation=True,
                status_callback=status_callback,
            )
            interpretation = self._prefer_enriched_interpretation(
                base_result=interpretation,
                enriched_result=enriched_interpretation,
            )
            if interpretation is enriched_interpretation:
                brief = enriched_brief
                active_schema = enriched_schema
                active_context = enriched_context
                schema_level = "enriched"

        self._emit_status(status_callback, "Validando a melhor interpretacao...")
        interpretation = self._merge_followup_interpretation(conversation_context, interpretation)
        interpretation = self._rerank_interpretation(raw_question, interpretation)
        interpretation = self.operation_planner.refine_interpretation(
            interpretation,
            brief,
            active_context,
            context_memory=self.context_memory,
        )
        if interface_mode != "local":
            interpretation = self._maybe_apply_ollama_fallback(
                question=raw_question,
                normalized_question=normalized_question,
                effective_question=effective_question,
                interpretation=interpretation,
                schema=active_schema,
                schema_context=active_context,
                brief=brief,
                conversation_context=conversation_context,
                schema_level=schema_level,
                force=interface_mode == "ollama",
            )
        interpretation = self._enforce_explicit_location_guard(interpretation, brief, active_context)
        log_info(
            "[Relatorios][debug][engine] "
            f"pre_execution question='{raw_question}' final_status='{interpretation.status}' "
            f"needs_confirmation={bool(interpretation.needs_confirmation)} "
            f"has_plan={bool(interpretation.plan is not None)} "
            f"message='{interpretation.message or interpretation.clarification_question or ''}'"
        )
        if interpretation.plan is not None:
            interpretation.plan.original_question = raw_question
            trace = dict(interpretation.plan.planning_trace or {})
            trace["dictionary_normalized_question"] = normalized_question
            trace["planner_confidence"] = float(interpretation.confidence or 0.0)
            trace["conversation_effective_question"] = effective_question
            if conversation_context.is_followup:
                trace["conversation_previous_question"] = self._conversation_previous_question(conversation_context.previous_state)
                trace["conversation_merged_question"] = effective_question
                trace["conversation_followup_type"] = conversation_context.followup_type
                trace["conversation_delta"] = dict(conversation_context.delta or {})
                trace["conversation_debug"] = list(
                    trace.get("conversation_debug") or conversation_context.debug or []
                )
            interpretation.plan.planning_trace = trace
        self._safe_register_interpretation(memory_handle, interpretation)
        log_info(
            "[Relatorios] ai-engine "
            f"question='{raw_question}' schema_level={schema_level} status={interpretation.status} "
            f"confidence={float(interpretation.confidence or 0.0):.3f} duration_ms={((perf_counter() - started_at) * 1000):.1f}"
        )
        return EngineInterpretationPayload(
            interpretation=interpretation,
            brief=brief,
            schema_context=active_context,
            schema_level=schema_level,
        )

    def execute_plan(
        self,
        question: str,
        plan: QueryPlan,
        memory_handle=None,
    ) -> QueryResult:
        started_at = perf_counter()
        try:
            result = self.report_executor.execute(plan)
            if not result.ok:
                self._safe_mark_query_failure(
                    memory_handle,
                    error_message=f"execution: {result.message or 'resultado vazio'}",
                    plan=plan,
                    duration_ms=int((perf_counter() - started_at) * 1000),
                )
                self._safe_update_conversation_state(
                    question=question,
                    plan=plan,
                    result=result,
                    success=False,
                    error_message=result.message or "resultado vazio",
                )
                return result

            result.plan = result.plan or plan
            try:
                result.chart_payload = self.chart_factory.build_payload(result)
            except Exception as exc:
                result.chart_payload = None
                log_warning(
                    "[Relatorios] falha ao gerar grafico "
                    f"question='{question}' error={exc}\n{traceback.format_exc()}"
                )
                if result.summary.text:
                    result.summary.text = (
                        f"{result.summary.text} Nao foi possivel montar o grafico, mas a tabela foi gerada."
                    )
            self.context_memory.remember_result(question, plan, result)
            self._safe_mark_query_success(
                memory_handle,
                plan=plan,
                result=result,
                duration_ms=int((perf_counter() - started_at) * 1000),
            )
            self._safe_update_conversation_state(
                question=question,
                plan=plan,
                result=result,
                success=True,
            )
            return result
        except Exception as exc:
            detail = self._format_error_detail(exc)
            log_error(
                "[Relatorios] falha durante a execucao "
                f"question='{question}' plan={plan.to_dict()} error={exc}\n{traceback.format_exc()}"
            )
            self._safe_mark_query_failure(
                memory_handle,
                error_message=f"execution_error: {detail}",
                plan=plan,
                duration_ms=int((perf_counter() - started_at) * 1000),
            )
            self._safe_update_conversation_state(
                question=question,
                plan=plan,
                result=None,
                success=False,
                error_message=detail,
            )
            raise

    def create_execution_job(self, plan: QueryPlan) -> ReportExecutionJob:
        return self.report_executor.create_job(plan)

    def finalize_execution_job(
        self,
        question: str,
        job: ReportExecutionJob,
        memory_handle=None,
    ) -> QueryResult:
        result = job.result
        if not result.ok:
            self._safe_mark_query_failure(
                memory_handle,
                error_message=f"execution: {result.message or 'resultado vazio'}",
                plan=job.plan,
            )
            self._safe_update_conversation_state(
                question=question,
                plan=job.plan,
                result=result,
                success=False,
                error_message=result.message or "resultado vazio",
            )
            return result

        result.plan = result.plan or job.plan
        try:
            result.chart_payload = self.chart_factory.build_payload(result)
        except Exception as exc:
            result.chart_payload = None
            log_warning(
                "[Relatorios] falha ao gerar grafico "
                f"question='{question}' error={exc}\n{traceback.format_exc()}"
            )
            if result.summary.text:
                result.summary.text = (
                    f"{result.summary.text} Nao foi possivel montar o grafico, mas a tabela foi gerada."
                )
        self.context_memory.remember_result(question, job.plan, result)
        self._safe_mark_query_success(
            memory_handle,
            plan=job.plan,
            result=result,
        )
        self._safe_update_conversation_state(
            question=question,
            plan=job.plan,
            result=result,
            success=True,
        )
        return result

    def mark_execution_exception(
        self,
        plan: QueryPlan,
        memory_handle,
        detail: str,
    ):
        self._safe_mark_query_failure(
            memory_handle,
            error_message=f"execution_error: {detail}",
            plan=plan,
        )
        self._safe_update_conversation_state(
            question=plan.original_question or "",
            plan=plan,
            result=None,
            success=False,
            error_message=detail,
        )

    def _interpret_with_variants(
        self,
        question: str,
        schema,
        schema_context: ProjectSchemaContext,
        brief: PlanningBrief,
        schema_link_result: Optional[SchemaLinkResult],
        overrides: Optional[Dict[str, str]],
        deep_validation: bool,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> InterpretationResult:
        results = []
        for variant in self.operation_planner.candidate_questions(brief):
            try:
                if variant.strip() != question.strip():
                    self._emit_status(status_callback, "Comparando algumas leituras da pergunta...")
                else:
                    self._emit_status(status_callback, "Entendendo o pedido...")
                result = self.query_interpreter.interpret(
                    question=variant,
                    schema=schema,
                    overrides=dict(overrides or {}),
                    context_memory=self.context_memory,
                    schema_service=self.schema_service,
                    schema_link_result=schema_link_result,
                    deep_validation=deep_validation,
                )
                if result.plan is not None:
                    result.plan.original_question = question
                    normalized_variant = variant.strip() if variant.strip() != question.strip() else ""
                    if normalized_variant:
                        result.plan.rewritten_question = normalized_variant
                if variant.strip() != question.strip():
                    result.source = f"{result.source}+variant"
                results.append(result)
            except Exception as exc:
                log_warning(
                    "[Relatorios] ai-engine variante falhou "
                    f"question='{question}' variant='{variant}' error={exc}\n{traceback.format_exc()}"
                )
        return self.operation_planner.choose_best_interpretation(
            results,
            brief,
            schema_context,
            context_memory=self.context_memory,
        )

    def _emit_status(self, status_callback: Optional[Callable[[str], None]], message: str):
        if status_callback is None:
            return
        try:
            status_callback(message)
        except Exception:
            pass

    def _load_schema(self, include_profiles: bool = False, layer_ids: Optional[Sequence[str]] = None):
        try:
            return self.schema_service.read_project_schema(
                include_profiles=include_profiles,
                layer_ids=layer_ids,
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao carregar schema; usando fallback leve "
                f"error={exc}\n{traceback.format_exc()}"
            )
            return self.schema_service.read_project_schema(
                force_refresh=True,
                include_profiles=False,
                layer_ids=layer_ids,
            )

    def _load_schema_context(
        self,
        schema,
        include_profiles: bool = False,
        layer_ids: Optional[Sequence[str]] = None,
    ) -> ProjectSchemaContext:
        cache_key = (
            bool(include_profiles),
            tuple(sorted(str(layer_id) for layer_id in (layer_ids or []) if layer_id)),
            tuple(sorted(layer.layer_id for layer in schema.layers)),
        )
        if cache_key not in self._schema_context_cache:
            self._schema_context_cache[cache_key] = self.schema_context_builder.build(schema)
        return self._schema_context_cache[cache_key]

    def _should_retry_with_enriched_schema(self, interpretation: InterpretationResult) -> bool:
        if interpretation is None:
            return False
        if interpretation.status == "unsupported":
            return True
        if interpretation.status == "ambiguous" and interpretation.candidate_interpretations:
            return True
        if interpretation.status == "confirm" and float(interpretation.confidence or 0.0) < 0.82:
            return True
        return False

    def _build_schema_links(
        self,
        question: str,
        schema,
        schema_context: ProjectSchemaContext,
    ) -> Optional[SchemaLinkResult]:
        try:
            return self.schema_linker_service.link(question, schema, schema_context)
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao construir schema linker "
                f"question='{question}' error={exc}\n{traceback.format_exc()}"
            )
            return None

    def _candidate_layer_ids_from_interpretation(
        self,
        interpretation: InterpretationResult,
        brief: PlanningBrief,
    ) -> Optional[list]:
        layer_ids = list(self.operation_planner.candidate_layer_ids(brief))
        if interpretation is None:
            return layer_ids or None
        if interpretation.plan is not None:
            for layer_id in (
                interpretation.plan.target_layer_id,
                interpretation.plan.source_layer_id,
                interpretation.plan.boundary_layer_id,
            ):
                if layer_id and layer_id not in layer_ids:
                    layer_ids.append(layer_id)
        for candidate in getattr(interpretation, "candidate_interpretations", []) or []:
            plan = getattr(candidate, "plan", None)
            if plan is None:
                continue
            for layer_id in (plan.target_layer_id, plan.source_layer_id, plan.boundary_layer_id):
                if layer_id and layer_id not in layer_ids:
                    layer_ids.append(layer_id)
        for option in getattr(interpretation, "options", []) or []:
            for layer_id in (
                getattr(option, "target_layer_id", None),
                getattr(option, "source_layer_id", None),
                getattr(option, "boundary_layer_id", None),
            ):
                if layer_id and layer_id not in layer_ids:
                    layer_ids.append(layer_id)
        return layer_ids or None

    def _prefer_enriched_interpretation(self, base_result, enriched_result):
        valid = {"ok", "confirm", "ambiguous"}
        if enriched_result is None or enriched_result.status not in valid:
            return base_result
        if base_result is None or base_result.status not in valid:
            return enriched_result
        if enriched_result.status == "ok" and base_result.status != "ok":
            return enriched_result
        if float(enriched_result.confidence or 0.0) >= float(base_result.confidence or 0.0) + 0.04:
            return enriched_result
        if enriched_result.status == "ambiguous" and enriched_result.candidate_interpretations:
            return enriched_result
        return base_result

    def _rerank_interpretation(self, question: str, interpretation: InterpretationResult) -> InterpretationResult:
        if interpretation is None or self.query_memory_service is None:
            return interpretation
        try:
            return self.query_memory_service.rerank_interpretation(
                question=question,
                interpretation=interpretation,
                session_id=self.session_id,
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao reranquear interpretacao na memoria "
                f"question='{question}' error={exc}\n{traceback.format_exc()}"
            )
            return interpretation

    def _enforce_explicit_location_guard(
        self,
        interpretation: InterpretationResult,
        brief: PlanningBrief,
        schema_context: ProjectSchemaContext,
    ) -> InterpretationResult:
        explicit_locations = self._explicit_location_values(brief)
        log_info(
            "[Relatorios][debug][guard] "
            f"called=True explicit_locations={explicit_locations} "
            f"has_interpretation={bool(interpretation is not None)} "
            f"has_plan={bool(getattr(interpretation, 'plan', None) is not None)}"
        )
        if not explicit_locations or interpretation is None:
            log_info(
                "[Relatorios][debug][guard] "
                f"released=True reason='no_explicit_location_or_no_interpretation' explicit_locations={explicit_locations}"
            )
            return interpretation

        resolved_location = False
        if interpretation.plan is not None:
            resolved_location = self._plan_has_resolved_explicit_location(
                interpretation.plan,
                explicit_locations,
                schema_context,
            )
        log_info(
            "[Relatorios][debug][guard] "
            f"resolved_location={resolved_location} explicit_locations={explicit_locations} "
            f"plan_filters={[(item.field, item.value, item.layer_role) for item in (interpretation.plan.filters or [])] if interpretation.plan is not None else []}"
        )

        if interpretation.plan is not None and resolved_location:
            trace = dict(interpretation.plan.planning_trace or {})
            trace["explicit_location_guard"] = {
                "status": "applied",
                "locations": explicit_locations,
            }
            interpretation.plan.planning_trace = trace
            log_info("[Relatorios][debug][guard] released=True reason='explicit_location_resolved'")
            return interpretation

        location_text = ", ".join(value.title() for value in explicit_locations[:3])
        message = (
            f"Encontrei o filtro {location_text}, mas ainda nao consegui aplicar isso com seguranca. "
            "Confirme ou escolha uma coluna para evitar um resultado geral."
        )

        interpretation.status = "confirm" if interpretation.plan is not None else "unsupported"
        interpretation.needs_confirmation = interpretation.plan is not None
        interpretation.clarification_question = message if interpretation.plan is not None else ""
        interpretation.message = message
        interpretation.confidence = min(float(interpretation.confidence or 0.0), 0.74) if interpretation.plan is not None else float(interpretation.confidence or 0.0)
        if interpretation.plan is not None:
            trace = dict(interpretation.plan.planning_trace or {})
            trace["explicit_location_guard"] = {
                "status": "blocked",
                "locations": explicit_locations,
            }
            interpretation.plan.planning_trace = trace
        log_info(
            "[Relatorios][debug][guard] "
            f"released=False blocked=True final_status='{interpretation.status}' explicit_locations={explicit_locations}"
        )
        return interpretation

    def _explicit_location_values(self, brief: PlanningBrief) -> List[str]:
        values: List[str] = []
        linked_value_keys = {
            normalize_compact(getattr(item, "value", "") or "")
            for item in (getattr(brief, "linked_values", []) or [])
            if normalize_compact(getattr(item, "value", "") or "")
        }
        if not linked_value_keys:
            return values
        for item in brief.extracted_filters or []:
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
            if any(token in filter_field for token in ("municipio", "cidade", "bairro", "localidade", "setor", "distrito", "comunidade", "povoado")):
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

    def _strip_ui_context_suffix(self, question: str) -> str:
        text = str(question or "").strip()
        marker = "\n\nContexto adicional:"
        if marker in text:
            return text.split(marker, 1)[0].strip()
        normalized_marker = " contexto adicional "
        lowered = text.lower()
        marker_index = lowered.find(normalized_marker)
        if marker_index >= 0:
            return text[:marker_index].strip()
        return text

    def _resolve_conversation_context(self, question: str, normalized_question: str) -> ConversationContextPayload:
        if self.conversation_memory_service is None or not self.session_id:
            return ConversationContextPayload(
                normalized_question=normalized_question,
                effective_question=normalized_question,
            )
        previous_state = self.conversation_memory_service.get_state(self.session_id)
        is_followup = self.followup_resolver.is_followup(normalized_question, previous_state)
        if not is_followup:
            return ConversationContextPayload(
                normalized_question=normalized_question,
                effective_question=normalized_question,
                previous_state=previous_state,
            )
        delta = self.followup_resolver.extract_delta(normalized_question, previous_state)
        followup_type = delta.get("followup_type") or self.followup_resolver.classify_followup_type(
            normalized_question,
            previous_state,
        )
        delta["followup_type"] = followup_type
        effective_question = self.context_merge_engine.build_merged_question(
            previous_state,
            delta,
            normalized_question,
        )
        debug = list(delta.get("notes") or [])
        if followup_type and not delta.get("reset_context"):
            debug.insert(0, "Entendi como continuacao da consulta anterior")
        log_info(
            "[Relatorios] conversation "
            f"question='{question}' followup={bool(followup_type)} type={followup_type} merged='{effective_question}'"
        )
        return ConversationContextPayload(
            normalized_question=normalized_question,
            effective_question=effective_question or normalized_question,
            previous_state=previous_state,
            is_followup=bool(followup_type),
            followup_type=followup_type,
            delta=delta,
            debug=debug,
        )

    def _merge_followup_interpretation(
        self,
        conversation_context: ConversationContextPayload,
        interpretation: InterpretationResult,
    ) -> InterpretationResult:
        if not conversation_context.is_followup:
            return interpretation
        try:
            merged = self.context_merge_engine.merge(
                previous_state=conversation_context.previous_state,
                delta=conversation_context.delta,
                new_interpretation=interpretation,
            )
            if merged.plan is not None:
                trace = dict(merged.plan.planning_trace or {})
                debug = list(trace.get("conversation_debug") or [])
                for item in conversation_context.debug:
                    if item not in debug:
                        debug.append(item)
                trace["conversation_debug"] = debug[:5]
                trace["conversation_followup_type"] = conversation_context.followup_type
                trace["conversation_delta"] = dict(conversation_context.delta or {})
                trace["conversation_merged_question"] = conversation_context.effective_question
                merged.plan.planning_trace = trace
            return merged
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao mesclar contexto conversacional "
                f"error={exc}\n{traceback.format_exc()}"
            )
            return interpretation

    def _maybe_apply_ollama_fallback(
        self,
        question: str,
        normalized_question: str,
        effective_question: str,
        interpretation: InterpretationResult,
        schema,
        schema_context: ProjectSchemaContext,
        brief: PlanningBrief,
        conversation_context: ConversationContextPayload,
        schema_level: str,
        force: bool = False,
    ) -> InterpretationResult:
        if self.ollama_fallback_service is None:
            return interpretation
        current_confidence = float(getattr(interpretation, "confidence", 0.0) or 0.0)
        if not force and not self.ollama_fallback_service.should_use_fallback(current_confidence, effective_question):
            return interpretation

        fallback_schema = schema
        fallback_context = schema_context
        allow_feature_scan = bool(schema_level in {"enriched", "scoped_deep", "light_deep"})
        candidate_layer_ids = self._candidate_layer_ids_from_interpretation(interpretation, brief)
        if not allow_feature_scan and candidate_layer_ids:
            try:
                fallback_schema = self._load_schema(
                    include_profiles=True,
                    layer_ids=candidate_layer_ids,
                )
                fallback_context = self._load_schema_context(
                    fallback_schema,
                    include_profiles=True,
                    layer_ids=candidate_layer_ids,
                )
                allow_feature_scan = True
            except Exception as exc:
                log_warning(
                    "[Relatorios] falha ao enriquecer schema para ollama "
                    f"question='{question}' error={exc}\n{traceback.format_exc()}"
                )

        try:
            fallback_result = self.ollama_fallback_service.try_fallback(
                question=effective_question,
                normalized_question=normalized_question,
                schema=fallback_schema,
                current_interpretation=interpretation,
                context_payload={
                    "recent_context": self.context_memory.build_prompt_context(),
                    "followup": {
                        "is_followup": conversation_context.is_followup,
                        "type": conversation_context.followup_type,
                        "delta": dict(conversation_context.delta or {}),
                    },
                    "planner": {
                        "intent_label": brief.intent_label,
                        "metric_hint": brief.metric_hint,
                        "subject_hint": brief.subject_hint,
                        "group_hint": brief.group_hint,
                    },
                },
                base_context_plan=self.context_memory.last_plan(),
                schema_service=self.schema_service,
                allow_feature_scan=allow_feature_scan,
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao usar fallback do ollama "
                f"question='{question}' error={exc}\n{traceback.format_exc()}"
            )
            return interpretation

        if fallback_result is None:
            return interpretation

        fallback_result = self._merge_followup_interpretation(conversation_context, fallback_result)
        fallback_result = self._rerank_interpretation(question, fallback_result)
        fallback_result = self.operation_planner.refine_interpretation(
            fallback_result,
            brief,
            fallback_context,
            context_memory=self.context_memory,
        )
        preferred = self._prefer_ollama_interpretation(interpretation, fallback_result)
        if preferred is fallback_result:
            log_info(
                "[Relatorios] ollama fallback aceito "
                f"question='{question}' status={fallback_result.status} "
                f"confidence={float(fallback_result.confidence or 0.0):.3f}"
            )
        else:
            log_info(
                "[Relatorios] ollama fallback ignorado "
                f"question='{question}' current={interpretation.status}/{current_confidence:.3f} "
                f"fallback={fallback_result.status}/{float(fallback_result.confidence or 0.0):.3f}"
            )
        return preferred

    def _prefer_ollama_interpretation(
        self,
        current: InterpretationResult,
        fallback: InterpretationResult,
    ) -> InterpretationResult:
        valid_states = {"ok", "confirm", "ambiguous"}
        if fallback is None or fallback.status not in valid_states:
            return current
        if current is None or current.status not in valid_states:
            return fallback
        if fallback.status == "ok" and current.status != "ok":
            return fallback
        if current.status == "unsupported" and fallback.plan is not None:
            return fallback
        if current.plan is None and fallback.plan is not None:
            return fallback
        if float(fallback.confidence or 0.0) >= float(current.confidence or 0.0) + 0.08:
            return fallback
        if current.status == "ambiguous" and fallback.status in {"ok", "confirm"} and fallback.plan is not None:
            return fallback
        return current

    def _safe_update_conversation_state(
        self,
        question: str,
        plan: Optional[QueryPlan],
        result: Optional[QueryResult],
        success: bool,
        error_message: str = "",
    ):
        if self.conversation_memory_service is None or not self.session_id:
            return
        try:
            trace = dict((plan.planning_trace if plan is not None else {}) or {})
            self.conversation_memory_service.update_state(
                session_id=self.session_id,
                interpreted_query=plan,
                result=result,
                raw_query=question,
                normalized_query=trace.get("dictionary_normalized_question") or question,
                merged_query=trace.get("conversation_merged_question")
                or trace.get("conversation_effective_question")
                or trace.get("dictionary_normalized_question")
                or question,
                is_followup=bool(trace.get("conversation_followup_type")),
                followup_type=trace.get("conversation_followup_type") or "",
                delta=dict(trace.get("conversation_delta") or {}),
                debug=list(trace.get("conversation_debug") or []),
                success=bool(success),
                error_message=error_message or "",
                interpretation_status="ok" if success else "failed",
                confidence=float((trace.get("planner_confidence") or 0.0)),
                source=(trace.get("conversation_source") or ""),
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao atualizar estado conversacional "
                f"question='{question}' error={exc}\n{traceback.format_exc()}"
            )

    def record_interpretation_failure(
        self,
        question: str,
        detail: str,
        interpretation: Optional[InterpretationResult] = None,
    ):
        if self.conversation_memory_service is None or not self.session_id:
            return
        try:
            plan = interpretation.plan if interpretation is not None else None
            trace = dict((plan.planning_trace if plan is not None else {}) or {})
            self.conversation_memory_service.update_state(
                session_id=self.session_id,
                interpreted_query=plan,
                result=None,
                raw_query=question,
                normalized_query=trace.get("dictionary_normalized_question") or question,
                merged_query=trace.get("conversation_merged_question") or question,
                is_followup=bool(trace.get("conversation_followup_type")),
                followup_type=trace.get("conversation_followup_type") or "",
                delta=dict(trace.get("conversation_delta") or {}),
                debug=list(trace.get("conversation_debug") or []),
                success=False,
                error_message=detail,
                interpretation_status=interpretation.status if interpretation is not None else "failed",
                confidence=float(interpretation.confidence or 0.0) if interpretation is not None else 0.0,
                source=(interpretation.source if interpretation is not None else ""),
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao registrar erro conversacional "
                f"question='{question}' error={exc}\n{traceback.format_exc()}"
            )

    def _conversation_previous_question(self, previous_state: Optional[ConversationState]) -> str:
        if previous_state is None:
            return ""
        last_turn = previous_state.last_turn()
        if last_turn is None:
            return ""
        return last_turn.raw_query or last_turn.normalized_query or ""

    def _safe_register_interpretation(self, memory_handle, interpretation):
        if memory_handle is None or interpretation is None or self.query_memory_service is None:
            return
        try:
            self.query_memory_service.register_interpretation(
                handle=memory_handle,
                interpretation=interpretation,
                source_context_json=self.context_memory.build_prompt_context(),
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao salvar interpretacao na memoria "
                f"query_id={getattr(memory_handle, 'history_id', None)} error={exc}\n{traceback.format_exc()}"
            )

    def _safe_mark_query_success(self, memory_handle, plan: QueryPlan, result: QueryResult, duration_ms: Optional[int] = None):
        if memory_handle is None or self.query_memory_service is None:
            return
        try:
            self.query_memory_service.mark_query_success(
                handle=memory_handle,
                plan=plan,
                result=result,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao marcar sucesso na memoria "
                f"query_id={getattr(memory_handle, 'history_id', None)} error={exc}\n{traceback.format_exc()}"
            )

    def _safe_mark_query_failure(
        self,
        memory_handle,
        error_message: str,
        duration_ms: Optional[int] = None,
        plan: Optional[QueryPlan] = None,
        execution_payload_json: Optional[Dict] = None,
    ):
        if memory_handle is None or self.query_memory_service is None:
            return
        try:
            self.query_memory_service.mark_query_failure(
                handle=memory_handle,
                error_message=error_message,
                duration_ms=duration_ms,
                plan=plan,
                execution_payload_json=execution_payload_json,
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao marcar erro na memoria "
                f"query_id={getattr(memory_handle, 'history_id', None)} error={exc}\n{traceback.format_exc()}"
            )

    def _format_error_detail(self, exc: Exception) -> str:
        text = str(exc).strip() or exc.__class__.__name__
        if len(text) > 220:
            return text[:217] + "..."
        return text
