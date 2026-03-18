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
)

from .result_models import FilterSpec, QueryPlan, QueryResult, ResultRow, SummaryPayload
from .text_utils import normalize_compact, normalize_text


class ReportExecutionJob:
    def __init__(self, executor: "ReportExecutor", plan: QueryPlan):
        self.executor = executor
        self.plan = plan
        self.processed = 0
        self.total_estimate = 0
        self.phase_label = "processando"
        self._done = False
        self._result = QueryResult(ok=False, message="A execucao ainda nao terminou.")

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
            self._complete(QueryResult(ok=False, message="Nao encontrei a camada escolhida para esse relatorio."))
            return
        if plan.metric.operation in {"min", "max", "sum", "avg"}:
            if not plan.metric.field or plan.metric.field not in self.layer.fields().names():
                self._complete(QueryResult(ok=False, message="O campo consultado nao existe mais nessa camada."))
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

            feature_geometry = feature.geometry()
            clipped_geometry = self.executor._clip_geometry_to_boundary(feature_geometry, self.boundary_context)
            if self.boundary_context is not None and clipped_geometry is None:
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
                self._complete(QueryResult(ok=False, message="Nao encontrei dados compativeis com essa pergunta."))
                return
            selected_value = min(self.values) if self.plan.metric.operation == "min" else max(self.values)
        elif self.plan.metric.operation == "avg":
            if self.contributing_count <= 0:
                self._complete(QueryResult(ok=False, message="Nao encontrei dados compativeis com essa pergunta."))
                return
            selected_value = self.total_value / max(1, self.contributing_count)
        else:
            if self.contributing_count <= 0:
                self._complete(QueryResult(ok=False, message="Nao encontrei dados compativeis com essa pergunta."))
                return
            selected_value = self.total_value

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
            self._complete(QueryResult(ok=False, message="Nao encontrei a camada escolhida para esse relatorio."))
            return
        if plan.group_field not in self.layer.fields().names():
            self._complete(QueryResult(ok=False, message="O campo de agrupamento nao existe mais nessa camada."))
            return
        if plan.metric.field and plan.metric.field not in self.layer.fields().names():
            self._complete(QueryResult(ok=False, message="O campo numerico usado na consulta nao existe mais."))
            return

        boundary_context, error_message = self.executor._prepare_boundary_filter_context(plan, target_layer=self.layer)
        if error_message:
            self._complete(QueryResult(ok=False, message=error_message))
            return

        self.boundary_context = boundary_context
        self.totals = defaultdict(float)
        self.counts = defaultdict(int)
        self.filtered_records = 0
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
                self._complete(self.executor._build_result(self.plan, self.totals, self.counts, self.filtered_records))
                return

            self.processed += 1
            if not self.executor._feature_matches_filters(feature, self.plan.filters, self.field_names, "target"):
                continue
            feature_geometry = feature.geometry()
            clipped_geometry = self.executor._clip_geometry_to_boundary(feature_geometry, self.boundary_context)
            if self.boundary_context is not None and clipped_geometry is None:
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
            self._complete(QueryResult(ok=False, message="Nao encontrei a camada de origem dessa consulta."))
            return
        if self.boundary_layer is None or not self.boundary_layer.isValid():
            self._complete(QueryResult(ok=False, message="Nao encontrei a camada de limites dessa consulta."))
            return
        if plan.group_field not in self.boundary_layer.fields().names():
            self._complete(QueryResult(ok=False, message="O campo de agrupamento nao existe mais na camada de limites."))
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
                    self._complete(QueryResult(ok=False, message="A camada de limites nao possui geometrias validas."))
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


