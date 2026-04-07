from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence, Tuple

from .text_utils import normalize_text


def _tuple(values: Sequence[str]) -> Tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


def _tuple_map(values: Mapping[str, Sequence[str]]) -> Dict[str, Tuple[str, ...]]:
    return {str(key).strip(): _tuple(items) for key, items in values.items() if str(key).strip()}


def _merge_unique(base: Sequence[str], extra: Sequence[str]) -> Tuple[str, ...]:
    merged = list(base)
    for item in extra:
        if item not in merged:
            merged.append(item)
    return tuple(merged)


def _normalized(value: str) -> str:
    return normalize_text(str(value or "").strip())


def _flatten_tuple_map(values: Mapping[str, Sequence[str]]) -> Tuple[str, ...]:
    flattened: Tuple[str, ...] = ()
    for items in (values or {}).values():
        flattened = _merge_unique(flattened, _tuple(items or ()))
    return flattened


@dataclass(frozen=True)
class DomainPack:
    name: str
    canonical_terms: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    service_terms: Tuple[str, ...] = ()
    material_terms: Tuple[str, ...] = ()
    status_terms: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    water_terms: Tuple[str, ...] = ()
    sewer_terms: Tuple[str, ...] = ()
    network_terms: Tuple[str, ...] = ()
    connection_terms: Tuple[str, ...] = ()
    location_terms: Tuple[str, ...] = ()
    length_terms: Tuple[str, ...] = ()
    diameter_terms: Tuple[str, ...] = ()
    group_hints: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    subject_hints: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    group_like_terms: Tuple[str, ...] = ()
    location_reject_tokens: Tuple[str, ...] = ()
    location_stop_words: Tuple[str, ...] = ()
    engineering_layer_hints: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    location_field_hints: Tuple[str, ...] = ()
    filter_field_hints: Tuple[str, ...] = ()
    status_field_hints: Tuple[str, ...] = ()
    engineering_value_hints: Tuple[str, ...] = ()
    service_field_family_hints: Tuple[str, ...] = ()
    generic_service_field_hints: Tuple[str, ...] = ()
    generic_semantic_terms: Tuple[str, ...] = ()
    entity_priority_terms: Tuple[str, ...] = ()
    ratio_denominator_terms: Tuple[str, ...] = ()
    ratio_target_terms: Tuple[str, ...] = ()
    ratio_source_terms: Tuple[str, ...] = ()
    ratio_target_geometry_types: Tuple[str, ...] = ()
    ratio_source_geometry_types: Tuple[str, ...] = ()
    rewrite_templates: Dict[str, str] = field(default_factory=dict)
    ratio_descriptor_overrides: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    entity_label_suffixes: Dict[str, str] = field(default_factory=dict)
    semantic_metric_labels: Dict[str, str] = field(default_factory=dict)
    value_insight_labels: Dict[str, str] = field(default_factory=dict)
    derived_intent_labels: Dict[str, str] = field(default_factory=dict)
    ratio_messages: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectPack:
    canonical_terms: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    layer_aliases: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    field_aliases: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    value_aliases: Dict[str, Tuple[str, ...]] = field(default_factory=dict)


def build_canonical_terms(
    domain_pack: DomainPack,
    project_pack: Optional[ProjectPack] = None,
) -> Dict[str, Tuple[str, ...]]:
    merged = {key: tuple(values) for key, values in (domain_pack.canonical_terms or {}).items()}
    if project_pack is None:
        return merged
    for key, values in (project_pack.canonical_terms or {}).items():
        merged[key] = _merge_unique(merged.get(key, ()), values)
    return merged


def build_semantic_catalog(
    domain_pack: DomainPack,
    project_pack: Optional[ProjectPack] = None,
) -> Dict[str, Tuple[str, ...]]:
    canonical_terms = build_canonical_terms(domain_pack, project_pack)
    location_group_terms = _flatten_tuple_map(domain_pack.group_hints or {})
    status_terms = _flatten_tuple_map(domain_pack.status_terms or {})
    subject_lot_terms = tuple((domain_pack.subject_hints or {}).get("lote", ()))
    return {
        "metric:count": _merge_unique(canonical_terms.get("quantidade", ()), canonical_terms.get("contagem_excel", ())),
        "metric:length": _merge_unique(domain_pack.length_terms, canonical_terms.get("extensao", ())),
        "metric:area": canonical_terms.get("area", ()),
        "metric:avg": _merge_unique(canonical_terms.get("media", ()), canonical_terms.get("media_excel", ())),
        "metric:sum": _merge_unique(canonical_terms.get("total", ()), canonical_terms.get("soma_excel", ())),
        "metric:max": canonical_terms.get("maximo", ()),
        "metric:min": canonical_terms.get("minimo", ()),
        "subject:network": domain_pack.network_terms,
        "subject:connection": domain_pack.connection_terms,
        "subject:lot": subject_lot_terms,
        "attribute:diameter": _merge_unique(domain_pack.diameter_terms, canonical_terms.get("diametro", ())),
        "attribute:material": _merge_unique(domain_pack.material_terms, canonical_terms.get("material", ())),
        "attribute:status": _merge_unique(status_terms, canonical_terms.get("status", ())),
        "group:location": _merge_unique(domain_pack.location_terms, location_group_terms),
        "context:water": domain_pack.water_terms,
        "context:sewer": domain_pack.sewer_terms,
        "context:service": domain_pack.service_terms,
    }


