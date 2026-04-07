import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Dict, List, Optional

from .domain_packs import (
    DEFAULT_DOMAIN_PACK,
    DomainPack,
    ProjectPack,
    build_canonical_terms,
    build_project_alias_lookup,
    build_semantic_catalog,
    collect_project_terms,
)
from .text_utils import normalize_text


CANONICAL_TERMS = DEFAULT_DOMAIN_PACK.canonical_terms

RANKING_TERMS = ("maior", "menor", "mais", "menos")
COMPARISON_TERMS = ("compar", "versus", "vs", "entre")
DIFFERENCE_TERMS = ("diferenca", "diferença", "menos", "subtrair", "subtracao", "subtração")
PERCENTAGE_TERMS = ("percentual", "porcentagem", "percento", "%", "participacao", "participação")
RATIO_HINT_TERMS = ("dividido por", "dividida por", "razao entre", "relação entre", "relacao entre", "proporcao entre", "proporção entre")
RATIO_DENOMINATOR_TERMS = DEFAULT_DOMAIN_PACK.ratio_denominator_terms
GROUP_LIKE_TERMS = DEFAULT_DOMAIN_PACK.group_like_terms
FOLLOW_UP_TERMS = ("agora", "so", "somente", "apenas", "usa", "mostra")
LOCATION_PREFIXES = ("municipio", "cidade", "bairro", "localidade", "setor", "distrito", "comunidade", "povoado")
SERVICE_TERMS = DEFAULT_DOMAIN_PACK.service_terms
LOCATION_QUALIFIER_PATTERNS = (
    r"\bzona\s+urbana\s+(?:de|do|da|dos|das)\s+(.+)$",
    r"\bzona\s+rural\s+(?:de|do|da|dos|das)\s+(.+)$",
    r"\barea\s+urbana\s+(?:de|do|da|dos|das)\s+(.+)$",
    r"\barea\s+rural\s+(?:de|do|da|dos|das)\s+(.+)$",
)
LOCATION_STOP_WORDS = set(DEFAULT_DOMAIN_PACK.location_stop_words)

REPLACEMENTS = (
    (r"\bcont\.?ses?\b", "quantidade"),
    (r"\bcount\s*ifs?\b", "quantidade"),
    (r"\bsomases\b", "total"),
    (r"\bsomase\b", "total"),
    (r"\bsoma\.?ses?\b", "total"),
    (r"\bsum\s*ifs?\b", "total"),
    (r"\bmediase\b", "media"),
    (r"\bmediases\b", "media"),
    (r"\bmedia\.?ses?\b", "media"),
    (r"\baverage\s*ifs?\b", "media"),
    (r"\bparticipacao no total\b", "percentual"),
    (r"\bparticipacao\b", "percentual"),
    (r"\bshare\b", "percentual"),
    (r"\bdelta\b", "diferenca"),
    (r"\bvariacao\b", "diferenca"),
    (r"\btaxa\b", "razao"),
    (r"\bdn\s*[-/]?\s*(\d{2,4})\b", r"dn \1"),
    (r"\b(\d{2,4})\s*mm\b", r"\1 mm"),
    (r"\bdiamentro\b", "diametro"),
    (r"\bdiamtro\b", "diametro"),
    (r"\bdiametor\b", "diametro"),
    (r"\bqtd\b", "quantidade"),
    (r"\bqtde\b", "quantidade"),
    (r"\bmun\b", "municipio"),
    (r"\bmunic\b", "municipio"),
    (r"\bcid\b", "cidade"),
    (r"\bbair\b", "bairro"),
    (r"\bmetr\b", "metragem"),
    (r"\bmts\b", "metros"),
    (r"\bmt\b", "metros"),
    (r"\bcomp\b", "comprimento"),
    (r"\bext\b", "extensao"),
    (r"\bdiam\b", "diametro"),
)


@dataclass
class PreprocessedQuestion:
    original_text: str
    normalized_text: str
    corrected_text: str
    rewritten_text: str
    tokens: List[str] = field(default_factory=list)
    fuzzy_corrections: Dict[str, str] = field(default_factory=dict)
    intent_label: str = "agregacao"
    notes: List[str] = field(default_factory=list)
    metric_hint: str = ""
    subject_hint: str = ""
    group_hint: str = ""
    group_phrase: str = ""
    attribute_hint: str = ""
    value_mode: str = ""
    composite_mode: str = ""
    excel_mode: str = ""
    top_n: Optional[int] = None
    semantic_terms: List[str] = field(default_factory=list)