class ReportExecutor:
    def execute(self, plan: QueryPlan) -> QueryResult:
        if plan.intent == "value_insight":
            return self._execute_value_insight(plan)
        if plan.intent == "aggregate_chart":
            return self._execute_direct(plan)
        if plan.intent == "spatial_aggregate":
            return self._execute_spatial(plan)
        return QueryResult(ok=False, message="Nao foi possivel montar um plano de consulta valido.")

    def create_job(self, plan: QueryPlan) -> ReportExecutionJob:
        if plan.intent == "value_insight":
            return _ValueInsightJob(self, plan)
        if plan.intent == "aggregate_chart":
            return _DirectAggregateJob(self, plan)
        if plan.intent == "spatial_aggregate":
            return _SpatialAggregateJob(self, plan)
        job = ReportExecutionJob(self, plan)
        job._complete(QueryResult(ok=False, message="Nao foi possivel montar um plano de consulta valido."))
        return job

    def _execute_value_insight(self, plan: QueryPlan) -> QueryResult:
        layer = self._get_layer(plan.target_layer_id)
        if layer is None or not layer.isValid():
            return QueryResult(ok=False, message="Nao encontrei a camada escolhida para esse relatorio.")
        if plan.metric.operation in {"min", "max", "sum", "avg"}:
            if not plan.metric.field or plan.metric.field not in layer.fields().names():
                return QueryResult(ok=False, message="O campo consultado nao existe mais nessa camada.")

        boundary_context, error_message = self._prepare_boundary_filter_context(plan, target_layer=layer)
        if error_message:
            return QueryResult(ok=False, message=error_message)

        values: List[float] = []
        total_value = 0.0
        contributing_count = 0
        processed = 0
        distance_area = self._distance_area(layer)
        field_names = layer.fields().names()

        for feature in layer.getFeatures():
            if not self._feature_matches_filters(feature, plan.filters, field_names, "target"):
                continue

            feature_geometry = feature.geometry()
            clipped_geometry = self._clip_geometry_to_boundary(feature_geometry, boundary_context)
            if boundary_context is not None and clipped_geometry is None:
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
                return QueryResult(ok=False, message="Nao encontrei dados compativeis com essa pergunta.")
            selected_value = min(values) if plan.metric.operation == "min" else max(values)
        elif plan.metric.operation == "avg":
            if contributing_count <= 0:
                return QueryResult(ok=False, message="Nao encontrei dados compativeis com essa pergunta.")
            selected_value = total_value / max(1, contributing_count)
        else:
            if contributing_count <= 0:
                return QueryResult(ok=False, message="Nao encontrei dados compativeis com essa pergunta.")
            selected_value = total_value

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

    def _execute_direct(self, plan: QueryPlan) -> QueryResult:
        layer = self._get_layer(plan.target_layer_id)
        if layer is None or not layer.isValid():
            return QueryResult(ok=False, message="Nao encontrei a camada escolhida para esse relatorio.")
        if plan.group_field not in layer.fields().names():
            return QueryResult(ok=False, message="O campo de agrupamento nao existe mais nessa camada.")
        if plan.metric.field and plan.metric.field not in layer.fields().names():
            return QueryResult(ok=False, message="O campo numerico usado na consulta nao existe mais.")

        boundary_context, error_message = self._prepare_boundary_filter_context(plan, target_layer=layer)
        if error_message:
            return QueryResult(ok=False, message=error_message)

        totals = defaultdict(float)
        counts = defaultdict(int)
        processed = 0
        distance_area = self._distance_area(layer)
        field_names = layer.fields().names()

        for feature in layer.getFeatures():
            if not self._feature_matches_filters(feature, plan.filters, field_names, "target"):
                continue
            feature_geometry = feature.geometry()
            clipped_geometry = self._clip_geometry_to_boundary(feature_geometry, boundary_context)
            if boundary_context is not None and clipped_geometry is None:
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

        return self._build_result(plan, totals, counts, processed)

    def _execute_spatial(self, plan: QueryPlan) -> QueryResult:
        source_layer = self._get_layer(plan.source_layer_id)
        boundary_layer = self._get_layer(plan.boundary_layer_id)
        if source_layer is None or not source_layer.isValid():
            return QueryResult(ok=False, message="Nao encontrei a camada de origem dessa consulta.")
        if boundary_layer is None or not boundary_layer.isValid():
            return QueryResult(ok=False, message="Nao encontrei a camada de limites dessa consulta.")
        if plan.group_field not in boundary_layer.fields().names():
            return QueryResult(ok=False, message="O campo de agrupamento nao existe mais na camada de limites.")

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
            return QueryResult(ok=False, message="A camada de limites nao possui geometrias validas.")

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
            return QueryResult(ok=False, message="Nao encontrei dados compativeis com essa pergunta.")

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
            return "Nao encontrei dados compativeis com essa pergunta."

        top = rows[0].category
        if plan.metric.operation == "count":
            if any(token in normalize_text(plan.group_field) for token in ("dn", "diam", "diametro", "bitola")):
                message = f"Foram encontrados {len(rows)} diametros distintos. O mais frequente e {top}."
            else:
                message = f"{top} possui a maior quantidade."
        elif plan.metric.operation == "length":
            message = f"{top} possui a maior extensao total."
        elif plan.metric.operation == "area":
            message = f"{top} possui a maior area total."
        elif plan.metric.operation == "avg":
            message = f"{top} possui a maior media."
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
            message = f"A extensao total{scope_text} e {value_text}."
        elif plan.metric.operation == "area":
            message = f"A area total{scope_text} e {value_text}."
        elif plan.metric.operation == "avg":
            message = f"A media de {field_label.lower()}{scope_text} e {value_text}."
        elif plan.metric.operation == "sum":
            message = f"O total de {field_label.lower()}{scope_text} e {value_text}."
        elif plan.metric.operation == "min":
            message = f"O menor {field_label.lower()}{scope_text} e {value_text}."
        else:
            message = f"O maior {field_label.lower()}{scope_text} e {value_text}."
        if processed > 0:
            message += f" Foram analisados {processed} registros."
        return message

    def _value_label(self, plan: QueryPlan) -> str:
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
            return None, "Nao encontrei a camada de limite usada para esse filtro geografico."

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
            return None, "Nao encontrei um limite geografico compativel com esse filtro."
        return {"geometries": geometries, "index": spatial_index}, ""

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
            matches = f" {expected_text} " in f" {current_text} " or expected_text in current_text
        if not matches and expected_compact:
            matches = expected_compact in current_compact

        if operator == "contains":
            return bool(expected_text and expected_text in current_text) or bool(expected_compact and expected_compact in current_compact)
        if operator == "neq":
            return not matches
        return matches

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
