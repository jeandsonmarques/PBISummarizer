from .operation_planner import OperationPlanner
from .result_models import FieldSchema, LayerSchema, ProjectSchema
from .schema_context_builder import SchemaContextBuilder


def _field(
    name: str,
    alias: str = "",
    kind: str = "text",
    is_filter_candidate: bool = False,
    is_location_candidate: bool = False,
):
    return FieldSchema(
        name=name,
        alias=alias,
        kind=kind,
        is_filter_candidate=is_filter_candidate,
        is_location_candidate=is_location_candidate,
        search_text=f"{name} {alias}".strip(),
    )


def build_sample_schema() -> ProjectSchema:
    return ProjectSchema(
        layers=[
            LayerSchema(
                layer_id="rede_layer",
                name="rede_distribuicao",
                geometry_type="line",
                feature_count=1200,
                fields=[
                    _field("municipio", kind="text", is_filter_candidate=True, is_location_candidate=True),
                    _field("bairro", kind="text", is_filter_candidate=True, is_location_candidate=True),
                    _field("dn", alias="diametro", kind="integer", is_filter_candidate=True),
                    _field("material", kind="text", is_filter_candidate=True),
                    _field("ext_m", alias="extensao", kind="numeric"),
                ],
            ),
            LayerSchema(
                layer_id="ligacoes_layer",
                name="ligacoes_agua",
                geometry_type="point",
                feature_count=4500,
                fields=[
                    _field("bairro", kind="text", is_filter_candidate=True, is_location_candidate=True),
                    _field("municipio", kind="text", is_filter_candidate=True, is_location_candidate=True),
                    _field("status", kind="text", is_filter_candidate=True),
                ],
            ),
            LayerSchema(
                layer_id="bairros_layer",
                name="limite_bairros",
                geometry_type="polygon",
                feature_count=30,
                fields=[
                    _field("nome", alias="bairro", kind="text", is_filter_candidate=True, is_location_candidate=True),
                    _field("municipio", kind="text", is_filter_candidate=True, is_location_candidate=True),
                ],
            ),
        ]
    )


def run_examples():
    schema = build_sample_schema()
    schema_context = SchemaContextBuilder().build(schema)
    planner = OperationPlanner()

    examples = {
        "quantos metros de rede DN150 existem em Agua Branca": {
            "metric_hint": "length",
            "subject_hint": "rede",
            "diameter": "150",
            "location": "Agua Branca",
            "top_layer": "rede_distribuicao",
        },
        "somar extensao de rede por diametro": {
            "metric_hint": "length",
            "subject_hint": "rede",
            "attribute_hint": "diameter",
            "top_layer": "rede_distribuicao",
        },
        "rede de PVC por municipio": {
            "subject_hint": "rede",
            "material": "PVC",
            "group_hint": "municipio",
            "top_layer": "rede_distribuicao",
        },
        "total de ligacoes por bairro": {
            "subject_hint": "ligacao",
            "group_hint": "bairro",
            "top_layer": "ligacoes_agua",
        },
        "ligacoes de agua em penedo": {
            "metric_hint": "count",
            "subject_hint": "ligacao",
            "location": "Penedo",
            "top_layer": "ligacoes_agua",
        },
    }

    for question, expected in examples.items():
        brief = planner.build_brief(question, schema_context)
        assert brief.likely_layers, f"Sem camada sugerida para: {question}"
        assert brief.likely_layers[0].layer_name == expected["top_layer"], (question, brief.likely_layers[0])
        for key, value in expected.items():
            if key == "top_layer":
                continue
            if key == "diameter":
                assert any(item["kind"] == "diameter" and item["value"] == value for item in brief.extracted_filters), brief
            elif key == "location":
                assert any(item["kind"] == "location" and item["value"] == value for item in brief.extracted_filters), brief
            elif key == "material":
                assert any(item["kind"] == "material" and item["value"] == value for item in brief.extracted_filters), brief
            else:
                assert getattr(brief, key) == value, (question, key, getattr(brief, key))


if __name__ == "__main__":  # pragma: no cover
    run_examples()
    print("Smoke tests ok.")