class QueryPreprocessor:
    def __init__(
        self,
        domain_pack: Optional[DomainPack] = None,
        project_pack: Optional[ProjectPack] = None,
    ):
        self.domain_pack = domain_pack or DEFAULT_DOMAIN_PACK
        self.project_pack = project_pack
        self.canonical_terms = build_canonical_terms(self.domain_pack, project_pack)
        self.service_terms = tuple(self.domain_pack.service_terms or ())
        self.material_terms = tuple(self.domain_pack.material_terms or ())
        self.diameter_terms = tuple(self.domain_pack.diameter_terms or ())
        self.connection_terms = tuple(self.domain_pack.connection_terms or ())
        self.length_terms = tuple(self.domain_pack.length_terms or ())
        self.ratio_denominator_terms = tuple(self.domain_pack.ratio_denominator_terms or ())
        self.subject_hints = dict(self.domain_pack.subject_hints or {})
        self.group_hints = dict(self.domain_pack.group_hints or {})
        self.location_stop_words = set(self.domain_pack.location_stop_words or ())
        self.rewrite_templates = dict(self.domain_pack.rewrite_templates or {})
        self.ratio_descriptor_overrides = dict(self.domain_pack.ratio_descriptor_overrides or {})
        self.entity_label_suffixes = dict(self.domain_pack.entity_label_suffixes or {})
        self.semantic_catalog = build_semantic_catalog(self.domain_pack, project_pack)
        self.project_value_alias_lookup = build_project_alias_lookup(
            project_pack.value_aliases if project_pack is not None else {},
        )
        self.project_terms = tuple(
            normalize_text(term)
            for term in collect_project_terms(project_pack)
            if normalize_text(term)
        )
        self._vocabulary = sorted(
            {term for values in self.canonical_terms.values() for term in values}
            | set(self.canonical_terms.keys())
            | set(self.project_terms)
        )

    def _template_text(self, key: str, default: str) -> str:
        value = str(self.rewrite_templates.get(key, "") or "").strip()
        return value or default

    def _has_any_term(self, text: str, terms) -> bool:
        padded = f" {text} "
        for term in terms:
            normalized = normalize_text(term)
            if not normalized:
                continue
            if f" {normalized} " in padded or normalized in text:
                return True
        return False

    def _has_connection_denominator(self, text: str) -> bool:
        padded = f" {text} "
        for term in self.connection_terms:
            normalized = normalize_text(term)
            if not normalized:
                continue
            if f" por {normalized} " in padded or f" para cada {normalized} " in padded or f" cada {normalized} " in padded:
                return True
        return False

    def _apply_project_value_aliases(self, text: str) -> str:
        if not self.project_value_alias_lookup:
            return text
        updated = f" {text.strip()} "
        for alias_key in sorted(self.project_value_alias_lookup.keys(), key=len, reverse=True):
            target_text = normalize_text(self.project_value_alias_lookup.get(alias_key, ""))
            if not alias_key or not target_text or alias_key == target_text:
                continue
            pattern = rf"(?<![a-z0-9_]){re.escape(alias_key)}(?![a-z0-9_])"
            updated = re.sub(pattern, target_text, updated)
        return re.sub(r"\s+", " ", updated).strip()

    def preprocess(self, question: str) -> PreprocessedQuestion:
        normalized = normalize_text(question)
        excel_mode = self._excel_mode(normalized)
        corrected = self._apply_replacements(normalized)
        corrected = self._apply_project_value_aliases(corrected)
        corrected, fuzzy = self._apply_fuzzy_corrections(corrected)
        rewritten = self._rewrite_question(corrected)
        tokens = [token for token in corrected.split() if token]
        intent_label = self._classify_intent(corrected)
        top_n = self._detect_top_n(corrected)
        metric_hint = self._metric_hint(corrected)
        subject_hint = self._subject_hint(corrected)
        group_hint = self._group_hint(corrected)
        group_phrase = self._group_phrase(corrected)
        attribute_hint = self._attribute_hint(corrected)
        value_mode = self._value_mode(corrected)
        composite_mode = self._composite_mode(corrected)
        excel_mode = excel_mode or self._excel_mode(corrected)
        semantic_terms = self._extract_semantic_terms(
            corrected,
            metric_hint=metric_hint,
            subject_hint=subject_hint,
            group_hint=group_hint,
            attribute_hint=attribute_hint,
            value_mode=value_mode,
        )
        if excel_mode and intent_label not in {"razao", "diferenca", "percentual", "comparacao"}:
            intent_label = "formula_excel"
        return PreprocessedQuestion(
            original_text=question,
            normalized_text=normalized,
            corrected_text=corrected,
            rewritten_text=rewritten,
            tokens=tokens,
            fuzzy_corrections=fuzzy,
            intent_label=intent_label,
            notes=self._build_notes(corrected, fuzzy, rewritten, intent_label, attribute_hint, value_mode, excel_mode),
            metric_hint=metric_hint,
            subject_hint=subject_hint,
            group_hint=group_hint,
            group_phrase=group_phrase,
            attribute_hint=attribute_hint,
            value_mode=value_mode,
            composite_mode=composite_mode,
            excel_mode=excel_mode,
            top_n=top_n,
            semantic_terms=semantic_terms,
        )

    def _extract_semantic_terms(
        self,
        text: str,
        metric_hint: str = "",
        subject_hint: str = "",
        group_hint: str = "",
        attribute_hint: str = "",
        value_mode: str = "",
    ) -> List[str]:
        normalized = normalize_text(text)
        semantic_terms: List[str] = []
        seen = set()

        def _add(term: str):
            normalized_term = normalize_text(term).replace(" ", "")
            if not normalized_term or normalized_term in seen:
                return
            seen.add(normalized_term)
            semantic_terms.append(term)

        metric_map = {
            "count": "metric:count",
            "length": "metric:length",
            "area": "metric:area",
            "avg": "metric:avg",
            "sum": "metric:sum",
        }
        subject_map = {
            "rede": "subject:network",
            "ligacao": "subject:connection",
            "lote": "subject:lot",
        }
        attribute_map = {
            "diameter": "attribute:diameter",
            "material": "attribute:material",
            "status": "attribute:status",
        }

        if metric_hint:
            _add(metric_map.get(metric_hint, f"metric:{metric_hint}"))
        if value_mode == "max":
            _add("metric:max")
        elif value_mode == "min":
            _add("metric:min")
        if subject_hint:
            _add(subject_map.get(subject_hint, f"subject:{subject_hint}"))
        if attribute_hint:
            _add(attribute_map.get(attribute_hint, f"attribute:{attribute_hint}"))
        if group_hint in self.group_hints:
            _add("group:location")

        for semantic_label, aliases in self.semantic_catalog.items():
            if self._has_any_term(normalized, aliases):
                _add(semantic_label)
        return semantic_terms

    def _apply_replacements(self, text: str) -> str:
        updated = text
        for pattern, replacement in REPLACEMENTS:
            updated = re.sub(pattern, replacement, updated)
        updated = re.sub(r"\s+", " ", updated).strip()
        return updated

    def _apply_fuzzy_corrections(self, text: str):
        corrections: Dict[str, str] = {}
        tokens = text.split()
        corrected_tokens = []
        for token in tokens:
            replacement = self._closest_term(token)
            if replacement and replacement != token:
                corrections[token] = replacement
                corrected_tokens.append(replacement)
            else:
                corrected_tokens.append(token)
        return " ".join(corrected_tokens), corrections

    def _closest_term(self, token: str) -> Optional[str]:
        if not token or token.isdigit() or len(token) < 4:
            return None
        if token in self._vocabulary:
            return None
        matches = get_close_matches(token, self._vocabulary, n=1, cutoff=0.86)
        if not matches:
            return None
        candidate = matches[0]
        if abs(len(candidate) - len(token)) > 3:
            return None
        return candidate

    def _rewrite_question(self, text: str) -> str:
        metric = self._metric_hint(text)
        subject = self._subject_hint(text)
        group = self._group_hint(text)
        attribute = self._attribute_hint(text)
        value_mode = self._value_mode(text)
        excel_mode = self._excel_mode(text)
        filters = self._extract_filter_phrase(text)

        if excel_mode == "countif":
            base = "quantidade dos dados"
            if group:
                base = f"{base} por {group}"
            if filters:
                base = f"{base} {filters}"
            return re.sub(r"\s+", " ", base).strip()
        if excel_mode == "sumif":
            base = "total dos dados"
            if group:
                base = f"{base} por {group}"
            if filters:
                base = f"{base} {filters}"
            return re.sub(r"\s+", " ", base).strip()
        if excel_mode == "averageif":
            base = "media dos dados"
            if group:
                base = f"{base} por {group}"
            if filters:
                base = f"{base} {filters}"
            return re.sub(r"\s+", " ", base).strip()

        if self._is_ratio_query(text):
            normalized_text = normalize_text(text)
            if self._has_any_term(normalized_text, self.connection_terms) and re.search(r"\bpor\s+(metro|metros|km|quilometro|quilometros)\b", normalized_text):
                base = self._template_text("ratio_count_per_length", "razao entre quantidade de ligacoes e extensao da rede")
                if filters:
                    base = f"{base} {filters}"
                return re.sub(r"\s+", " ", base).strip()
            if self._has_connection_denominator(normalized_text) and self._has_any_term(normalized_text, self.length_terms):
                base = self._template_text("ratio_length_per_connection", "media de extensao da rede por ligacao")
                if filters:
                    base = f"{base} {filters}"
                return re.sub(r"\s+", " ", base).strip()
            ratio_operands = self._extract_ratio_descriptors(text)
            if ratio_operands:
                base = f"razao entre {ratio_operands[0]} e {ratio_operands[1]}"
                if filters:
                    base = f"{base} {filters}"
                return re.sub(r"\s+", " ", base).strip()
            base = "razao entre numerador e denominador"
            if filters:
                base = f"{base} {filters}"
            return re.sub(r"\s+", " ", base).strip()

        if attribute == "diameter" and value_mode == "max":
            base = self._template_text("diameter_max", "qual o maior diametro da rede")
            if filters:
                base = f"{base} {filters}"
            return re.sub(r"\s+", " ", base).strip()
        if attribute == "diameter" and value_mode == "min":
            base = self._template_text("diameter_min", "qual o menor diametro da rede")
            if filters:
                base = f"{base} {filters}"
            return re.sub(r"\s+", " ", base).strip()
        if attribute in {"diameter", "material"} and value_mode == "distribution":
            template_key = "diameter_distribution" if attribute == "diameter" else "material_distribution"
            base = self._template_text(template_key, f"quantidade da rede por {'diametro' if attribute == 'diameter' else 'material'}")
            if filters:
                base = f"{base} {filters}"
            return re.sub(r"\s+", " ", base).strip()

        metric_text = {
            "length": "extensao total",
            "area": "area total",
            "count": "quantidade",
            "avg": "media",
            "sum": "total",
        }.get(metric, "valor")

        subject_text = self.entity_label_suffixes.get(subject, "dos dados")

        if group:
            base = f"{metric_text} {subject_text} por {group}"
        else:
            base = f"{metric_text} {subject_text}"

        if filters:
            base = f"{base} {filters}"
        return re.sub(r"\s+", " ", base).strip()

    def _classify_intent(self, text: str) -> str:
        if self._is_ratio_query(text):
            return "razao"
        excel_mode = self._excel_mode(text)
        if excel_mode in {"countif", "sumif", "averageif"}:
            return "formula_excel"
        composite_mode = self._composite_mode(text)
        if composite_mode == "difference":
            return "diferenca"
        if composite_mode == "percentage":
            return "percentual"
        if composite_mode == "comparison":
            return "comparacao"
        value_mode = self._value_mode(text)
        if value_mode in {"max", "min"}:
            return "valor_extremo"
        if value_mode == "distribution" and self._attribute_hint(text):
            return "distribuicao_atributo"
        if self._detect_top_n(text):
            return "top_n"
        if any(term in text for term in COMPARISON_TERMS):
            return "comparacao"
        if any(term in text.split() for term in FOLLOW_UP_TERMS):
            return "contexto"
        if any(term in text.split() for term in RANKING_TERMS):
            return "ranking"
        filters = self._count_filters(text)
        if filters >= 2:
            return "filtro_composto"
        if filters == 1:
            return "filtro_simples"
        metric = self._metric_hint(text)
        if metric == "count":
            return "contagem"
        return "agregacao"

    def _count_filters(self, text: str) -> int:
        count = 0
        if re.search(r"\bdn\s+\d{2,4}\b", text) or re.search(r"\b\d{2,4}\s*mm\b", text):
            count += 1
        material_aliases = set(self.material_terms) | set(self.canonical_terms.get("material", ()))
        if any(token in text for token in material_aliases):
            count += 1
        if self._extract_status_value(text):
            count += 1
        if self._extract_location_fragment(text):
            count += 1
        return count

    def _metric_hint(self, text: str) -> str:
        tokens = set(normalize_text(text).split())
        excel_mode = self._excel_mode(text)
        if excel_mode == "countif":
            return "count"
        if excel_mode == "sumif":
            return "sum"
        if excel_mode == "averageif":
            return "avg"
        if any(token in tokens for token in ("metragem", "metros", "metro", "comprimento", "extensao")):
            return "length"
        if "area" in tokens:
            return "area"
        if "media" in tokens:
            return "avg"
        if any(token in tokens for token in ("ligacao", "ligacoes", "lote", "lotes", "ponto", "pontos", "hidrante", "hidrantes")):
            if any(token in tokens for token in ("total", "soma", "somatorio", "quantidade", "quantos", "quantas")):
                return "count"
        if any(token in tokens for token in ("total", "soma")):
            return "sum"
        return "count"

    def _subject_hint(self, text: str) -> str:
        if any(token in text for token in self.subject_hints.get("rede", ())):
            return "rede"
        if "trecho" in text:
            return "trecho"
        if any(token in text for token in self.subject_hints.get("ligacao", ())):
            return "ligacao"
        if any(token in text for token in ("ponto", "pontos", "hidrante", "hidrantes")):
            return "ponto"
        return ""

    def _group_hint(self, text: str) -> str:
        for canonical, aliases in self.group_hints.items():
            if any(token in text for token in aliases):
                return canonical
        return ""

    def _group_phrase(self, text: str) -> str:
        normalized = normalize_text(text)
        if not normalized or self._is_ratio_query(normalized):
            return ""
        parts = normalized.split(" por ", 1)
        if len(parts) < 2:
            return ""
        phrase = normalize_text(parts[1])
        phrase = re.sub(r"\b(?:em|no|na)\s+[a-z0-9][a-z0-9\s]+$", "", phrase).strip()
        phrase = re.sub(r"\b(?:com|onde|top|pizza|barra|linha|grafico)\b.*$", "", phrase).strip()
        return re.sub(r"\s+", " ", phrase).strip()

    def _attribute_hint(self, text: str) -> str:
        normalized = normalize_text(text)
        if any(token in normalized for token in self.diameter_terms):
            return "diameter"
        if any(token in normalized for token in self.canonical_terms.get("material", ())):
            return "material"
        return ""

    def _value_mode(self, text: str) -> str:
        normalized = normalize_text(text)
        attribute = self._attribute_hint(normalized)
        if not attribute:
            return ""

        if re.search(r"\b(?:ate qual|qual o maior|qual a maior|maior|maximo|maxima)\b", normalized):
            return "max"
        if re.search(r"\b(?:qual o menor|qual a menor|menor|minimo|minima)\b", normalized):
            return "min"
        if re.search(r"\b(?:quais|listar|lista|mostra|mostrar|distribuicao|distribuicao de)\b", normalized):
            return "distribution"
        if attribute == "diameter" and re.search(r"\bdiametro\b", normalized) and " por " not in normalized:
            return "distribution"
        if attribute == "material" and re.search(r"\bmaterial\b", normalized) and " por " not in normalized:
            return "distribution"
        return ""

    def _detect_top_n(self, text: str) -> Optional[int]:
        match = re.search(r"\btop\s+(\d+)\b", text)
        if match:
            try:
                return max(1, int(match.group(1)))
            except Exception:
                return None
        if self._looks_like_top_one_question(text):
            return 1
        return None

    def _extract_filter_phrase(self, text: str) -> str:
        parts = []
        dn_match = re.search(r"\bdn\s+(\d{2,4})\b", text)
        if dn_match:
            parts.append(f"com dn {dn_match.group(1)}")
        mm_match = re.search(r"\b(\d{2,4})\s*mm\b", text)
        if mm_match and not dn_match:
            parts.append(f"com dn {mm_match.group(1)}")
        for material in self.material_terms:
            if re.search(rf"\b{material}\b", text):
                parts.append(f"com material {material}")
        service_value = self._extract_service_value(text)
        if service_value:
            parts.append(f"de {service_value}")
        status_value = self._extract_status_value(text)
        if status_value:
            parts.append(f"com status {status_value}")
        location = self._extract_location_fragment(text)
        if location:
            parts.append(f"em {location}")
        return " ".join(parts).strip()

    def _extract_service_value(self, text: str) -> str:
        normalized = normalize_text(text)
        for service_term in self.service_terms:
            if re.search(rf"\b{re.escape(service_term)}\b", normalized):
                return service_term
        return ""

    def _extract_status_value(self, text: str) -> str:
        normalized = normalize_text(text)
        if re.search(r"\bativ[ao]s?\b", normalized):
            return "ativo"
        if re.search(r"\binativ[ao]s?\b", normalized):
            return "inativo"
        if re.search(r"\bcancelad[ao]s?\b", normalized):
            return "cancelado"
        if re.search(r"\bsuspens[ao]s?\b", normalized):
            return "suspenso"
        return ""

    def _excel_mode(self, text: str) -> str:
        normalized = normalize_text(text)
        if any(token in normalized for token in ("countif", "countifs", "cont se", "contse", "contses")):
            return "countif"
        if any(token in normalized for token in ("sumif", "sumifs", "somase", "somases", "soma se")):
            return "sumif"
        if any(token in normalized for token in ("averageif", "averageifs", "mediase", "mediases", "media se")):
            return "averageif"
        return ""

    def _is_ratio_query(self, text: str) -> bool:
        normalized = normalize_text(text)
        if not normalized:
            return False
        ratio_metric_terms = {"quantidade", "total", "soma", "somatorio", "media", "area"} | set(self.length_terms)
        if any(term in normalized for term in RATIO_HINT_TERMS) or "share" in normalized or "taxa" in normalized:
            return True
        if re.search(r"\b(?:por|para cada)\s+(metro|metros|km|quilometro|quilometros)\b", normalized):
            return True
        if re.search(r"\b(?:por|para cada)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+){0,2})", normalized):
            denominator = re.search(r"\b(?:por|para cada)\s+([a-z0-9_]+(?:\s+[a-z0-9_]+){0,2})", normalized)
            if denominator:
                denominator_text = normalize_text(denominator.group(1))
                denominator_tokens = [token for token in denominator_text.split() if token]
                if denominator_tokens:
                    first_token = denominator_tokens[0]
                    if first_token in self.ratio_denominator_terms and first_token not in GROUP_LIKE_TERMS:
                        if any(token in normalized.split() for token in ratio_metric_terms):
                            return True
        if self._has_connection_denominator(normalized):
            return True
        return False

    def _extract_ratio_descriptors(self, text: str):
        normalized = normalize_text(text)
        if self._has_any_term(normalized, self.connection_terms) and re.search(r"\bpor\s+(metro|metros|km|quilometro|quilometros)\b", normalized):
            return self.ratio_descriptor_overrides.get("count_per_length", ("quantidade de ligacoes", "extensao da rede"))
        if self._has_any_term(normalized, self.length_terms) and self._has_connection_denominator(normalized):
            return self.ratio_descriptor_overrides.get("length_per_count", ("extensao da rede", "quantidade de ligacoes"))
        patterns = (
            r"\b(.+?)\s+dividid[oa]\s+por\s+(.+)$",
            r"\b(?:razao|relacao|relação|proporcao|proporção)\s+entre\s+(.+?)\s+e\s+(.+)$",
            r"\b(.+?)\s+para cada\s+(.+)$",
        )
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if not match:
                continue
            left = self._clean_ratio_descriptor(match.group(1))
            right = self._clean_ratio_descriptor(match.group(2))
            if left and right:
                return left, right
        match = re.search(r"\b(.+?)\s+por\s+(.+)$", normalized)
        if not match:
            return ()
        right = self._clean_ratio_descriptor(match.group(2))
        if not right:
            return ()
        right_tokens = right.split()
        if not right_tokens or right_tokens[0] in GROUP_LIKE_TERMS:
            return ()
        if right_tokens[0] not in self.ratio_denominator_terms:
            return ()
        left = self._clean_ratio_descriptor(match.group(1))
        if left and right:
            return left, right
        return ()

    def _clean_ratio_descriptor(self, text: str) -> str:
        cleaned = normalize_text(text)
        cleaned = re.sub(r"\b(?:razao|relacao|relação|proporcao|proporção|dividid[oa]|por|entre|e|de|do|da)\b", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _composite_mode(self, text: str) -> str:
        normalized = normalize_text(text)
        if self._is_ratio_query(normalized):
            return "ratio"
        if any(term in normalized for term in PERCENTAGE_TERMS):
            return "percentage"
        if any(term in normalized for term in DIFFERENCE_TERMS):
            return "difference"
        if any(term in normalized for term in COMPARISON_TERMS):
            return "comparison"
        if re.search(r"\b(?:vs|versus)\b", normalized):
            return "comparison"
        if re.search(r"\bentre\s+.+\s+e\s+.+", normalized):
            return "comparison"
        return ""

    def _looks_like_top_one_question(self, text: str) -> bool:
        normalized = normalize_text(text)
        if not normalized:
            return False
        if not any(term in normalized.split() for term in RANKING_TERMS):
            return False
        if normalized.startswith(("qual ", "quais ", "quem ", "cidade ", "municipio ", "bairro ")):
            return True
        return bool(re.search(r"\b(?:cidade|municipio|bairro|localidade)\s+com\s+(?:maior|menor)\b", normalized))

    def _extract_location_fragment(self, text: str) -> str:
        normalized = normalize_text(text)
        if not normalized:
            return ""

        patterns = (
            r"\b(?:em|no|na)\s+([a-z0-9][a-z0-9\s]+?)(?=$|\b(?:com|onde|top|pizza|barra|linha|grafico)\b)",
            r"\b(?:municipio|cidade|bairro|localidade|setor|distrito|comunidade|povoado)\s+(?!(?:com|tem|possui|maior|mais|menor|menos)\b)(?:de|do|da)?\s*([a-z0-9][a-z0-9\s]+?)(?=$|\b(?:com|onde|top|pizza|barra|linha|grafico)\b)",
            r"^([a-z0-9][a-z0-9\s]+?)\s+(?:tem|possui)\s+(?:rede|trecho|trechos|tubulacao|adutora|ramal)\b",
        )
        for pattern in patterns:
            matches = list(re.finditer(pattern, normalized))
            if not matches:
                continue
            candidate = self._clean_location_fragment(matches[-1].group(1))
            candidate = self._strip_location_qualifiers(candidate)
            if self._is_probable_location_fragment(candidate):
                return candidate

        if not any(token in normalized.split() for token in ("maior", "menor", "mais", "menos", "cidade", "municipio", "bairro", "localidade")):
            bare_tail = re.search(
                r"\b(?:rede|trecho|trechos|tubulacao|adutora|ramal|ramais|ligacao|ligacoes)\s+([a-z0-9][a-z0-9\s]+)$",
                normalized,
            )
            if bare_tail:
                candidate = self._clean_location_fragment(bare_tail.group(1))
                candidate = self._strip_location_qualifiers(candidate)
                if self._is_probable_location_fragment(candidate):
                    return candidate
        return ""

    def _clean_location_fragment(self, text: str) -> str:
        cleaned = normalize_text(text)
        cleaned = re.sub(r"\b(?:dn|mm)\b", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _strip_location_qualifiers(self, text: str) -> str:
        cleaned = normalize_text(text)
        if not cleaned:
            return ""
        for pattern in LOCATION_QUALIFIER_PATTERNS:
            match = re.search(pattern, cleaned)
            if match:
                return re.sub(r"\s+", " ", match.group(1)).strip()
        return cleaned

    def _is_probable_location_fragment(self, text: str) -> bool:
        normalized = normalize_text(text)
        if not normalized:
            return False
        tokens = [token for token in normalized.split() if token]
        if not tokens or len(tokens) > 4:
            return False
        if any(token.isdigit() for token in tokens):
            return False
        if any(token in self.location_stop_words for token in tokens):
            return False
        if tokens[0] in {"de", "do", "da", "em", "no", "na", "por"}:
            return False
        if normalized in LOCATION_PREFIXES:
            return False
        return True

    def _build_notes(
        self,
        corrected_text: str,
        fuzzy_corrections: Dict[str, str],
        rewritten_text: str,
        intent_label: str,
        attribute_hint: str,
        value_mode: str,
        excel_mode: str = "",
    ) -> List[str]:
        notes = [f"intencao={intent_label}"]
        if fuzzy_corrections:
            notes.append(f"correcoes={fuzzy_corrections}")
        if rewritten_text and rewritten_text != corrected_text:
            notes.append(f"reescrita={rewritten_text}")
        if attribute_hint:
            notes.append(f"atributo={attribute_hint}")
        if value_mode:
            notes.append(f"modo={value_mode}")
        composite_mode = self._composite_mode(corrected_text)
        if composite_mode:
            notes.append(f"composto={composite_mode}")
        if excel_mode:
            notes.append(f"excel={excel_mode}")
        return notes
