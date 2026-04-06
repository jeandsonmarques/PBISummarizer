import json

from .operation_planner import OperationPlanner
from .dictionary_service import build_dictionary_service
from .ollama_fallback_service import OllamaFallbackService
from .query_preprocessor import QueryPreprocessor
from .conversation_state import ActiveQueryState, ConversationState
from .context_merge_engine import ContextMergeEngine
from .field_role_resolver import FieldRoleResolver
from .followup_resolver import FollowupResolver
from .result_models import FieldSchema, LayerSchema, MetricSpec, ProjectSchema, QueryPlan, QueryResult
from .schema_context_builder import SchemaContextBuilder
from .schema_linker_service import SchemaLinkerService
from .text_utils import normalize_text
from .report_context_memory import ReportContextMemory


def _field(
    name: str,
    alias: str = "",
    kind: str = "text",
    is_filter_candidate: bool = False,
    is_location_candidate: bool = False,
    sample_values=None,
    top_values=None,
):
    return FieldSchema(
        name=name,
        alias=alias,
        kind=kind,
        sample_values=list(sample_values or []),
        top_values=list(top_values or []),
        is_filter_candidate=is_filter_candidate,
        is_location_candidate=is_location_candidate,
        search_text=" ".join([name, alias] + list(sample_values or []) + list(top_values or [])).strip(),
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
                    _field("status", kind="text", is_filter_candidate=True, top_values=["Ativo", "Inativo", "Cancelado"]),
                    _field(
                        "nm_situacao_ligacao_agua",
                        alias="situacao ligacao agua",
                        kind="text",
                        is_filter_candidate=True,
                        top_values=["Ativa", "Eliminada", "Cortada Cavalete"],
                    ),
                    _field(
                        "nm_situacao_ligacao_esgoto",
                        alias="situacao ligacao esgoto",
                        kind="text",
                        is_filter_candidate=True,
                        top_values=["Ativa", "Cancelada", "Eliminada"],
                    ),
                    _field(
                        "tipo_servico",
                        alias="servico",
                        kind="text",
                        is_filter_candidate=True,
                        top_values=["Agua", "Esgoto"],
                    ),
                    _field(
                        "tipo_pavimento",
                        alias="tipo de pavimento",
                        kind="text",
                        is_filter_candidate=True,
                        top_values=["Asfalto", "Paralelepipedo"],
                    ),
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


def run_dictionary_examples():
    dictionary_service = build_dictionary_service()
    assert dictionary_service.entry_count > 1000, dictionary_service.entry_count
    normalized = dictionary_service.normalize_query("qts mts rede agua")
    assert "metro" in normalized, normalized


def run_regression_examples():
    schema = build_sample_schema()
    schema_context = SchemaContextBuilder().build(schema)
    planner = OperationPlanner()
    preprocessor = QueryPreprocessor()
    linker = SchemaLinkerService()

    brief = planner.build_brief("quantas ligacoes ativas em penedo", schema_context)
    assert any(item["kind"] == "status" and item["value"] == "Ativo" for item in brief.extracted_filters), brief.extracted_filters
    assert any(item["kind"] == "location" and item["value"] == "Penedo" for item in brief.extracted_filters), brief.extracted_filters
    assert brief.likely_layers and brief.likely_layers[0].layer_name == "ligacoes_agua", brief.likely_layers

    generic_filter_brief = planner.build_brief("quantas ligacoes de esgoto ativas em penedo", schema_context)
    assert any(item["kind"] == "generic" and item["value"] == "Esgoto" for item in generic_filter_brief.extracted_filters), generic_filter_brief.extracted_filters
    assert generic_filter_brief.likely_layers and generic_filter_brief.likely_layers[0].layer_name == "ligacoes_agua", generic_filter_brief.likely_layers

    generic_group_brief = planner.build_brief("quantas ligacoes por tipo de pavimento", schema_context)
    assert generic_group_brief.group_phrase == "tipo de pavimento", generic_group_brief.group_phrase
    assert generic_group_brief.likely_layers and generic_group_brief.likely_layers[0].layer_name == "ligacoes_agua", generic_group_brief.likely_layers

    ratio_preprocessed = preprocessor.preprocess("quantos metros por ligacao em penedo")
    assert ratio_preprocessed.intent_label == "razao", ratio_preprocessed
    assert "media de extensao da rede por ligacao" in ratio_preprocessed.rewritten_text, ratio_preprocessed.rewritten_text

    generic_ratio = preprocessor.preprocess("extensao de rede dividida por quantidade de ligacoes em penedo")
    assert generic_ratio.intent_label == "razao", generic_ratio
    assert generic_ratio.composite_mode == "ratio", generic_ratio
    assert "razao entre" in generic_ratio.rewritten_text, generic_ratio.rewritten_text

    ratio_per_meter = preprocessor.preprocess("quantas ligacoes tem por metro na cidade de igreja nova")
    assert ratio_per_meter.intent_label == "razao", ratio_per_meter
    assert ratio_per_meter.composite_mode == "ratio", ratio_per_meter

    difference = preprocessor.preprocess("diferenca entre ligacoes ativas e inativas em penedo")
    assert difference.intent_label == "diferenca", difference
    assert difference.composite_mode == "difference", difference

    percentage = preprocessor.preprocess("percentual de ligacoes ativas em relacao a inativas em penedo")
    assert percentage.intent_label == "percentual", percentage
    assert percentage.composite_mode == "percentage", percentage

    comparison = preprocessor.preprocess("comparar rede de agua e rede de esgoto em penedo")
    assert comparison.intent_label == "comparacao", comparison
    assert comparison.composite_mode == "comparison", comparison

    excel_countif = preprocessor.preprocess("cont.se ligacoes ativas em penedo")
    assert excel_countif.excel_mode == "countif", excel_countif
    assert excel_countif.metric_hint == "count", excel_countif

    excel_sumif = preprocessor.preprocess("somase extensao da rede em penedo")
    assert excel_sumif.excel_mode == "sumif", excel_sumif

    excel_averageif = preprocessor.preprocess("mediase custo por bairro")
    assert excel_averageif.excel_mode == "averageif", excel_averageif

    link_result = linker.link("quantas ligacoes de esgoto ativas em penedo", schema, schema_context)
    assert link_result.layer_candidates and link_result.layer_candidates[0].layer_name == "ligacoes_agua", link_result.layer_candidates
    assert any(item.field_name == "status" for item in link_result.field_candidates[:6]), link_result.field_candidates
    assert any(normalized in {"ativo", "esgoto"} for normalized in [normalize_text(item.value) for item in link_result.value_candidates[:8]]), link_result.value_candidates

    linked_brief = planner.build_brief(
        "quantas ligacoes de esgoto ativas em penedo",
        schema_context,
        schema_link_result=link_result,
    )
    assert linked_brief.linked_layers and linked_brief.linked_layers[0].layer_name == "ligacoes_agua", linked_brief.linked_layers

    ratio_inverse = preprocessor.preprocess("ligacoes por metro em piranhas")
    assert ratio_inverse.intent_label == "razao", ratio_inverse
    assert "razao entre quantidade de ligacoes e extensao da rede" in ratio_inverse.rewritten_text, ratio_inverse.rewritten_text


def run_field_role_examples():
    resolver = FieldRoleResolver()

    dn_scores = resolver.score_field(
        field_name="dn",
        alias="diametro",
        field_kind="integer",
        geometry_type="line",
        layer_name="rede_distribuicao",
        sample_values=["150", "200"],
        top_values=["150", "100"],
    )
    assert dn_scores["diameter_field"] > dn_scores["length_field"], dn_scores

    length_scores = resolver.score_field(
        field_name="ext_m",
        alias="extensao",
        field_kind="numeric",
        geometry_type="line",
        layer_name="rede_distribuicao",
        sample_values=["25.0", "80.0"],
        top_values=["50.0"],
    )
    assert length_scores["length_field"] >= 9.0, length_scores

    municipality_scores = resolver.score_field(
        field_name="de_municipio",
        alias="municipio",
        field_kind="text",
        geometry_type="point",
        layer_name="clientes",
        sample_values=["Penedo", "Agua Branca"],
        top_values=["Penedo"],
    )
    assert municipality_scores["municipality_field"] > municipality_scores["generic_name_field"], municipality_scores

    status_scores = resolver.score_field(
        field_name="nm_situacao_ligacao_esgoto",
        alias="situacao ligacao esgoto",
        field_kind="text",
        geometry_type="point",
        layer_name="clientes",
        sample_values=["Ativa", "Cancelada"],
        top_values=["Ativa"],
    )
    assert status_scores["status_field"] >= status_scores["service_field"], status_scores


def run_layer_selection_examples():
    schema = ProjectSchema(
        layers=[
            LayerSchema(
                layer_id="l_agua",
                name="sa_redes_agua",
                geometry_type="line",
                feature_count=100,
                fields=[_field("municipio", kind="text", is_filter_candidate=True, is_location_candidate=True)],
            ),
            LayerSchema(
                layer_id="l_esgoto",
                name="se_redes_esgoto",
                geometry_type="line",
                feature_count=100,
                fields=[_field("municipio", kind="text", is_filter_candidate=True, is_location_candidate=True)],
            ),
            LayerSchema(
                layer_id="l_clientes",
                name="clientes",
                geometry_type="point",
                feature_count=100,
                fields=[_field("municipio", kind="text", is_filter_candidate=True, is_location_candidate=True)],
            ),
        ]
    )
    schema_context = SchemaContextBuilder().build(schema)
    planner = OperationPlanner()

    agua_brief = planner.build_brief("extensao de rede de agua em penedo", schema_context)
    assert agua_brief.likely_layers and agua_brief.likely_layers[0].layer_name == "sa_redes_agua", agua_brief.likely_layers

    esgoto_brief = planner.build_brief("qual extensao de rede esgoto em penedo", schema_context)
    assert esgoto_brief.likely_layers and esgoto_brief.likely_layers[0].layer_name == "se_redes_esgoto", esgoto_brief.likely_layers

    clientes_brief = planner.build_brief("quantas ligacoes de agua tem em penedo", schema_context)
    assert clientes_brief.likely_layers and clientes_brief.likely_layers[0].layer_name == "clientes", clientes_brief.likely_layers

    context_memory = ReportContextMemory()
    context_memory.remember_result(
        "extensao de rede de agua em penedo",
        QueryPlan(
            intent="value_insight",
            original_question="extensao de rede de agua em penedo",
            target_layer_id="l_agua",
            target_layer_name="sa_redes_agua",
            metric=MetricSpec(operation="length", use_geometry=True, label="Extensao"),
        ),
        QueryResult(ok=True),
    )
    followup_brief = planner.build_brief("e de esgoto?", schema_context, context_memory=context_memory)
    assert followup_brief.follow_up is True, followup_brief
    assert followup_brief.likely_layers and followup_brief.likely_layers[0].layer_name == "se_redes_esgoto", followup_brief.likely_layers


def run_conversation_examples():
    resolver = FollowupResolver()
    merger = ContextMergeEngine()
    previous_state = ConversationState(
        session_id="sess-1",
        active_query=ActiveQueryState(
            intent="aggregate_chart",
            metric="length",
            entity="rede",
            filters={"diameter": "150", "location": "Agua Branca"},
            group_by="",
            aggregation="length",
            target_field="",
            confidence=0.91,
        ),
    )

    pvc_delta = resolver.extract_delta("e de pvc?", previous_state)
    assert pvc_delta["followup_type"] == "ADD_FILTER", pvc_delta
    assert pvc_delta["add_filters"].get("material") == "PVC", pvc_delta
    pvc_question = merger.build_merged_question(previous_state, pvc_delta, "e de pvc?")
    assert "pvc" in normalize_text(pvc_question), pvc_question
    assert "agua branca" in normalize_text(pvc_question), pvc_question
    assert "150" in normalize_text(pvc_question), pvc_question

    group_delta = resolver.extract_delta("agora por bairro", previous_state)
    assert group_delta["followup_type"] == "CHANGE_GROUP", group_delta
    assert normalize_text(group_delta["group_by"]) == "bairro", group_delta

    metric_delta = resolver.extract_delta("qual o maior diametro?", previous_state)
    assert metric_delta["followup_type"] == "CHANGE_METRIC", metric_delta
    assert metric_delta["aggregation"] == "max", metric_delta
    assert metric_delta["target_field"] == "diametro", metric_delta
    assert "diameter" in metric_delta["remove_filter_kinds"], metric_delta

    reset_delta = resolver.extract_delta("agora sobre ligacoes", previous_state)
    assert reset_delta["followup_type"] == "RESET_CONTEXT", reset_delta
    assert reset_delta["reset_context"] is True, reset_delta
    assert reset_delta["entity"] == "ligacao", reset_delta


def run_ollama_fallback_examples():
    schema = build_sample_schema()
    service = OllamaFallbackService()
    raw_response = {
        "response": json.dumps(
            {
                "intent": "value_insight",
                "target_layer": "ligacoes_agua",
                "metric": {"operation": "count"},
                "filters": [
                    {
                        "field": "municipio",
                        "value": "Penedo",
                        "operator": "eq",
                        "layer_role": "target",
                        "kind": "location",
                    },
                    {
                        "field": "nm_situacao_ligacao_esgoto",
                        "value": "Ativa",
                        "operator": "eq",
                        "layer_role": "target",
                        "kind": "status",
                    },
                ],
                "confidence": 0.81,
                "needs_confirmation": False,
                "clarification_question": "",
                "rewritten_question": "quantidade das ligacoes de esgoto com status ativa em penedo",
            }
        )
    }
    parsed = service.parse_response(raw_response)
    assert parsed.get("intent") == "value_insight", parsed
    result = service.validate_response(parsed, schema, question="ligacoes de esgoto ativas em penedo")
    assert result is not None, result
    assert result.plan is not None, result
    assert result.plan.intent == "value_insight", result.plan
    assert result.plan.target_layer_name == "ligacoes_agua", result.plan
    assert len(result.plan.filters) == 2, result.plan.filters


if __name__ == "__main__":  # pragma: no cover
    run_examples()
    run_dictionary_examples()
    run_regression_examples()
    run_field_role_examples()
    run_layer_selection_examples()
    run_conversation_examples()
    run_ollama_fallback_examples()
    print("Smoke tests ok.")
