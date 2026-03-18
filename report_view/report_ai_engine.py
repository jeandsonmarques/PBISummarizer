import traceback
from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Dict, Optional, Sequence

from .chart_factory import ChartFactory
from .dictionary_service import DictionaryService
from .hybrid_query_interpreter import HybridQueryInterpreter
from .layer_schema_service import LayerSchemaService
from .operation_planner import OperationPlanner, PlanningBrief
from .report_context_memory import ReportContextMemory
from .report_executor import ReportExecutionJob, ReportExecutor
from .report_logging import log_error, log_info, log_warning
from .result_models import InterpretationResult, ProjectSchemaContext, QueryPlan, QueryResult
from .schema_context_builder import SchemaContextBuilder


@dataclass
class EngineInterpretationPayload:
    interpretation: InterpretationResult
    brief: PlanningBrief
    schema_context: ProjectSchemaContext
    schema_level: str = "light"


class ReportAIEngine:
    def __init__(
        self,
        schema_service: Optional[LayerSchemaService] = None,
        query_interpreter: Optional[HybridQueryInterpreter] = None,
        report_executor: Optional[ReportExecutor] = None,
        chart_factory: Optional[ChartFactory] = None,
        dictionary_service: Optional[DictionaryService] = None,
        context_memory: Optional[ReportContextMemory] = None,
        query_memory_service=None,
        session_id: str = "",
    ):
        self.schema_service = schema_service or LayerSchemaService()
        self.query_interpreter = query_interpreter or HybridQueryInterpreter()
        self.report_executor = report_executor or ReportExecutor()
        self.chart_factory = chart_factory or ChartFactory()
        self.dictionary_service = dictionary_service or DictionaryService().loadDictionary()
        self.context_memory = context_memory or ReportContextMemory()
        self.query_memory_service = query_memory_service
        self.session_id = session_id or ""
        self.schema_context_builder = SchemaContextBuilder()
        self.operation_planner = OperationPlanner()
        self._schema_context_cache: Dict[tuple, ProjectSchemaContext] = {}

    def refresh(self):
        self.schema_service.clear_cache()
        self._schema_context_cache = {}

    def interpret_question(
        self,
        question: str,
        overrides: Optional[Dict[str, str]] = None,
        memory_handle=None,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> EngineInterpretationPayload:
        started_at = perf_counter()
        normalized_question = question
        if self.dictionary_service is not None:
            self._emit_status(status_callback, "Normalizando termos tecnicos...")
            normalized_question = self.dictionary_service.normalize_query(question) or question
            if normalized_question != question:
                log_info(
                    "[Relatorios] dicionario "
                    f"original='{question}' normalized='{normalized_question}'"
                )
        self._emit_status(status_callback, "Lendo as camadas abertas...")
        light_schema = self._load_schema(include_profiles=False)
        self._emit_status(status_callback, "Montando o contexto das camadas...")
        light_context = self._load_schema_context(light_schema, include_profiles=False)
        self._emit_status(status_callback, "Pensando na melhor interpretacao...")
        brief = self.operation_planner.build_brief(
            question=normalized_question,
            schema_context=light_context,
            context_memory=self.context_memory,
        )
        log_info(
            "[Relatorios] planner "
            f"question='{question}' normalized='{normalized_question}' intent={brief.intent_label} metric={brief.metric_hint} "
            f"subject={brief.subject_hint} group={brief.group_hint} filters={brief.extracted_filters} "
            f"layers={[item.layer_name for item in brief.likely_layers[:3]]}"
        )
        interpretation = self._interpret_with_variants(
            question=normalized_question,
            schema=light_schema,
            schema_context=light_context,
            brief=brief,
            overrides=overrides,
            deep_validation=False,
            status_callback=status_callback,
        )
        schema_level = "light"

        if self._should_retry_with_enriched_schema(interpretation):
            self._emit_status(status_callback, "Aprofundando a analise dos dados...")
            layer_ids = self._candidate_layer_ids_from_interpretation(interpretation, brief)
            log_info(
                "[Relatorios] ai-engine retry=enriched "
                f"question='{question}' candidate_layer_ids={layer_ids}"
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
            enriched_brief = self.operation_planner.build_brief(
                question=normalized_question,
                schema_context=enriched_context,
                context_memory=self.context_memory,
            )
            enriched_interpretation = self._interpret_with_variants(
                question=normalized_question,
                schema=enriched_schema,
                schema_context=enriched_context,
                brief=enriched_brief,
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
                light_context = enriched_context
                schema_level = "enriched"

        self._emit_status(status_callback, "Validando a melhor interpretacao...")
        interpretation = self._rerank_interpretation(question, interpretation)
        interpretation = self.operation_planner.refine_interpretation(
            interpretation,
            brief,
            light_context,
            context_memory=self.context_memory,
        )
        if interpretation.plan is not None:
            interpretation.plan.original_question = question
            trace = dict(interpretation.plan.planning_trace or {})
            trace["dictionary_normalized_question"] = normalized_question
            interpretation.plan.planning_trace = trace
        self._safe_register_interpretation(memory_handle, interpretation)
        log_info(
            "[Relatorios] ai-engine "
            f"question='{question}' schema_level={schema_level} status={interpretation.status} "
            f"confidence={float(interpretation.confidence or 0.0):.3f} duration_ms={((perf_counter() - started_at) * 1000):.1f}"
        )
        return EngineInterpretationPayload(
            interpretation=interpretation,
            brief=brief,
            schema_context=light_context,
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

    def _interpret_with_variants(
        self,
        question: str,
        schema,
        schema_context: ProjectSchemaContext,
        brief: PlanningBrief,
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