def build_project_alias_lookup(
    alias_map: Optional[Mapping[str, Sequence[str]]],
    include_targets: bool = False,
) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for target, aliases in (alias_map or {}).items():
        target_text = str(target).strip()
        target_key = _normalized(target_text)
        if include_targets and target_key:
            lookup.setdefault(target_key, target_text)
        for alias in aliases or ():
            alias_text = str(alias).strip()
            alias_key = _normalized(alias_text)
            if alias_key:
                lookup[alias_key] = target_text
    return lookup


def aliases_for_target(
    alias_map: Optional[Mapping[str, Sequence[str]]],
    target: str,
) -> Tuple[str, ...]:
    target_key = _normalized(target)
    if not target_key:
        return ()
    for candidate, aliases in (alias_map or {}).items():
        if _normalized(candidate) == target_key:
            return _tuple(aliases or ())
    return ()


def collect_project_terms(project_pack: Optional[ProjectPack]) -> Tuple[str, ...]:
    if project_pack is None:
        return ()
    terms = []
    for mapping in (
        project_pack.layer_aliases,
        project_pack.field_aliases,
        project_pack.value_aliases,
    ):
        for target, aliases in (mapping or {}).items():
            for alias in aliases or ():
                alias_text = str(alias).strip()
                if alias_text:
                    terms.append(alias_text)
    return _merge_unique((), terms)


def project_pack_signature(project_pack: Optional[ProjectPack]) -> Tuple:
    if project_pack is None:
        return ()

    def _mapping_signature(values: Mapping[str, Sequence[str]]) -> Tuple:
        items = []
        for key, aliases in (values or {}).items():
            key_norm = _normalized(key)
            if not key_norm:
                continue
            alias_signature = tuple(
                sorted(
                    alias_norm
                    for alias_norm in (_normalized(alias) for alias in aliases or ())
                    if alias_norm
                )
            )
            items.append((key_norm, alias_signature))
        return tuple(sorted(items))

    return (
        _mapping_signature(project_pack.canonical_terms),
        _mapping_signature(project_pack.layer_aliases),
        _mapping_signature(project_pack.field_aliases),
        _mapping_signature(project_pack.value_aliases),
    )


