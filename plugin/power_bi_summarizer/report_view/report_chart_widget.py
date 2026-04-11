from __future__ import annotations

from typing import List

from .chart_factory import ReportChartWidget
from .pivot.pivot_formatters import PivotFormatter
from .pivot.pivot_models import PivotResult
from .result_models import ChartPayload


class ReportPivotChartWidget(ReportChartWidget):
    def render_from_pivot_result(self, result: PivotResult, orientation: str = "rows", chart_type: str = "bar"):
        payload = self._pivot_result_to_chart_payload(result, orientation)
        if payload is None:
            self.set_payload(None, empty_text="Sem dados para exibir")
            return
        payload.chart_type = chart_type
        self.set_payload(payload)

    def _pivot_result_to_chart_payload(self, result: PivotResult, orientation: str):
        categories: List[str] = []
        values: List[float] = []
        feature_groups: List[List[int]] = []

        if orientation == "columns":
            for column_index, column_key in enumerate(result.column_headers):
                value = result.column_totals.get(column_key)
                if value is None:
                    value = self._sum_numeric_cells(
                        [row[column_index] for row in result.matrix if column_index < len(row)]
                    )
                if value is None:
                    continue
                categories.append(PivotFormatter.format_header_tuple(column_key))
                values.append(float(value))
                feature_groups.append(
                    self._merge_ids(
                        [row[column_index].feature_ids for row in result.matrix if column_index < len(row)]
                    )
                )
        else:
            for row_index, row_key in enumerate(result.row_headers):
                value = result.row_totals.get(row_key)
                if value is None:
                    value = self._sum_numeric_cells(
                        result.matrix[row_index] if row_index < len(result.matrix) else []
                    )
                if value is None:
                    continue
                categories.append(PivotFormatter.format_header_tuple(row_key))
                values.append(float(value))
                feature_groups.append(
                    self._merge_ids(
                        [cell.feature_ids for cell in (result.matrix[row_index] if row_index < len(result.matrix) else [])]
                    )
                )

        if not categories:
            return None

        metadata = dict(result.metadata or {})
        row_fields = list(metadata.get("row_fields") or [])
        column_fields = list(metadata.get("column_fields") or [])
        if orientation == "columns":
            category_field = " / ".join(column_fields) if column_fields else "Grupo"
        else:
            category_field = " / ".join(row_fields) if row_fields else "Grupo"
        return ChartPayload.build(
            chart_type="bar",
            title="Tabela dinamica",
            categories=categories,
            values=values,
            value_label=str(metadata.get("aggregation") or "Valor"),
            selection_layer_id=metadata.get("layer_id"),
            selection_layer_name=metadata.get("layer_name") or "",
            category_field=category_field,
            raw_categories=list(result.row_headers if orientation != "columns" else result.column_headers),
            category_feature_ids=feature_groups,
        )

    def _sum_numeric_cells(self, cells):
        total = 0.0
        found = False
        for cell in cells or []:
            raw_value = getattr(cell, "raw_value", None)
            if isinstance(raw_value, (int, float)):
                total += float(raw_value)
                found = True
        return total if found else None

    def _merge_ids(self, groups) -> List[int]:
        merged = []
        seen = set()
        for group in groups or []:
            for feature_id in group or []:
                if feature_id in seen:
                    continue
                seen.add(feature_id)
                merged.append(int(feature_id))
        return merged
