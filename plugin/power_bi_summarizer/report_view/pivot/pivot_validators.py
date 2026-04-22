from __future__ import annotations

from typing import Iterable, Optional

from qgis.PyQt.QtCore import QVariant
from qgis.core import QgsWkbTypes

from .pivot_models import PivotFieldSpec, PivotRequest
from ...utils.i18n_runtime import tr_text as _rt


class PivotValidationError(Exception):
    pass


class PivotValidator:
    TEXT_ALLOWED_AGGREGATIONS = {"count", "min", "max", "unique"}
    NUMERIC_ALLOWED_AGGREGATIONS = {
        "count",
        "sum",
        "average",
        "min",
        "max",
        "median",
        "unique",
        "variance",
        "stddev",
    }

    @classmethod
    def validate_request(cls, request: PivotRequest, layer) -> None:
        cls._validate_presence(request, layer)
        cls._validate_duplicates(request)
        cls._validate_aggregation(request)
        cls._validate_field_compatibility(request, layer)
        cls._validate_geometry_compatibility(request, layer)

    @classmethod
    def _validate_presence(cls, request: PivotRequest, layer) -> None:
        if layer is None or not getattr(layer, "isValid", lambda: False)():
            raise PivotValidationError(_rt("Selecione uma camada válida."))
        if not request.row_fields and not request.column_fields and request.value_field is None:
            raise PivotValidationError(_rt("Escolha ao menos um campo para montar a tabela dinâmica."))
        if request.aggregation != "count" and request.value_field is None:
            raise PivotValidationError(_rt("Escolha um campo de valor para essa agregação."))

    @classmethod
    def _validate_aggregation(cls, request: PivotRequest) -> None:
        allowed = cls.TEXT_ALLOWED_AGGREGATIONS | cls.NUMERIC_ALLOWED_AGGREGATIONS
        if request.aggregation not in allowed:
            raise PivotValidationError(_rt("A agregação escolhida não é suportada."))

    @classmethod
    def _validate_field_compatibility(cls, request: PivotRequest, layer) -> None:
        for field_spec in cls._iter_field_specs(request):
            if field_spec.source_type == "geometry":
                continue
            field_index = layer.fields().indexFromName(field_spec.field_name)
            field = layer.fields()[field_index] if field_index >= 0 else None
            if field is None:
                raise PivotValidationError(
                    _rt("O campo '{field_name}' não existe.", field_name=field_spec.display_name or field_spec.field_name)
                )

            inferred_type = field_spec.data_type or cls._infer_data_type(field.type())
            if field_spec is request.value_field:
                if request.aggregation not in cls._allowed_for_data_type(inferred_type):
                    raise PivotValidationError(
                        _rt(
                            "A agregação '{aggregation}' não combina com o campo '{field_name}'.",
                            aggregation=request.aggregation,
                            field_name=field_spec.display_name or field_spec.field_name,
                        )
                    )

    @classmethod
    def _validate_geometry_compatibility(cls, request: PivotRequest, layer) -> None:
        specs = [field for field in cls._iter_field_specs(request) if field.source_type == "geometry"]
        if not specs:
            return

        geometry_type = QgsWkbTypes.geometryType(layer.wkbType())
        for field_spec in specs:
            if field_spec.geometry_op == "area" and geometry_type != QgsWkbTypes.PolygonGeometry:
                raise PivotValidationError(_rt("Área só pode ser usada em camada poligonal."))
            if field_spec.geometry_op == "length" and geometry_type not in {
                QgsWkbTypes.LineGeometry,
                QgsWkbTypes.PolygonGeometry,
            }:
                raise PivotValidationError(_rt("Comprimento só pode ser usado em linha ou polígono."))

    @classmethod
    def _validate_duplicates(cls, request: PivotRequest) -> None:
        for area_name, specs in (
            ("linhas", request.row_fields),
            ("colunas", request.column_fields),
        ):
            seen = set()
            for field_spec in specs:
                key = (field_spec.source_type, field_spec.field_name, field_spec.geometry_op)
                if key in seen:
                    raise PivotValidationError(
                        _rt(
                            "O campo '{field_name}' foi escolhido mais de uma vez.",
                            field_name=field_spec.display_name or field_spec.field_name,
                        )
                    )
                seen.add(key)

    @classmethod
    def _iter_field_specs(cls, request: PivotRequest) -> Iterable[PivotFieldSpec]:
        for field_spec in request.row_fields:
            yield field_spec
        for field_spec in request.column_fields:
            yield field_spec
        if request.value_field is not None:
            yield request.value_field

    @classmethod
    def _allowed_for_data_type(cls, data_type: Optional[str]) -> set:
        if data_type == "numeric":
            return set(cls.NUMERIC_ALLOWED_AGGREGATIONS)
        return set(cls.TEXT_ALLOWED_AGGREGATIONS)

    @classmethod
    def _infer_data_type(cls, variant_type: int) -> str:
        if variant_type in {
            QVariant.Int,
            QVariant.UInt,
            QVariant.LongLong,
            QVariant.ULongLong,
            QVariant.Double,
        }:
            return "numeric"
        if variant_type in {QVariant.Date, QVariant.DateTime, QVariant.Time}:
            return "date"
        if variant_type == QVariant.Bool:
            return "bool"
        return "text"