SANITATION_DOMAIN_PACK = DomainPack(
    name="sanitation",
    canonical_terms=_tuple_map(
        {
            "quantidade": ("qtd", "qtde", "quant", "quantidade", "contagem", "quantos", "quantas"),
            "extensao": ("ext", "extensao", "comprimento", "comp", "metragem", "metros", "metro", "mts", "mt"),
            "area": ("area",),
            "media": ("media",),
            "total": ("total", "somatorio", "soma"),
            "contagem_excel": ("contse", "cont se", "cont.ses", "contses", "countif", "countifs", "count if", "count ifs"),
            "soma_excel": ("somase", "soma se", "somases", "sumif", "sumifs", "sum if", "sum ifs"),
            "media_excel": ("mediase", "media se", "mediases", "averageif", "averageifs", "average if", "average ifs"),
            "maximo": ("maximo", "maior", "ate qual", "qual o maior", "qual a maior"),
            "minimo": ("minimo", "menor", "qual o menor", "qual a menor"),
            "municipio": ("municipio", "mun", "munic", "cidade", "cid"),
            "bairro": ("bairro", "bairr", "setor"),
            "localidade": ("localidade", "local", "comunidade", "povoado"),
            "rede": ("rede", "red", "tubulacao", "tub", "ramal", "adutora"),
            "trecho": ("trecho", "trechos", "segmento", "segmentos"),
            "diametro": ("dn", "diam", "diametro", "bitola"),
            "material": ("material", "mat", "classe", "tipo"),
            "status": (
                "status",
                "situacao",
                "sit",
                "ativo",
                "ativa",
                "ativos",
                "ativas",
                "inativo",
                "inativa",
                "inativos",
                "inativas",
                "cancelado",
                "cancelada",
                "cancelados",
                "canceladas",
                "suspenso",
                "suspensa",
            ),
            "pizza": ("pizza", "setores"),
            "barra": ("barra", "barras", "coluna", "colunas"),
            "linha": ("linha", "linhas"),
            "top": ("top", "maior", "menor", "mais", "menos"),
        }
    ),
    service_terms=_tuple(("agua", "esgoto", "drenagem", "pluvial", "sanitario")),
    material_terms=_tuple(("pvc", "pead", "pba", "fofo", "ferro", "aco", "fibrocimento")),
    status_terms=_tuple_map(
        {
            "ativo": ("ativo", "ativa", "ativos", "ativas"),
            "inativo": ("inativo", "inativa", "inativos", "inativas"),
            "cancelado": ("cancelado", "cancelada", "cancelados", "canceladas"),
            "suspenso": ("suspenso", "suspensa", "suspensos", "suspensas"),
        }
    ),
    water_terms=_tuple(("agua", "abastecimento")),
    sewer_terms=_tuple(("esgoto", "esgotos", "sanitario", "sanitaria", "sewer", "coletor", "coletores")),
    network_terms=_tuple(("rede", "redes", "adutora", "adutoras", "ramal", "ramais", "tubulacao", "tubulacoes", "trecho", "trechos")),
    connection_terms=_tuple(("ligacao", "ligacoes", "cliente", "clientes", "economia", "economias", "usuario", "usuarios", "unidade", "unidades")),
    location_terms=_tuple(("municipio", "cidade", "bairro", "localidade", "setor", "distrito", "comunidade", "logradouro", "povoado")),
    length_terms=_tuple(("extensao", "comprimento", "metragem", "metro", "metros", "quilometro", "quilometros", "km")),
    diameter_terms=_tuple(("dn", "diametro", "diam", "bitola")),
    group_hints=_tuple_map(
        {
            "municipio": ("municipio", "cidade"),
            "bairro": ("bairro", "setor"),
            "localidade": ("localidade", "comunidade", "povoado"),
        }
    ),
    subject_hints=_tuple_map(
        {
            "rede": ("rede", "adutora", "ramal", "tubulacao", "trecho"),
            "ligacao": ("ligacao", "ligacoes", "ponto", "pontos"),
            "lote": ("lote", "lotes", "parcela", "parcelas"),
        }
    ),
    group_like_terms=_tuple(("municipio", "cidade", "bairro", "localidade", "setor", "distrito", "comunidade", "povoado", "material", "diametro", "dn", "tipo", "classe")),
    location_reject_tokens=_tuple(
        (
            "adutora",
            "adutoras",
            "area",
            "bairro",
            "barra",
            "bitola",
            "cidade",
            "cidades",
            "com",
            "comprimento",
            "diametro",
            "dn",
            "essa",
            "esse",
            "isso",
            "isto",
            "extensao",
            "grafico",
            "linha",
            "mais",
            "maior",
            "material",
            "media",
            "menor",
            "menos",
            "metragem",
            "metro",
            "metros",
            "mm",
            "municipio",
            "municipios",
            "pizza",
            "por",
            "possui",
            "quantidade",
            "quantos",
            "quantas",
            "que",
            "qual",
            "quais",
            "ramal",
            "ramais",
            "rede",
            "redes",
            "setor",
            "agua",
            "esgoto",
            "camada",
            "tem",
            "top",
            "trecho",
            "trechos",
            "tubulacao",
            "usa",
        )
    ),
    location_stop_words=_tuple(
        (
            "adutora",
            "adutoras",
            "area",
            "bairro",
            "barra",
            "bitola",
            "cidade",
            "cidades",
            "com",
            "comprimento",
            "diametro",
            "dn",
            "essa",
            "esse",
            "isso",
            "isto",
            "extensao",
            "grafico",
            "linha",
            "mais",
            "maior",
            "material",
            "media",
            "menor",
            "menos",
            "metragem",
            "metro",
            "metros",
            "mm",
            "municipio",
            "municipios",
            "pizza",
            "por",
            "possui",
            "quantidade",
            "quantos",
            "quantas",
            "que",
            "qual",
            "quais",
            "ramal",
            "ramais",
            "rede",
            "redes",
            "setor",
            "tem",
            "top",
            "trecho",
            "trechos",
            "tubulacao",
            "usa",
        )
    ),
    engineering_layer_hints=_tuple_map(
        {
            "line": ("rede", "redes", "trecho", "trechos", "tubulacao", "tubulacoes", "adutora", "adutoras", "ramal", "ramais"),
            "point": ("ponto", "pontos", "hidrante", "hidrantes", "valvula", "valvulas", "ligacao", "ligacoes", "cliente", "clientes", "economia", "economias"),
            "polygon": ("bairro", "bairros", "municipio", "municipios", "cidade", "cidades", "setor", "setores", "localidade", "localidades"),
        }
    ),
    location_field_hints=_tuple(("municipio", "cidade", "bairro", "localidade", "distrito", "setor", "logradouro", "comunidade", "povoado")),
    filter_field_hints=_tuple(("dn", "diametro", "diam", "bitola", "material", "classe", "tipo", "categoria", "municipio", "cidade", "bairro", "localidade", "setor", "status", "situacao", "sit")),
    status_field_hints=_tuple(("status", "situacao", "sit")),
    engineering_value_hints=_tuple(("pvc", "pead", "fofo", "ferro", "aco", "dn", "mm")),
    service_field_family_hints=_tuple(("ligacao", "rede", "servico", "abastecimento", "coleta")),
    generic_service_field_hints=_tuple(("servico", "sistema", "rede", "ligacao", "tipo_servico")),
    generic_semantic_terms=_tuple(("agua", "esgoto", "drenagem", "pluvial", "sanitario", "ativo", "inativo", "cancelado", "suspenso")),
    entity_priority_terms=_tuple(("rede", "ligacao", "lote", "bairro", "municipio")),
    ratio_denominator_terms=_tuple(
        (
            "metro",
            "metros",
            "km",
            "quilometro",
            "quilometros",
            "ligacao",
            "ligacoes",
            "cliente",
            "clientes",
            "economia",
            "economias",
            "ponto",
            "pontos",
            "hidrante",
            "hidrantes",
            "ramal",
            "ramais",
            "trecho",
            "trechos",
            "rede",
            "redes",
            "lote",
            "lotes",
            "parcela",
            "parcelas",
            "imovel",
            "imoveis",
        )
    ),
    ratio_target_terms=_tuple(("rede", "redes", "adutora", "adutoras", "ramal", "ramais", "tubulacao", "tubulacoes", "trecho", "trechos")),
    ratio_source_terms=_tuple(("ligacao", "ligacoes", "cliente", "clientes", "economia", "economias", "usuario", "usuarios", "unidade", "unidades")),
    ratio_target_geometry_types=_tuple(("line",)),
    ratio_source_geometry_types=_tuple(("point",)),
    rewrite_templates={
        "ratio_count_per_length": "razao entre quantidade de ligacoes e extensao da rede",
        "ratio_length_per_connection": "media de extensao da rede por ligacao",
        "diameter_max": "qual o maior diametro da rede",
        "diameter_min": "qual o menor diametro da rede",
        "diameter_distribution": "quantidade da rede por diametro",
        "material_distribution": "quantidade da rede por material",
    },
    ratio_descriptor_overrides={
        "count_per_length": ("quantidade de ligacoes", "extensao da rede"),
        "length_per_count": ("extensao da rede", "quantidade de ligacoes"),
    },
    entity_label_suffixes={
        "rede": "da rede",
        "trecho": "dos trechos",
        "ponto": "dos pontos",
        "ligacao": "das ligacoes",
        "lote": "dos lotes",
    },
    semantic_metric_labels={
        "count": "Quantidade",
        "sum": "Total",
        "avg": "Media",
        "length": "Extensao total",
        "area": "Area total",
        "max": "Maior valor",
        "min": "Menor valor",
        "ratio": "Metros por ligacao",
        "difference": "Diferenca",
        "percentage": "Percentual",
        "comparison": "Comparacao",
    },
    value_insight_labels={
        "diameter": "o maior diametro",
        "material": "o material",
    },
    derived_intent_labels={
        "ratio_metric": "Metros por ligacao",
        "ratio_label": "Metros por ligacao da rede",
        "ratio_summary": "A extensao media da rede por ligacao",
        "ratio_entity": "da rede por ligacao",
        "ratio_human_metric": "a extensao media por ligacao",
        "ratio_chart_title": "Metros por ligacao",
        "ratio_confirmation_template": "Voce quis dizer a extensao media da rede por ligacao, usando {target_layer} dividido por {source_layer}?",
    },
    ratio_messages={
        "missing_layers": "Nao consegui encontrar uma camada de rede e uma camada de ligacoes para calcular essa media.",
        "build_failed": "Nao consegui montar uma consulta segura de metros por ligacao com as camadas abertas.",
        "ambiguous": "Encontrei mais de uma forma plausivel de calcular metros por ligacao.",
    },
)


DEFAULT_DOMAIN_PACK = SANITATION_DOMAIN_PACK
