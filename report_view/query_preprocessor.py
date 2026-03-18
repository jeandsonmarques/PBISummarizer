import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Dict, List, Optional

from .text_utils import normalize_text


CANONICAL_TERMS = {
    "quantidade": ["qtd", "qtde", "quant", "quantidade", "contagem", "quantos", "quantas"],
    "extensao": ["ext", "extensao", "comprimento", "comp", "metragem", "metros", "metro", "mts", "mt"],
    "area": ["area"],
    "media": ["media"],
    "total": ["total", "somatorio", "soma"],
    "maximo": ["maximo", "maior", "ate qual", "qual o maior", "qual a maior"],
    "minimo": ["minimo", "menor", "qual o menor", "qual a menor"],
    "municipio": ["municipio", "mun", "munic", "cidade", "cid"],
    "bairro": ["bairro", "bairr", "setor"],
    "localidade": ["localidade", "local", "comunidade", "povoado"],
    "rede": ["rede", "red", "tubulacao", "tub", "ramal", "adutora"],
    "trecho": ["trecho", "trechos", "segmento", "segmentos"],
    "diametro": ["dn", "diam", "diametro", "bitola"],
    "material": ["material", "mat", "classe", "tipo"],
    "pizza": ["pizza", "setores"],
    "barra": ["barra", "barras", "coluna", "colunas"],
    "linha": ["linha", "linhas"],
    "top": ["top", "maior", "menor", "mais", "menos"],
}

RANKING_TERMS = ("maior", "menor", "mais", "menos")
COMPARISON_TERMS = ("compar", "versus", "vs", "entre")
FOLLOW_UP_TERMS = ("agora", "so", "somente", "apenas", "usa", "mostra")
LOCATION_PREFIXES = ("municipio", "cidade", "bairro", "localidade", "setor", "distrito", "comunidade", "povoado")
LOCATION_STOP_WORDS = {
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
}

REPLACEMENTS = (
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
    attribute_hint: str = ""
    value_mode: str = ""
    top_n: Optional[int] = None


class QueryPreprocessor:
    def __init__(self):
        self._vocabulary = sorted(
            {term for values in CANONICAL_TERMS.values() for term in values} | set(CANONICAL_TERMS.keys())
        )

    def preprocess(self, question: str) -> PreprocessedQuestion:
        normalized = normalize_text(question)
        corrected = self._apply_replacements(normalized)
        corrected, fuzzy = self._apply_fuzzy_corrections(corrected)
        rewritten = self._rewrite_question(corrected)
        tokens = [token for token in corrected.split() if token]
        intent_label = self._classify_intent(corrected)
        top_n = self._detect_top_n(corrected)
        metric_hint = self._metric_hint(corrected)
        subject_hint = self._subject_hint(corrected)
        group_hint = self._group_hint(corrected)
        attribute_hint = self._attribute_hint(corrected)
        value_mode = self._value_mode(corrected)
        return PreprocessedQuestion(
            original_text=question,
            normalized_text=normalized,
            corrected_text=corrected,
            rewritten_text=rewritten,
            tokens=tokens,
            fuzzy_corrections=fuzzy,
            intent_label=intent_label,
            notes=self._build_notes(corrected, fuzzy, rewritten, intent_label, attribute_hint, value_mode),
            metric_hint=metric_hint,
            subject_hint=subject_hint,
            group_hint=group_hint,
            attribute_hint=attribute_hint,
            value_mode=value_mode,
            top_n=top_n,
        )

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
        filters = self._extract_filter_phrase(text)

        if attribute == "diameter" and value_mode == "max":
            base = "qual o maior diametro da rede"
            if filters:
                base = f"{base} {filters}"
            return re.sub(r"\s+", " ", base).strip()
        if attribute == "diameter" and value_mode == "min":
            base = "qual o menor diametro da rede"
            if filters:
                base = f"{base} {filters}"
            return re.sub(r"\s+", " ", base).strip()
        if attribute in {"diameter", "material"} and value_mode == "distribution":
            attribute_text = "diametro" if attribute == "diameter" else "material"
            base = f"quantidade da rede por {attribute_text}"
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

        subject_text = {
            "rede": "da rede",
            "trecho": "dos trechos",
            "ponto": "dos pontos",
            "ligacao": "das ligacoes",
        }.get(subject, "dos dados")

        if group:
            base = f"{metric_text} {subject_text} por {group}"
        else:
            base = f"{metric_text} {subject_text}"

        if filters:
            base = f"{base} {filters}"
        return re.sub(r"\s+", " ", base).strip()

    def _classify_intent(self, text: str) -> str:
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
        if any(token in text for token in ("pvc", "pead", "material")):
            count += 1
        if self._extract_location_fragment(text):
            count += 1
        return count

    def _metric_hint(self, text: str) -> str:
        tokens = set(normalize_text(text).split())
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
        if any(token in text for token in ("rede", "tubulacao", "ramal", "adutora")):
            return "rede"
        if "trecho" in text:
            return "trecho"
        if any(token in text for token in ("ligacao", "ligacoes")):
            return "ligacao"
        if any(token in text for token in ("ponto", "pontos", "hidrante", "hidrantes")):
            return "ponto"
        return ""

    def _group_hint(self, text: str) -> str:
        if any(token in text for token in ("municipio", "cidade")):
            return "municipio"
        if "bairro" in text:
            return "bairro"
        if "localidade" in text:
            return "localidade"
        return ""

    def _attribute_hint(self, text: str) -> str:
        normalized = normalize_text(text)
        if any(token in normalized for token in ("dn", "diametro", "bitola")):
            return "diameter"
        if any(token in normalized for token in ("material", "classe", "tipo")):
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
        for material in ("pvc", "pead"):
            if re.search(rf"\b{material}\b", text):
                parts.append(f"com material {material}")
        location = self._extract_location_fragment(text)
        if location:
            parts.append(f"em {location}")
        return " ".join(parts).strip()

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
            if self._is_probable_location_fragment(candidate):
                return candidate

        if not any(token in normalized.split() for token in ("maior", "menor", "mais", "menos", "cidade", "municipio", "bairro", "localidade")):
            bare_tail = re.search(
                r"\b(?:rede|trecho|trechos|tubulacao|adutora|ramal|ramais|ligacao|ligacoes)\s+([a-z0-9][a-z0-9\s]+)$",
                normalized,
            )
            if bare_tail:
                candidate = self._clean_location_fragment(bare_tail.group(1))
                if self._is_probable_location_fragment(candidate):
                    return candidate
        return ""

    def _clean_location_fragment(self, text: str) -> str:
        cleaned = normalize_text(text)
        cleaned = re.sub(r"\b(?:dn|mm)\b", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
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
        if any(token in LOCATION_STOP_WORDS for token in tokens):
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
        return notes
