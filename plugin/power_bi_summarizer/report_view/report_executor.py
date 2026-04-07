import copy
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from qgis.core import (
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsFeature,
    QgsFeatureRequest,
    QgsProject,
    QgsSpatialIndex,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .report_logging import log_info
from .result_models import CompositeOperandSpec, FilterSpec, MetricSpec, QueryPlan, QueryResult, ResultRow, SummaryPayload
from .text_utils import normalize_compact, normalize_text


class ReportExecutionJob:
    def __init__(self, executor: "ReportExecutor", plan: QueryPlan):
        self.executor = executor
        self.plan = plan
        self.processed = 0
        self.total_estimate = 0
        self.phase_label = "processando"
        self._done = False
        self._result = QueryResult(ok=False, message="A execução ainda não terminou.")

    @property
    def done(self) -> bool:
        return self._done

    @property
    def result(self) -> QueryResult:
        return self._result

    def step(self, batch_size: int = 400) -> bool:
        if self._done:
            return True
        self._step_impl(max(1, int(batch_size)))
        return self._done

    def progress_text(self) -> str:
        if self.total_estimate > 0:
            return f"{self.phase_label.capitalize()}... {self.processed}/{self.total_estimate} registros"
        if self.processed > 0:
            return f"{self.phase_label.capitalize()}... {self.processed} registros"
        return f"{self.phase_label.capitalize()}..."

    def _complete(self, result: QueryResult):
        self._done = True
        self._result = result

    def _step_impl(self, batch_size: int):
        raise NotImplementedError


class _ValueInsightJob(ReportExecutionJob):
    def __init__(self, executor: "ReportExecutor", plan: QueryPlan):
        super().__init__(executor, plan)
        self.phase_label = "analisando dados"
        self.layer = self.executor._get_layer(plan.target_layer_id)
        if self.layer is None or not self.layer.isValid():
            self._complete(QueryResult(ok=False, message="Não encontrei a camada escolhida para esse relatório."))
            return
        if plan.metric.operation in {"min", "max", "sum", "avg"}:
            if not plan.metric.field or plan.metric.field not in self.layer.fields().names():
                self._complete(QueryResult(ok=False, message="O campo consultado não existe mais nessa camada."))
                return

        boundary_context, error_message = self.executor._prepare_boundary_filter_context(plan, target_layer=self.layer)
        if error_message:
            self._complete(QueryResult(ok=False, message=error_message))
            return

        self.boundary_context = boundary_context
        self.distance_area = self.executor._distance_area(self.layer)
        self.field_names = self.layer.fields().names()
        self.iterator = iter(self.layer.getFeatures())
        self.total_estimate = max(0, int(self.layer.featureCount()))
        self.values: List[float] = []
        self.total_value = 0.0
        self.contributing_count = 0
        self.filtered_records = 0
        self.target_matches = 0
        self.boundary_filtered_out = 0

    def _step_impl(self, batch_size: int):
        if self.done:
            return
        for _ in range(batch_size):
            try:
                feature = next(self.iterator)
            except StopIteration:
                self._finish()
                return

            self.processed += 1
            if not self.executor._feature_matches_filters(feature, self.plan.filters, self.field_names, "target"):
                continue
            self.target_matches += 1

            feature_geometry = feature.geometry()
            clipped_geometry = self.executor._clip_geometry_to_boundary(feature_geometry, self.boundary_context)
            if self.boundary_context is not None and clipped_geometry is None:
                self.boundary_filtered_out += 1
                continue

            self.filtered_records += 1
            if self.plan.metric.operation == "count":
                self.total_value += 1.0
                self.contributing_count += 1
                continue

            if self.plan.metric.use_geometry:
                if clipped_geometry is None or clipped_geometry.isEmpty():
                    continue
                if self.plan.metric.operation == "length":
                    numeric_value = self.executor._safe_float(self.distance_area.measureLength(clipped_geometry))
                else:
                    numeric_value = self.executor._safe_float(self.distance_area.measureArea(clipped_geometry))
                if numeric_value is None:
                    continue
                self.total_value += float(numeric_value)
                self.contributing_count += 1
                continue

            numeric_value = self.executor._coerce_numeric(feature[self.plan.metric.field]) if self.plan.metric.field else None
            if numeric_value is None:
                continue
            if self.plan.metric.operation in {"min", "max"}:
                self.values.append(float(numeric_value))
            else:
                self.total_value += float(numeric_value)
            self.contributing_count += 1

    def _finish(self):
        if self.plan.metric.operation in {"min", "max"}:
            if not self.values:
                fallback_result = self.executor._try_execution_fallback(self.plan, self.layer)
                if fallback_result is not None:
                    self._complete(fallback_result)
                    return
                self._complete(
                    self.executor._build_no_data_result(
                        self.plan,
                        layer_name=self.layer.name(),
                        target_matches=self.target_matches,
                        contributing_count=0,
                        boundary_filtered_out=self.boundary_filtered_out,
                        boundary_context=self.boundary_context,
                    )
                )
                return
            selected_value = min(self.values) if self.plan.metric.operation == "min" else max(self.values)
        elif self.plan.metric.operation == "avg":
            if self.contributing_count <= 0:
                fallback_result = self.executor._try_execution_fallback(self.plan, self.layer)
                if fallback_result is not None:
                    self._complete(fallback_result)
                    return
                self._complete(
                    self.executor._build_no_data_result(
                        self.plan,
                        layer_name=self.layer.name(),
                        target_matches=self.target_matches,
                        contributing_count=self.contributing_count,
                        boundary_filtered_out=self.boundary_filtered_out,
                        boundary_context=self.boundary_context,
                    )
                )
                return
            selected_value = self.total_value / max(1, self.contributing_count)
        else:
            if self.contributing_count <= 0:
                fallback_result = self.executor._try_execution_fallback(self.plan, self.layer)
                if fallback_result is not None:
                    self._complete(fallback_result)
                    return
                self._complete(
                    self.executor._build_no_data_result(
                        self.plan,
                        layer_name=self.layer.name(),
                        target_matches=self.target_matches,
                        contributing_count=self.contributing_count,
                        boundary_filtered_out=self.boundary_filtered_out,
                        boundary_context=self.boundary_context,
                    )
                )
                return
            selected_value = self.total_value

        self.executor._record_execution_trace(
            self.plan,
            status="ok",
            layer_name=self.layer.name(),
            target_matches=self.target_matches,
            contributing_count=self.contributing_count,
            boundary_filtered_out=self.boundary_filtered_out,
        )

        label = self.plan.metric.field_label or self.plan.metric.label or self.plan.metric.field or "Valor"
        self._complete(
            QueryResult(
                ok=True,
                summary=SummaryPayload(text=self.executor._build_value_insight_summary(self.plan, selected_value, self.filtered_records)),
                rows=[ResultRow(category=label, value=float(selected_value), raw_category=label)],
                value_label=self.executor._value_label(self.plan),
                show_percent=False,
                plan=self.plan,
                total_records=self.filtered_records,
                total_value=float(selected_value),
            )
        )


class _DirectAggregateJob(ReportExecutionJob):
    def __init__(self, executor: "ReportExecutor", plan: QueryPlan):
        super().__init__(executor, plan)
        self.phase_label = "analisando dados"
        self.layer = self.executor._get_layer(plan.target_layer_id)
        if self.layer is None or not self.layer.isValid():
            self._complete(QueryResult(ok=False, message="Não encontrei a camada escolhida para esse relatório."))
            return
        if plan.group_field not in self.layer.fields().names():
            self._complete(QueryResult(ok=False, message="O campo de agrupamento não existe mais nessa camada."))
            return
        if plan.metric.field and plan.metric.field not in self.layer.fields().names():
            self._complete(QueryResult(ok=False, message="O campo numérico usado na consulta não existe mais."))
            return

        boundary_context, error_message = self.executor._prepare_boundary_filter_context(plan, target_layer=self.layer)
        if error_message:
            self._complete(QueryResult(ok=False, message=error_message))
            return

        self.boundary_context = boundary_context
        self.totals = defaultdict(float)
        self.counts = defaultdict(int)
        self.filtered_records = 0
        self.target_matches = 0
        self.boundary_filtered_out = 0
        self.distance_area = self.executor._distance_area(self.layer)
        self.field_names = self.layer.fields().names()
        self.iterator = iter(self.layer.getFeatures())
        self.total_estimate = max(0, int(self.layer.featureCount()))

    def _step_impl(self, batch_size: int):
        if self.done:
            return
        for _ in range(batch_size):
            try:
                feature = next(self.iterator)
            except StopIteration:
                if not self.totals:
                    fallback_result = self.executor._try_execution_fallback(self.plan, self.layer)
                    if fallback_result is not None:
                        self._complete(fallback_result)
                        return
                    self._complete(
                        self.executor._build_no_data_result(
                            self.plan,
                            layer_name=self.layer.name(),
                            target_matches=self.target_matches,
                            contributing_count=self.filtered_records,
                            boundary_filtered_out=self.boundary_filtered_out,
                            boundary_context=self.boundary_context,
                        )
                    )
                    return
                self.executor._record_execution_trace(
                    self.plan,
                    status="ok",
                    layer_name=self.layer.name(),
                    target_matches=self.target_matches,
                    contributing_count=self.filtered_records,
                    boundary_filtered_out=self.boundary_filtered_out,
                )
                self._complete(self.executor._build_result(self.plan, self.totals, self.counts, self.filtered_records))
                return

            self.processed += 1
            if not self.executor._feature_matches_filters(feature, self.plan.filters, self.field_names, "target"):
                continue
            self.target_matches += 1
            feature_geometry = feature.geometry()
            clipped_geometry = self.executor._clip_geometry_to_boundary(feature_geometry, self.boundary_context)
            if self.boundary_context is not None and clipped_geometry is None:
                self.boundary_filtered_out += 1
                continue

            category_value = self.executor._render_category(feature[self.plan.group_field])
            if not category_value:
                continue

            if self.plan.metric.operation == "count":
                value = 1.0
            elif self.plan.metric.use_geometry:
                if clipped_geometry is None or clipped_geometry.isEmpty():
                    continue
                if self.plan.metric.operation == "length":
                    value = self.executor._safe_float(self.distance_area.measureLength(clipped_geometry))
                else:
                    value = self.executor._safe_float(self.distance_area.measureArea(clipped_geometry))
                if value is None:
                    continue
            else:
                value = self.executor._safe_float(feature[self.plan.metric.field]) if self.plan.metric.field else None
                if value is None:
                    continue

            self.totals[category_value] += float(value)
            self.counts[category_value] += 1
            self.filtered_records += 1


class _SpatialAggregateJob(ReportExecutionJob):
    def __init__(self, executor: "ReportExecutor", plan: QueryPlan):
        super().__init__(executor, plan)
        self.phase_label = "preparando limites"
        self.source_layer = self.executor._get_layer(plan.source_layer_id)
        self.boundary_layer = self.executor._get_layer(plan.boundary_layer_id)
        if self.source_layer is None or not self.source_layer.isValid():
            self._complete(QueryResult(ok=False, message="Não encontrei a camada de origem dessa consulta."))
            return
        if self.boundary_layer is None or not self.boundary_layer.isValid():
            self._complete(QueryResult(ok=False, message="Não encontrei a camada de limites dessa consulta."))
            return
        if plan.group_field not in self.boundary_layer.fields().names():
            self._complete(QueryResult(ok=False, message="O campo de agrupamento não existe mais na camada de limites."))
            return

        self.request = QgsFeatureRequest()
        if self.boundary_layer.fields().indexFromName(plan.group_field) >= 0:
            self.request.setSubsetOfAttributes([plan.group_field], self.boundary_layer.fields())

        self.boundary_features: Dict[int, object] = {}
        self.spatial_index = QgsSpatialIndex()
        self.transform = None
        if self.source_layer.crs() != self.boundary_layer.crs():
            try:
                self.transform = QgsCoordinateTransform(
                    self.boundary_layer.crs(),
                    self.source_layer.crs(),
                    QgsProject.instance(),
                )
            except Exception:
                self.transform = None

        self.boundary_iterator = iter(self.boundary_layer.getFeatures(self.request))
        self.source_iterator = None
        self.boundary_total = max(0, int(self.boundary_layer.featureCount()))
        self.source_total = max(0, int(self.source_layer.featureCount()))
        self.total_estimate = self.boundary_total + self.source_total
        self.totals = defaultdict(float)
        self.counts = defaultdict(int)
        self.filtered_records = 0
        self.distance_area = self.executor._distance_area(self.source_layer)

    def _step_impl(self, batch_size: int):
        if self.done:
            return
        if self.source_iterator is None:
            self._step_boundaries(max(10, batch_size // 4))
            return
        self._step_sources(batch_size)

    def _step_boundaries(self, batch_size: int):
        self.phase_label = "preparando limites"
        for _ in range(batch_size):
            try:
                feature = next(self.boundary_iterator)
            except StopIteration:
                if not self.boundary_features:
                    self._complete(QueryResult(ok=False, message="A camada de limites não possui geometrias válidas."))
                    return
                self.source_iterator = iter(self.source_layer.getFeatures())
                self.phase_label = "analisando dados"
                return

            self.processed += 1
            if not self.executor._feature_matches_filters(feature, self.plan.filters, self.boundary_layer.fields().names(), "boundary"):
                continue
            geometry = feature.geometry()
            if geometry is None or geometry.isEmpty():
                continue
            if self.transform is not None:
                try:
                    geometry.transform(self.transform)
                except Exception:
                    continue

            self.boundary_features[feature.id()] = (geometry, feature[self.plan.group_field])
            index_feature = QgsFeature()
            index_feature.setId(feature.id())
            index_feature.setGeometry(geometry)
            self.spatial_index.addFeature(index_feature)

    def _step_sources(self, batch_size: int):
        self.phase_label = "analisando dados"
        for _ in range(batch_size):
            try:
                source_feature = next(self.source_iterator)
            except StopIteration:
                self._complete(self.executor._build_result(self.plan, self.totals, self.counts, self.filtered_records))
                return

            self.processed += 1
            if not self.executor._feature_matches_filters(source_feature, self.plan.filters, self.source_layer.fields().names(), "source"):
                continue
            source_geometry = source_feature.geometry()
            if source_geometry is None or source_geometry.isEmpty():
                continue

            candidate_ids = self.spatial_index.intersects(source_geometry.boundingBox())
            matched = False
            for boundary_id in candidate_ids:
                boundary_feature = self.boundary_features.get(boundary_id)
                if boundary_feature is None:
                    continue
                boundary_geometry, boundary_value = boundary_feature
                if boundary_geometry is None or boundary_geometry.isEmpty():
                    continue

                if self.plan.spatial_relation == "within":
                    is_match = source_geometry.within(boundary_geometry) or source_geometry.intersects(boundary_geometry)
                else:
                    is_match = source_geometry.intersects(boundary_geometry)
                if not is_match:
                    continue

                category_value = self.executor._render_category(boundary_value)
                if not category_value:
                    continue

                if self.plan.metric.operation == "count":
                    value = 1.0
                else:
                    intersection = source_geometry.intersection(boundary_geometry)
                    if intersection is None or intersection.isEmpty():
                        continue
                    if self.plan.metric.operation == "length":
                        value = self.executor._safe_float(self.distance_area.measureLength(intersection))
                    else:
                        value = self.executor._safe_float(self.distance_area.measureArea(intersection))
                    if value is None:
                        continue

                self.totals[category_value] += float(value)
                self.counts[category_value] += 1
                matched = True

            if matched:
                self.filtered_records += 1


class _DerivedRatioJob(ReportExecutionJob):
    def __init__(self, executor: "ReportExecutor", plan: QueryPlan):
        super().__init__(executor, plan)
        self.target_layer = self.executor._get_layer(plan.target_layer_id)
        self.source_layer = self.executor._get_layer(plan.source_layer_id)
        self.phase_label = "analisando rede"
        if self.target_layer is None or not self.target_layer.isValid():
            self._complete(QueryResult(ok=False, message="Não encontrei a camada de rede usada nesse cálculo."))
            return
        if self.source_layer is None or not self.source_layer.isValid():
            self._complete(QueryResult(ok=False, message="Não encontrei a camada de ligações usada nesse cálculo."))
            return

        self.target_boundary_context, error_message = self.executor._prepare_boundary_filter_context(
            plan,
            target_layer=self.target_layer,
        )
        if error_message:
            self._complete(QueryResult(ok=False, message=error_message))
            return

        self.source_boundary_context, error_message = self.executor._prepare_boundary_filter_context(
            plan,
            target_layer=self.source_layer,
        )
        if error_message:
            self._complete(QueryResult(ok=False, message=error_message))
            return

        self.target_distance_area = self.executor._distance_area(self.target_layer)
        self.target_field_names = self.target_layer.fields().names()
        self.source_field_names = self.source_layer.fields().names()
        self.target_iterator = iter(self.target_layer.getFeatures())
        self.source_iterator = None
        self.target_total = max(0, int(self.target_layer.featureCount()))
        self.source_total = max(0, int(self.source_layer.featureCount()))
        self.total_estimate = self.target_total + self.source_total
        self.numerator_total = 0.0
        self.denominator_total = 0
        self.target_processed = 0
        self.source_processed = 0

    def _step_impl(self, batch_size: int):
        if self.done:
            return
        if self.source_iterator is None:
            self._step_target(batch_size)
            return
        self._step_source(batch_size)

    def _step_target(self, batch_size: int):
        self.phase_label = "analisando rede"
        for _ in range(batch_size):
            try:
                feature = next(self.target_iterator)
            except StopIteration:
                self.source_iterator = iter(self.source_layer.getFeatures())
                self.phase_label = "analisando ligacoes"
                return

            self.processed += 1
            if not self.executor._feature_matches_filters(feature, self.plan.filters, self.target_field_names, "target"):
                continue
            clipped_geometry = self.executor._clip_geometry_to_boundary(feature.geometry(), self.target_boundary_context)
            if self.target_boundary_context is not None and clipped_geometry is None:
                continue
            if clipped_geometry is None or clipped_geometry.isEmpty():
                continue
            numeric_value = self.executor._safe_float(self.target_distance_area.measureLength(clipped_geometry))
            if numeric_value is None:
                continue
            self.numerator_total += float(numeric_value)
            self.target_processed += 1

    def _step_source(self, batch_size: int):
        self.phase_label = "analisando ligacoes"
        for _ in range(batch_size):
            try:
                feature = next(self.source_iterator)
            except StopIteration:
                self._finish()
                return

            self.processed += 1
            if not self.executor._feature_matches_filters(feature, self.plan.filters, self.source_field_names, "source"):
                continue
            clipped_geometry = self.executor._clip_geometry_to_boundary(feature.geometry(), self.source_boundary_context)
            if self.source_boundary_context is not None and clipped_geometry is None:
                continue
            self.denominator_total += 1
            self.source_processed += 1

    def _finish(self):
        if self.numerator_total <= 0 or self.denominator_total <= 0:
            self._complete(QueryResult(ok=False, message="Não encontrei dados suficientes para calcular metros por ligação."))
            return
        ratio_value = float(self.numerator_total) / max(1, int(self.denominator_total))
        self._complete(
            QueryResult(
                ok=True,
                summary=SummaryPayload(
                    text=self.executor._build_ratio_summary(
                        self.plan,
                        ratio_value,
                        self.numerator_total,
                        self.denominator_total,
                    )
                ),
                rows=[ResultRow(category="Metros por ligação", value=float(ratio_value), raw_category="Metros por ligação")],
                value_label=self.executor._value_label(self.plan),
                show_percent=False,
                plan=self.plan,
                total_records=self.source_processed,
                total_value=float(ratio_value),
            )
        )


class _CompositeMetricJob(ReportExecutionJob):
    def __init__(self, executor: "ReportExecutor", plan: QueryPlan):
        super().__init__(executor, plan)
        self.phase_label = "analisando dados"
        self.operation = (getattr(plan.composite, "operation", "") or plan.metric.operation or "").lower()
        self.operands = list(getattr(plan.composite, "operands", []) or [])
        self.operand_jobs: List[_ValueInsightJob] = []
        self.operand_results: List[QueryResult] = []
        self.current_index = 0
        self.total_estimate = 0

        if len(self.operands) < 2:
            self._complete(QueryResult(ok=False, message="Não encontrei operandos suficientes para essa operação."))
            return

        for operand in self.operands:
            operand_plan = self.executor._build_operand_plan(self.plan, operand)
            job = _ValueInsightJob(self.executor, operand_plan)
            if job.done and not job.result.ok:
                self._complete(job.result)
                return
            self.operand_jobs.append(job)
            self.total_estimate += max(0, int(job.total_estimate or 0))
        if self.total_estimate <= 0:
            self.total_estimate = len(self.operand_jobs)

    def _step_impl(self, batch_size: int):
        if self.done:
            return
        if self.current_index >= len(self.operand_jobs):
            self._finish()
            return

        current_job = self.operand_jobs[self.current_index]
        current_operand = self.operands[self.current_index]
        self.phase_label = f"analisando {normalize_text(current_operand.label or 'operando')}".strip()
        done = current_job.step(batch_size=batch_size)
        self.processed = sum(item.processed for item in self.operand_jobs)
        if not done:
            return
        if not current_job.result.ok:
            self._complete(current_job.result)
            return
        self.operand_results.append(current_job.result)
        self.current_index += 1
        if self.current_index >= len(self.operand_jobs):
            self._finish()

    def _finish(self):
        result = self.executor._finalize_composite_results(self.plan, self.operands, self.operand_results)
        self._complete(result)


class ReportExecutor:
    def execute(self, plan: QueryPlan) -> QueryResult:
        if plan.intent == "value_insight":
            return self._execute_value_insight(plan)
        if plan.intent == "composite_metric":
            return self._execute_composite_metric(plan)
        if plan.intent == "derived_ratio":
            return self._execute_derived_ratio(plan)
        if plan.intent == "aggregate_chart":
            return self._execute_direct(plan)
        if plan.intent == "spatial_aggregate":
            return self._execute_spatial(plan)
        return QueryResult(ok=False, message="Não foi possível montar um plano de consulta válido.")

    def select_plan_features(self, plan: QueryPlan) -> Tuple[bool, str]:
        layer, layer_role = self._selection_layer_for_plan(plan)
        if layer is None or not layer.isValid():
            return False, "Não encontrei a camada usada nesse resultado."

        boundary_context = None
        if layer_role == "target":
            boundary_context, error_message = self._prepare_boundary_filter_context(plan, target_layer=layer)
            if error_message:
                return False, error_message

        matching_ids: List[int] = []
        field_names = layer.fields().names()
        for feature in layer.getFeatures():
            if not self._feature_matches_filters(feature, plan.filters, field_names, layer_role):
                continue
            if boundary_context is not None:
                clipped_geometry = self._clip_geometry_to_boundary(feature.geometry(), boundary_context)
                if clipped_geometry is None:
                    continue
            matching_ids.append(feature.id())

        for current_layer in QgsProject.instance().mapLayers().values():
            if isinstance(current_layer, QgsVectorLayer) and current_layer.isValid():
                current_layer.removeSelection()

        if not matching_ids:
            return False, "Nenhuma feição filtrada foi encontrada para selecionar no mapa."

        layer.selectByIds(matching_ids)
        return True, f"{len(matching_ids)} feições selecionadas em {layer.name()}."

    def _selection_layer_for_plan(self, plan: QueryPlan) -> Tuple[Optional[QgsVectorLayer], str]:
        if plan.intent == "spatial_aggregate":
            return self._get_layer(plan.source_layer_id), "source"
        if plan.intent in {"aggregate_chart", "value_insight"}:
            return self._get_layer(plan.target_layer_id), "target"
        return self._get_layer(plan.target_layer_id), "target"

    def create_job(self, plan: QueryPlan) -> ReportExecutionJob:
        if plan.intent == "value_insight":
            return _ValueInsightJob(self, plan)
        if plan.intent == "composite_metric":
            return _CompositeMetricJob(self, plan)
        if plan.intent == "derived_ratio":
            return _DerivedRatioJob(self, plan)
        if plan.intent == "aggregate_chart":
            return _DirectAggregateJob(self, plan)
        if plan.intent == "spatial_aggregate":
            return _SpatialAggregateJob(self, plan)
        job = ReportExecutionJob(self, plan)
        job._complete(QueryResult(ok=False, message="Não foi possível montar um plano de consulta válido."))
        return job

    def _record_execution_trace(self, plan: QueryPlan, **payload) -> None:
        trace = dict(plan.planning_trace or {})
        execution_trace = dict(trace.get("execution") or {})
        execution_trace.update(payload)
        trace["execution"] = execution_trace
        extra_debug = list(payload.get("conversation_debug") or [])
        if extra_debug:
            conversation_debug = list(trace.get("conversation_debug") or [])
            conversation_debug.extend(str(item).strip() for item in extra_debug if str(item or "").strip())
            trace["conversation_debug"] = conversation_debug[:10]
        plan.planning_trace = trace

    def _location_like_field(self, field_name: str) -> bool:
        normalized = normalize_text(field_name)
        return any(
            token in normalized
            for token in ("municipio", "cidade", "bairro", "localidade", "setor", "distrito", "logradouro", "nome", "nm")
        )

    def _describe_filters(self, filters, layer_role: Optional[str] = None) -> str:
        parts = []
        for filter_spec in list(filters or []):
            if not isinstance(filter_spec, FilterSpec):
                continue
            if layer_role is not None and filter_spec.layer_role not in {"any", layer_role}:
                continue
            field_label = filter_spec.field or "campo"
            value_label = filter_spec.value if filter_spec.value not in (None, "") else "<vazio>"
            parts.append(f"{field_label}={value_label}")
        return ", ".join(parts)

    def _build_no_data_result(
        self,
        plan: QueryPlan,
        *,
        layer_name: str,
        target_matches: int,
        contributing_count: int,
        boundary_filtered_out: int = 0,
        boundary_context: Optional[Dict] = None,
    ) -> QueryResult:
        self._record_execution_trace(
            plan,
            status="no_data",
            layer_name=layer_name,
            target_matches=int(target_matches),
            contributing_count=int(contributing_count),
            boundary_filtered_out=int(boundary_filtered_out),
            boundary_context=boundary_context or {},
        )
        message = self._build_no_data_message(
            plan,
            layer_name=layer_name,
            target_matches=target_matches,
            contributing_count=contributing_count,
            boundary_filtered_out=boundary_filtered_out,
            boundary_context=boundary_context,
        )
        log_info(
            "[Relatórios] execução sem dados "
            f"layer={layer_name} target_matches={target_matches} contributing_count={contributing_count} "
            f"boundary_filtered_out={boundary_filtered_out} message='{message}'"
        )
        return QueryResult(ok=False, message=message, plan=plan)

    def _build_no_data_message(
        self,
        plan: QueryPlan,
        *,
        layer_name: str,
        target_matches: int,
        contributing_count: int,
        boundary_filtered_out: int = 0,
        boundary_context: Optional[Dict] = None,
    ) -> str:
        trace = dict(plan.planning_trace or {})
        chosen_metric_field = str(trace.get("chosen_metric_field") or plan.metric.field or "")
        diameter_field = str(trace.get("chosen_diameter_field") or "")
        location_field = str(trace.get("chosen_location_field") or "")
        geo_mode = str(trace.get("geo_filter_mode") or "none")
        requested_kinds = {str(item).lower() for item in list(trace.get("requested_filter_kinds") or [])}
        target_filters_text = self._describe_filters(plan.filters, layer_role="target")
        boundary_filters_text = self._describe_filters(plan.filters, layer_role="boundary")

        if "diameter" in requested_kinds and not diameter_field:
            return f"Encontrei a camada {layer_name}, mas não consegui localizar um campo de diâmetro compatível."
        if "location" in requested_kinds and not location_field and not plan.boundary_layer_id:
            return f"Encontrei a camada {layer_name}, mas não consegui localizar um campo geográfico compatível nessa camada."
        if plan.metric.use_geometry and target_matches > 0 and contributing_count <= 0:
            metric_name = "comprimento" if plan.metric.operation == "length" else "area"
            return f"A camada {layer_name} foi encontrada, mas não possui geometria válida para calcular {metric_name} com os filtros aplicados."
        if boundary_context is not None and target_matches > 0 and contributing_count <= 0:
            boundary_name = str((boundary_context or {}).get("layer_name") or plan.boundary_layer_name or "limite geográfico")
            if boundary_filtered_out > 0:
                return f"Encontrei o valor geográfico em {boundary_name}, mas a interseção não retornou feições na camada {layer_name}."
        if target_matches <= 0 and target_filters_text:
            if geo_mode == "textual":
                return f"Encontrei a camada {layer_name}, mas os filtros textuais aplicados ({target_filters_text}) não retornaram feições compatíveis."
            return f"Encontrei a camada {layer_name}, mas os filtros aplicados ({target_filters_text}) não retornaram feições compatíveis."
        if plan.boundary_layer_id and boundary_filters_text and boundary_context is None:
            return f"Encontrei a camada {layer_name}, mas não consegui localizar o limite geográfico usando {boundary_filters_text}."
        if not plan.metric.use_geometry and plan.metric.field and target_matches > 0 and contributing_count <= 0:
            return (
                f"Encontrei a camada {layer_name}, mas o campo {plan.metric.field_label or plan.metric.field} "
                "não possui valores válidos para essa operação."
            )
        if plan.metric.use_geometry and "length" == plan.metric.operation and not chosen_metric_field:
            return f"Encontrei a camada {layer_name}, mas não encontrei uma geometria de linha válida para somar comprimento."
        return "Não encontrei dados compatíveis com essa pergunta."

    def _build_boundary_fallback_plan(self, plan: QueryPlan, target_layer: QgsVectorLayer) -> Optional[QueryPlan]:
        trace = dict(plan.planning_trace or {})
        if plan.boundary_layer_id or trace.get("execution_fallback_attempted"):
            return None

        location_filters = [
            filter_spec
            for filter_spec in list(plan.filters or [])
            if isinstance(filter_spec, FilterSpec)
            and filter_spec.layer_role == "target"
            and (self._location_like_field(filter_spec.field) or normalize_text(filter_spec.field) == normalize_text(trace.get("chosen_location_field") or ""))
        ]
        if not location_filters:
            return None

        location_filter = location_filters[0]
        boundary_match = self._find_boundary_layer_match(target_layer, location_filter.value)
        if boundary_match is None:
            return None

        boundary_layer, boundary_field, boundary_value = boundary_match
        fallback_plan = copy.deepcopy(plan)
        fallback_plan.boundary_layer_id = boundary_layer.id()
        fallback_plan.boundary_layer_name = boundary_layer.name()
        fallback_plan.filters = [
            item
            for item in list(fallback_plan.filters or [])
            if not (
                isinstance(item, FilterSpec)
                and item.layer_role == "target"
                and normalize_text(item.value) == normalize_text(location_filter.value)
                and self._location_like_field(item.field)
            )
        ]
        fallback_plan.filters.append(
            FilterSpec(
                field=boundary_field,
                value=boundary_value,
                operator="eq",
                layer_role="boundary",
            )
        )
        fallback_trace = dict(fallback_plan.planning_trace or {})
        fallback_trace["execution_fallback_attempted"] = True
        fallback_trace["execution_fallback"] = {
            "mode": "spatial_boundary",
            "boundary_layer": boundary_layer.name(),
            "boundary_field": boundary_field,
            "boundary_value": boundary_value,
            "replaced_location": location_filter.value,
        }
        fallback_trace["geo_filter_mode"] = "spatial"
        conversation_debug = list(fallback_trace.get("conversation_debug") or [])
        conversation_debug.append(f"Tentando fallback espacial com {boundary_layer.name()}::{boundary_field}")
        fallback_trace["conversation_debug"] = conversation_debug[:10]
        fallback_plan.planning_trace = fallback_trace
        log_info(
            "[Relatorios] fallback espacial "
            f"target_layer={target_layer.name()} boundary_layer={boundary_layer.name()} "
            f"boundary_field={boundary_field} value={boundary_value}"
        )
        return fallback_plan

    def _find_boundary_layer_match(
        self,
        target_layer: QgsVectorLayer,
        location_value,
    ) -> Optional[Tuple[QgsVectorLayer, str, object]]:
        expected_value = normalize_text(location_value)
        if not expected_value:
            return None

        best_match = None
        best_score = 0.0
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not layer.isValid() or layer.id() == target_layer.id():
                continue
            if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
                continue

            layer_name_text = normalize_text(layer.name())
            candidate_fields = []
            for index, field in enumerate(layer.fields()):
                field_name = field.name()
                field_text = normalize_text(" ".join([field_name, layer.attributeAlias(index) or ""]))
                if not self._location_like_field(field_text):
                    continue
                if field_text in {"id", "codigo", "cod"}:
                    continue
                candidate_fields.append(field_name)

            for field_name in candidate_fields[:6]:
                request = QgsFeatureRequest()
                request.setSubsetOfAttributes([field_name], layer.fields())
                request.setLimit(2000)
                if hasattr(request, "setNoGeometry"):
                    request.setNoGeometry(True)
                for feature in layer.getFeatures(request):
                    current_value = feature[field_name]
                    if not self._match_filter_value(
                        current_value,
                        FilterSpec(field=field_name, value=location_value, operator="eq", layer_role="boundary"),
                    ):
                        continue
                    score = 10.0
                    if any(token in layer_name_text for token in ("municipio", "cidade")):
                        score += 4.0
                    if any(token in normalize_text(field_name) for token in ("municipio", "cidade")):
                        score += 3.0
                    if any(token in normalize_text(field_name) for token in ("bairro", "setor", "distrito")):
                        score += 2.0
                    if score > best_score:
                        best_score = score
                        best_match = (layer, field_name, current_value)
                    break
        return best_match

    def _try_execution_fallback(
        self,
        plan: QueryPlan,
        target_layer: QgsVectorLayer,
    ) -> Optional[QueryResult]:
        fallback_plan = self._build_boundary_fallback_plan(plan, target_layer)
        if fallback_plan is None:
            return None
        fallback_result = self.execute(fallback_plan)
        if fallback_result.ok:
            return fallback_result
        return fallback_result

    def _execute_value_insight(self, plan: QueryPlan) -> QueryResult:
        layer = self._get_layer(plan.target_layer_id)
        if layer is None or not layer.isValid():
            return QueryResult(ok=False, message="Não encontrei a camada escolhida para esse relatório.", plan=plan)
        if plan.metric.operation in {"min", "max", "sum", "avg"}:
            if not plan.metric.field or plan.metric.field not in layer.fields().names():
                return QueryResult(ok=False, message="O campo consultado não existe mais nessa camada.", plan=plan)

        boundary_context, error_message = self._prepare_boundary_filter_context(plan, target_layer=layer)
        if error_message:
            return QueryResult(ok=False, message=error_message, plan=plan)

        values: List[float] = []
        total_value = 0.0
        contributing_count = 0
        processed = 0
        target_matches = 0
        boundary_filtered_out = 0
        distance_area = self._distance_area(layer)
        field_names = layer.fields().names()

        for feature in layer.getFeatures():
            if not self._feature_matches_filters(feature, plan.filters, field_names, "target"):
                continue
            target_matches += 1

            feature_geometry = feature.geometry()
            clipped_geometry = self._clip_geometry_to_boundary(feature_geometry, boundary_context)
            if boundary_context is not None and clipped_geometry is None:
                boundary_filtered_out += 1
                continue

            processed += 1
            if plan.metric.operation == "count":
                total_value += 1.0
                contributing_count += 1
                continue

            if plan.metric.use_geometry:
                if clipped_geometry is None or clipped_geometry.isEmpty():
                    continue
                if plan.metric.operation == "length":
                    numeric_value = self._safe_float(distance_area.measureLength(clipped_geometry))
                else:
                    numeric_value = self._safe_float(distance_area.measureArea(clipped_geometry))
                if numeric_value is None:
                    continue
                total_value += float(numeric_value)
                contributing_count += 1
                continue

            numeric_value = self._coerce_numeric(feature[plan.metric.field]) if plan.metric.field else None
            if numeric_value is None:
                continue
            if plan.metric.operation in {"min", "max"}:
                values.append(float(numeric_value))
            else:
                total_value += float(numeric_value)
            contributing_count += 1

        if plan.metric.operation in {"min", "max"}:
            if not values:
                fallback_result = self._try_execution_fallback(plan, layer)
                if fallback_result is not None:
                    return fallback_result
                return self._build_no_data_result(
                    plan,
                    layer_name=layer.name(),
                    target_matches=target_matches,
                    contributing_count=0,
                    boundary_filtered_out=boundary_filtered_out,
                    boundary_context=boundary_context,
                )
            selected_value = min(values) if plan.metric.operation == "min" else max(values)
        elif plan.metric.operation == "avg":
            if contributing_count <= 0:
                fallback_result = self._try_execution_fallback(plan, layer)
                if fallback_result is not None:
                    return fallback_result
                return self._build_no_data_result(
                    plan,
                    layer_name=layer.name(),
                    target_matches=target_matches,
                    contributing_count=contributing_count,
                    boundary_filtered_out=boundary_filtered_out,
                    boundary_context=boundary_context,
                )
            selected_value = total_value / max(1, contributing_count)
        else:
            if contributing_count <= 0:
                fallback_result = self._try_execution_fallback(plan, layer)
                if fallback_result is not None:
                    return fallback_result
                return self._build_no_data_result(
                    plan,
                    layer_name=layer.name(),
                    target_matches=target_matches,
                    contributing_count=contributing_count,
                    boundary_filtered_out=boundary_filtered_out,
                    boundary_context=boundary_context,
                )
            selected_value = total_value

        self._record_execution_trace(
            plan,
            status="ok",
            layer_name=layer.name(),
            target_matches=target_matches,
            contributing_count=contributing_count,
            boundary_filtered_out=boundary_filtered_out,
        )

        label = plan.metric.field_label or plan.metric.label or plan.metric.field or "Valor"
        return QueryResult(
            ok=True,
            summary=SummaryPayload(text=self._build_value_insight_summary(plan, selected_value, processed)),
            rows=[ResultRow(category=label, value=float(selected_value), raw_category=label)],
            value_label=self._value_label(plan),
            show_percent=False,
            plan=plan,
            total_records=processed,
            total_value=float(selected_value),
        )

    def _execute_derived_ratio(self, plan: QueryPlan) -> QueryResult:
        job = _DerivedRatioJob(self, plan)
        while not job.done:
            job.step(batch_size=320)
        return job.result

    def _execute_composite_metric(self, plan: QueryPlan) -> QueryResult:
        job = _CompositeMetricJob(self, plan)
        while not job.done:
            job.step(batch_size=320)
        return job.result

    def _build_operand_plan(self, composite_plan: QueryPlan, operand: CompositeOperandSpec) -> QueryPlan:
        operand_filters = [
            FilterSpec(
                field=item.field,
                value=item.value,
                operator=item.operator,
                layer_role="boundary" if item.layer_role == "boundary" else "target",
            )
            for item in list(operand.filters or [])
        ]
        return QueryPlan(
            intent="value_insight",
            original_question=composite_plan.original_question,
            target_layer_id=operand.layer_id,
            target_layer_name=operand.layer_name,
            boundary_layer_id=operand.boundary_layer_id,
            boundary_layer_name=operand.boundary_layer_name,
            metric=MetricSpec(
                operation=operand.metric.operation,
                field=operand.metric.field,
                field_label=operand.metric.field_label,
                use_geometry=operand.metric.use_geometry,
                label=operand.metric.label,
                source_geometry_hint=operand.metric.source_geometry_hint,
            ),
            filters=operand_filters,
            chart=composite_plan.chart,
        )

    def _finalize_composite_results(
        self,
        plan: QueryPlan,
        operands: List[CompositeOperandSpec],
        results: List[QueryResult],
    ) -> QueryResult:
        if len(operands) < 2 or len(results) < 2:
            return QueryResult(ok=False, message="Não encontrei dados suficientes para concluir essa operação.")

        operation = normalize_text(getattr(plan.composite, "operation", "") or plan.metric.operation or "")
        rows = [
            ResultRow(
                category=operand.label or result.rows[0].category,
                value=float(result.total_value),
                raw_category=operand.label or result.rows[0].category,
            )
            for operand, result in zip(operands, results)
        ]
        total_records = sum(int(result.total_records or 0) for result in results)

        if operation == "comparison":
            return QueryResult(
                ok=True,
                summary=SummaryPayload(text=self._build_composite_summary(plan, results, rows)),
                rows=rows,
                value_label=self._value_label(plan),
                show_percent=False,
                plan=plan,
                total_records=total_records,
                total_value=max(row.value for row in rows),
            )

        left_value = float(results[0].total_value)
        right_value = float(results[1].total_value)
        if operation == "ratio":
            if abs(right_value) < 0.0000001:
                return QueryResult(ok=False, message="Não encontrei dados suficientes no denominador para dividir.")
            computed = left_value / right_value
        elif operation == "difference":
            computed = left_value - right_value
        elif operation == "percentage":
            if abs(right_value) < 0.0000001:
                return QueryResult(ok=False, message="Não encontrei dados suficientes no total de referência para calcular o percentual.")
            computed = (left_value / right_value) * 100.0
        else:
            return QueryResult(ok=False, message="Operação composta ainda não suportada.")

        result_label = getattr(plan.composite, "label", "") or plan.metric.label or "Resultado"
        result_row = ResultRow(category=result_label, value=float(computed), raw_category=result_label)
        return QueryResult(
            ok=True,
            summary=SummaryPayload(text=self._build_composite_summary(plan, results, [result_row], operand_rows=rows)),
            rows=[result_row],
            value_label=self._value_label(plan),
            show_percent=False,
            plan=plan,
            total_records=total_records,
            total_value=float(computed),
        )

    def _execute_direct(self, plan: QueryPlan) -> QueryResult:
        layer = self._get_layer(plan.target_layer_id)
        if layer is None or not layer.isValid():
            return QueryResult(ok=False, message="Não encontrei a camada escolhida para esse relatório.", plan=plan)
        if plan.group_field not in layer.fields().names():
            return QueryResult(ok=False, message="O campo de agrupamento não existe mais nessa camada.", plan=plan)
        if plan.metric.field and plan.metric.field not in layer.fields().names():
            return QueryResult(ok=False, message="O campo numérico usado na consulta não existe mais.", plan=plan)

        boundary_context, error_message = self._prepare_boundary_filter_context(plan, target_layer=layer)
        if error_message:
            return QueryResult(ok=False, message=error_message, plan=plan)

        totals = defaultdict(float)
        counts = defaultdict(int)
        processed = 0
        target_matches = 0
        boundary_filtered_out = 0
        distance_area = self._distance_area(layer)
        field_names = layer.fields().names()

        for feature in layer.getFeatures():
            if not self._feature_matches_filters(feature, plan.filters, field_names, "target"):
                continue
            target_matches += 1
            feature_geometry = feature.geometry()
            clipped_geometry = self._clip_geometry_to_boundary(feature_geometry, boundary_context)
            if boundary_context is not None and clipped_geometry is None:
                boundary_filtered_out += 1
                continue

            category_value = self._render_category(feature[plan.group_field])
            if not category_value:
                continue

            if plan.metric.operation == "count":
                value = 1.0
            elif plan.metric.use_geometry:
                if clipped_geometry is None or clipped_geometry.isEmpty():
                    continue
                if plan.metric.operation == "length":
                    value = self._safe_float(distance_area.measureLength(clipped_geometry))
                else:
                    value = self._safe_float(distance_area.measureArea(clipped_geometry))
                if value is None:
                    continue
            else:
                value = self._safe_float(feature[plan.metric.field]) if plan.metric.field else None
                if value is None:
                    continue

            totals[category_value] += float(value)
            counts[category_value] += 1
            processed += 1

        if not totals:
            fallback_result = self._try_execution_fallback(plan, layer)
            if fallback_result is not None:
                return fallback_result
            return self._build_no_data_result(
                plan,
                layer_name=layer.name(),
                target_matches=target_matches,
                contributing_count=processed,
                boundary_filtered_out=boundary_filtered_out,
                boundary_context=boundary_context,
            )

        self._record_execution_trace(
            plan,
            status="ok",
            layer_name=layer.name(),
            target_matches=target_matches,
            contributing_count=processed,
            boundary_filtered_out=boundary_filtered_out,
        )
        return self._build_result(plan, totals, counts, processed)

    def _execute_spatial(self, plan: QueryPlan) -> QueryResult:
        source_layer = self._get_layer(plan.source_layer_id)
        boundary_layer = self._get_layer(plan.boundary_layer_id)
        if source_layer is None or not source_layer.isValid():
            return QueryResult(ok=False, message="Não encontrei a camada de origem dessa consulta.")
        if boundary_layer is None or not boundary_layer.isValid():
            return QueryResult(ok=False, message="Não encontrei a camada de limites dessa consulta.")
        if plan.group_field not in boundary_layer.fields().names():
            return QueryResult(ok=False, message="O campo de agrupamento não existe mais na camada de limites.")

        request = QgsFeatureRequest()
        if boundary_layer.fields().indexFromName(plan.group_field) >= 0:
            request.setSubsetOfAttributes([plan.group_field], boundary_layer.fields())

        boundary_features: Dict[int, object] = {}
        spatial_index = QgsSpatialIndex()
        transform = None
        if source_layer.crs() != boundary_layer.crs():
            try:
                transform = QgsCoordinateTransform(
                    boundary_layer.crs(),
                    source_layer.crs(),
                    QgsProject.instance(),
                )
            except Exception:
                transform = None
        for feature in boundary_layer.getFeatures(request):
            if not self._feature_matches_filters(feature, plan.filters, boundary_layer.fields().names(), "boundary"):
                continue
            geometry = feature.geometry()
            if geometry is None or geometry.isEmpty():
                continue
            if transform is not None:
                try:
                    geometry.transform(transform)
                except Exception:
                    continue

            boundary_features[feature.id()] = (geometry, feature[plan.group_field])
            index_feature = QgsFeature()
            index_feature.setId(feature.id())
            index_feature.setGeometry(geometry)
            spatial_index.addFeature(index_feature)

        if not boundary_features:
            return QueryResult(ok=False, message="A camada de limites não possui geometrias válidas.")

        totals = defaultdict(float)
        counts = defaultdict(int)
        processed = 0
        distance_area = self._distance_area(source_layer)

        for source_feature in source_layer.getFeatures():
            if not self._feature_matches_filters(source_feature, plan.filters, source_layer.fields().names(), "source"):
                continue
            source_geometry = source_feature.geometry()
            if source_geometry is None or source_geometry.isEmpty():
                continue

            candidate_ids = spatial_index.intersects(source_geometry.boundingBox())
            matched = False
            for boundary_id in candidate_ids:
                boundary_feature = boundary_features.get(boundary_id)
                if boundary_feature is None:
                    continue
                boundary_geometry, boundary_value = boundary_feature
                if boundary_geometry is None or boundary_geometry.isEmpty():
                    continue

                if plan.spatial_relation == "within":
                    is_match = source_geometry.within(boundary_geometry) or source_geometry.intersects(boundary_geometry)
                else:
                    is_match = source_geometry.intersects(boundary_geometry)
                if not is_match:
                    continue

                category_value = self._render_category(boundary_value)
                if not category_value:
                    continue

                if plan.metric.operation == "count":
                    value = 1.0
                else:
                    intersection = source_geometry.intersection(boundary_geometry)
                    if intersection is None or intersection.isEmpty():
                        continue
                    if plan.metric.operation == "length":
                        value = self._safe_float(distance_area.measureLength(intersection))
                    else:
                        value = self._safe_float(distance_area.measureArea(intersection))
                    if value is None:
                        continue

                totals[category_value] += float(value)
                counts[category_value] += 1
                matched = True

            if matched:
                processed += 1

        return self._build_result(plan, totals, counts, processed)

    def _build_result(self, plan: QueryPlan, totals, counts, processed: int) -> QueryResult:
        rows = []
        for category, total in totals.items():
            value = float(total)
            if plan.metric.operation == "avg":
                divider = max(1, counts.get(category, 0))
                value = value / divider
            rows.append(ResultRow(category=str(category), value=float(value), raw_category=category))

        if not rows:
            return QueryResult(ok=False, message="Não encontrei dados compatíveis com essa pergunta.", plan=plan)

        if plan.group_field_kind in {"date", "datetime"}:
            rows.sort(key=lambda item: str(item.raw_category))
        elif plan.group_field_kind in {"integer", "numeric"} or any(
            token in normalize_text(plan.group_field) for token in ("dn", "diam", "diametro", "bitola")
        ):
            rows.sort(key=lambda item: (self._coerce_numeric(item.raw_category) or 0.0, item.category.lower()), reverse=True)
        else:
            rows.sort(key=lambda item: (-item.value, item.category.lower()))

        if plan.top_n:
            rows = rows[: plan.top_n]

        total_value = sum(row.value for row in rows)
        show_percent = plan.metric.operation != "avg" and total_value > 0 and len(rows) > 1
        if show_percent:
            for row in rows:
                row.percent = (row.value / total_value) * 100.0 if total_value else None

        return QueryResult(
            ok=True,
            summary=SummaryPayload(text=self._build_summary(plan, rows, processed)),
            rows=rows,
            value_label=self._value_label(plan),
            show_percent=show_percent,
            plan=plan,
            total_records=processed,
            total_value=total_value,
        )

    def _build_summary(self, plan: QueryPlan, rows, processed: int) -> str:
        if not rows:
            return "Não encontrei dados compatíveis com essa pergunta."

        top = rows[0].category
        if plan.metric.operation == "count":
            if any(token in normalize_text(plan.group_field) for token in ("dn", "diam", "diametro", "bitola")):
                message = f"Foram encontrados {len(rows)} diâmetros distintos. O mais frequente é {top}."
            else:
                message = f"{top} possui a maior quantidade."
        elif plan.metric.operation == "length":
            message = f"{top} possui a maior extensão total."
        elif plan.metric.operation == "area":
            message = f"{top} possui a maior área total."
        elif plan.metric.operation == "avg":
            message = f"{top} possui a maior média."
        else:
            message = f"{top} possui o maior total."

        if plan.metric.operation == "count" and processed > 0 and len(rows) > 1:
            message += f" Foram encontrados {processed} registros distribuidos em {len(rows)} categorias."
        return message

    def _build_value_insight_summary(self, plan: QueryPlan, value: float, processed: int) -> str:
        field_label = (plan.metric.field_label or plan.metric.label or plan.metric.field or "valor").strip()
        value_text = self._format_summary_value(value)
        scope_text = self._summary_scope_text(plan)
        if plan.metric.operation == "count":
            message = f"Foram encontrados {value_text} registros{scope_text}."
        elif plan.metric.operation == "length":
            message = f"A extensão total{scope_text} é {value_text}."
        elif plan.metric.operation == "area":
            message = f"A área total{scope_text} é {value_text}."
        elif plan.metric.operation == "avg":
            message = f"A média de {field_label.lower()}{scope_text} é {value_text}."
        elif plan.metric.operation == "sum":
            message = f"O total de {field_label.lower()}{scope_text} e {value_text}."
        elif plan.metric.operation == "min":
            message = f"O menor {field_label.lower()}{scope_text} e {value_text}."
        else:
            message = f"O maior {field_label.lower()}{scope_text} e {value_text}."
        if processed > 0:
            message += f" Foram analisados {processed} registros."
        return message

    def _build_ratio_summary(self, plan: QueryPlan, value: float, total_length: float, total_links: int) -> str:
        ratio_text = self._format_summary_value(value)
        length_text = self._format_summary_value(total_length)
        scope_text = self._summary_scope_text(plan)
        return (
            f"A extensão média por ligação{scope_text} é {ratio_text} metros. "
            f"Foram considerados {length_text} metros de rede e {int(total_links)} ligações."
        )

    def _build_composite_summary(
        self,
        plan: QueryPlan,
        operand_results: List[QueryResult],
        rows: List[ResultRow],
        operand_rows: Optional[List[ResultRow]] = None,
    ) -> str:
        operation = normalize_text(getattr(plan.composite, "operation", "") or plan.metric.operation or "")
        all_rows = operand_rows or rows
        labels = [row.category for row in all_rows[:2]]
        values = [row.value for row in all_rows[:2]]
        if len(labels) < 2 or len(values) < 2:
            return "Operação composta concluída."

        left_label, right_label = labels[0], labels[1]
        left_value, right_value = values[0], values[1]
        if operation == "comparison":
            winner_label = left_label if left_value >= right_value else right_label
            return (
                f"{winner_label} possui o maior valor. "
                f"Foram comparados {self._format_summary_value(left_value)} e {self._format_summary_value(right_value)}."
            )
        if operation == "difference":
            return (
                f"A diferença entre {left_label} e {right_label} é {self._format_summary_value(rows[0].value)}. "
                f"Valores comparados: {self._format_summary_value(left_value)} e {self._format_summary_value(right_value)}."
            )
        if operation == "percentage":
            return (
                f"{left_label} representa {self._format_summary_value(rows[0].value)}% de {right_label}. "
                f"Valores usados: {self._format_summary_value(left_value)} e {self._format_summary_value(right_value)}."
            )
        if operation == "ratio":
            return (
                f"A razão entre {left_label} e {right_label} é {self._format_summary_value(rows[0].value)}. "
                f"Valores usados: {self._format_summary_value(left_value)} e {self._format_summary_value(right_value)}."
            )
        return "Operação composta concluída."

    def _value_label(self, plan: QueryPlan) -> str:
        if plan.intent == "composite_metric":
            operation = normalize_text(getattr(plan.composite, "operation", "") or plan.metric.operation or "")
            if operation == "ratio":
                return getattr(plan.composite, "unit_label", "") or "Razao"
            if operation == "difference":
                return getattr(plan.composite, "unit_label", "") or "Diferenca"
            if operation == "percentage":
                return "%"
            if operation == "comparison":
                return getattr(plan.composite, "unit_label", "") or "Valor"
        if plan.metric.operation == "ratio":
            return "Metros por ligação"
        if plan.metric.operation == "count":
            return "Quantidade"
        if plan.metric.operation == "length":
            return "Extensao"
        if plan.metric.operation == "area":
            return "Area"
        if plan.metric.operation == "avg":
            return "Media"
        if plan.metric.operation == "sum":
            return plan.metric.field_label or plan.metric.label or "Total"
        if plan.metric.operation == "max":
            return plan.metric.label or "Maior valor"
        if plan.metric.operation == "min":
            return plan.metric.label or "Menor valor"
        return "Valor"

    def _distance_area(self, layer: QgsVectorLayer) -> QgsDistanceArea:
        distance_area = QgsDistanceArea()
        distance_area.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
        ellipsoid = QgsProject.instance().ellipsoid()
        if ellipsoid:
            try:
                distance_area.setEllipsoid(ellipsoid)
            except Exception:
                pass
        return distance_area

    def _prepare_boundary_filter_context(
        self,
        plan: QueryPlan,
        target_layer: QgsVectorLayer,
    ) -> Tuple[Optional[Dict], str]:
        if not plan.boundary_layer_id:
            return None, ""

        boundary_layer = self._get_layer(plan.boundary_layer_id)
        if boundary_layer is None or not boundary_layer.isValid():
            return None, "Não encontrei a camada de limite usada para esse filtro geográfico."

        boundary_filters = [item for item in plan.filters if isinstance(item, FilterSpec) and item.layer_role == "boundary"]
        if not boundary_filters:
            return None, ""

        request = QgsFeatureRequest()
        subset_fields = [item.field for item in boundary_filters if item.field in boundary_layer.fields().names()]
        if subset_fields:
            request.setSubsetOfAttributes(sorted(set(subset_fields)), boundary_layer.fields())

        transform = None
        if target_layer.crs() != boundary_layer.crs():
            try:
                transform = QgsCoordinateTransform(
                    boundary_layer.crs(),
                    target_layer.crs(),
                    QgsProject.instance(),
                )
            except Exception:
                transform = None

        geometries: Dict[int, object] = {}
        spatial_index = QgsSpatialIndex()
        for feature in boundary_layer.getFeatures(request):
            if not self._feature_matches_filters(feature, plan.filters, boundary_layer.fields().names(), "boundary"):
                continue
            geometry = feature.geometry()
            if geometry is None or geometry.isEmpty():
                continue
            if transform is not None:
                try:
                    geometry.transform(transform)
                except Exception:
                    continue

            geometries[feature.id()] = geometry
            index_feature = QgsFeature()
            index_feature.setId(feature.id())
            index_feature.setGeometry(geometry)
            spatial_index.addFeature(index_feature)

        if not geometries:
            return None, "Não encontrei um limite geográfico compatível com esse filtro."
        return {
            "geometries": geometries,
            "index": spatial_index,
            "layer_name": boundary_layer.name(),
            "matched_boundary_count": len(geometries),
            "mode": "spatial",
        }, ""

    def _clip_geometry_to_boundary(self, geometry, boundary_context: Optional[Dict]):
        if boundary_context is None:
            return geometry
        if geometry is None or geometry.isEmpty():
            return None

        candidate_ids = boundary_context["index"].intersects(geometry.boundingBox())
        clipped_geometry = None
        for boundary_id in candidate_ids:
            boundary_geometry = boundary_context["geometries"].get(boundary_id)
            if boundary_geometry is None or boundary_geometry.isEmpty():
                continue
            if not (geometry.intersects(boundary_geometry) or geometry.within(boundary_geometry) or boundary_geometry.contains(geometry)):
                continue
            intersection = geometry.intersection(boundary_geometry)
            if intersection is None or intersection.isEmpty():
                continue
            if clipped_geometry is None:
                clipped_geometry = intersection
            else:
                try:
                    clipped_geometry = clipped_geometry.combine(intersection)
                except Exception:
                    try:
                        clipped_geometry = clipped_geometry.union(intersection)
                    except Exception:
                        pass
        return clipped_geometry

    def _summary_scope_text(self, plan: QueryPlan) -> str:
        filter_text = (plan.detected_filters_text or "").strip()
        if not filter_text:
            return ""
        lowered = normalize_text(filter_text)
        if lowered.startswith(("em ", "no ", "na ")):
            return f" {filter_text}"
        return f" com {filter_text}"

    def _get_layer(self, layer_id: Optional[str]) -> Optional[QgsVectorLayer]:
        if not layer_id:
            return None
        layer = QgsProject.instance().mapLayer(layer_id)
        if isinstance(layer, QgsVectorLayer):
            return layer
        return None

    def _render_category(self, value) -> str:
        if value in (None, ""):
            return ""
        return str(value).strip()

    def _safe_float(self, value) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except Exception:
            return None

    def _feature_matches_filters(self, feature, filters, field_names, layer_role: str) -> bool:
        if not filters:
            return True
        field_names = set(field_names or [])
        for filter_spec in filters:
            if not isinstance(filter_spec, FilterSpec):
                continue
            if filter_spec.layer_role not in {"any", layer_role}:
                continue
            if not filter_spec.field or filter_spec.field not in field_names:
                return False

            current_value = feature[filter_spec.field]
            if not self._match_filter_value(current_value, filter_spec):
                return False
        return True

    def _match_filter_value(self, current_value, filter_spec: FilterSpec) -> bool:
        operator = (filter_spec.operator or "eq").lower()
        if operator in {"is_null", "null"}:
            return current_value in (None, "")
        if operator in {"not_null", "has_value"}:
            if current_value in (None, ""):
                return False
            current_text = normalize_text(current_value)
            return current_text not in {"null", "none", "nan"}
        if current_value in (None, ""):
            return False

        expected = filter_spec.value
        current_text = normalize_text(current_value)
        expected_text = normalize_text(expected)
        current_compact = normalize_compact(current_value)
        expected_compact = normalize_compact(expected)
        current_number = self._coerce_numeric(current_value)
        expected_number = self._coerce_numeric(expected)

        matches = False
        if current_number is not None and expected_number is not None:
            matches = abs(current_number - expected_number) < 0.0001
        if not matches and expected_text:
            matches = current_text == expected_text or current_compact == expected_compact
        if not matches and expected_text:
            current_status = self._normalize_status_value(current_text)
            expected_status = self._normalize_status_value(expected_text)
            if current_status and expected_status and current_status == expected_status:
                matches = True
        if not matches and expected_text:
            matches = f" {expected_text} " in f" {current_text} " or expected_text in current_text
        if not matches and expected_compact:
            matches = expected_compact in current_compact
        if not matches and expected_text:
            expected_tokens = {token for token in expected_text.split() if token and token not in {"de", "do", "da", "dos", "das"}}
            current_tokens = {token for token in current_text.split() if token}
            if len(expected_tokens) >= 2 and expected_tokens.issubset(current_tokens):
                matches = True

        if operator == "contains":
            return bool(expected_text and expected_text in current_text) or bool(expected_compact and expected_compact in current_compact)
        if operator == "neq":
            return not matches
        return matches

    def _normalize_status_value(self, value) -> str:
        normalized = normalize_text(value)
        if not normalized:
            return ""
        if "ativ" in normalized:
            return "ativo"
        if "inativ" in normalized:
            return "inativo"
        if "cancel" in normalized:
            return "cancelado"
        if "suspens" in normalized:
            return "suspenso"
        if "elimina" in normalized:
            return "eliminado"
        if "cortad" in normalized:
            return "cortado"
        return normalized

    def _coerce_numeric(self, value) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            cleaned = "".join(char for char in str(value) if char.isdigit() or char in ",.-")
            if not cleaned:
                return None
            cleaned = cleaned.replace(",", ".")
            if cleaned.count(".") > 1:
                cleaned = cleaned.replace(".", "", cleaned.count(".") - 1)
            return float(cleaned)
        except Exception:
            return None

    def _format_summary_value(self, value: float) -> str:
        if abs(value - round(value)) < 0.0001:
            return str(int(round(value)))
        return f"{value:.2f}".replace(".", ",")
