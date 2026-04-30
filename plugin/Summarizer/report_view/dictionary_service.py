import csv
from pathlib import Path
from typing import Dict, Optional

from .report_logging import log_info, log_warning
from .text_utils import normalize_text


DEFAULT_DICTIONARY_PATH = None

_PAYLOAD_CACHE: Dict[str, Dict] = {}


class DictionaryService:
    def __init__(self, csv_path: Optional[str] = None):
        self.csv_path = Path(csv_path) if csv_path else DEFAULT_DICTIONARY_PATH
        self._loaded = False
        self._alias_by_size: Dict[int, Dict[str, Dict]] = {}
        self._max_alias_tokens = 1
        self._entry_count = 0

    def loadDictionary(self, force_reload: bool = False):
        if self.csv_path is None:
            self._alias_by_size = {}
            self._max_alias_tokens = 1
            self._entry_count = 0
            self._loaded = True
            return self

        cache_key = str(self.csv_path.resolve())
        if not force_reload and cache_key in _PAYLOAD_CACHE:
            payload = _PAYLOAD_CACHE[cache_key]
            self._alias_by_size = payload["alias_by_size"]
            self._max_alias_tokens = payload["max_alias_tokens"]
            self._entry_count = payload["entry_count"]
            self._loaded = True
            return self

        if not self.csv_path.exists():
            log_warning(f"[Relatorios] dicionario semantico nao encontrado em '{self.csv_path}'")
            self._alias_by_size = {}
            self._max_alias_tokens = 1
            self._entry_count = 0
            self._loaded = True
            return self

        alias_by_size: Dict[int, Dict[str, Dict]] = {}
        entry_count = 0
        try:
            with self.csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    alias = (row.get("normalized_alias") or row.get("alias_term") or "").strip()
                    canonical = (row.get("normalized_canonical") or row.get("canonical_term") or "").strip()
                    if not alias or not canonical:
                        continue
                    alias = normalize_text(alias)
                    canonical = normalize_text(canonical)
                    if not alias or not canonical:
                        continue
                    try:
                        weight = float(row.get("weight") or 0.0)
                    except Exception:
                        weight = 0.0
                    size = max(1, len(alias.split()))
                    bucket = alias_by_size.setdefault(size, {})
                    current = bucket.get(alias)
                    if current is None or weight > float(current.get("weight") or 0.0):
                        bucket[alias] = {
                            "canonical": canonical,
                            "weight": weight,
                            "category": (row.get("category") or "").strip(),
                            "subcategory": (row.get("subcategory") or "").strip(),
                            "domain": (row.get("domain") or "").strip(),
                            "alias_type": (row.get("alias_type") or "").strip(),
                        }
                        entry_count += 1
        except Exception as exc:
            log_warning(f"[Relatorios] falha ao carregar dicionario semantico: {exc}")
            alias_by_size = {}
            entry_count = 0

        self._alias_by_size = alias_by_size
        self._max_alias_tokens = max(alias_by_size.keys(), default=1)
        self._entry_count = entry_count
        self._loaded = True
        _PAYLOAD_CACHE[cache_key] = {
            "alias_by_size": self._alias_by_size,
            "max_alias_tokens": self._max_alias_tokens,
            "entry_count": self._entry_count,
        }
        log_info(
            "[Relatorios] dicionario semantico "
            f"path='{self.csv_path.name}' entradas={self._entry_count} max_tokens={self._max_alias_tokens}"
        )
        return self

    def normalizeText(self, text: str) -> str:
        return normalize_text(text)

    def replaceAliases(self, text: str) -> str:
        if not self._loaded:
            self.loadDictionary()
        normalized = self.normalizeText(text)
        if not normalized or not self._alias_by_size:
            return normalized

        tokens = normalized.split()
        replaced = []
        index = 0
        total = len(tokens)
        while index < total:
            matched = False
            max_size = min(self._max_alias_tokens, total - index)
            for size in range(max_size, 0, -1):
                bucket = self._alias_by_size.get(size)
                if not bucket:
                    continue
                phrase = " ".join(tokens[index : index + size])
                entry = bucket.get(phrase)
                if entry is None:
                    continue
                replaced.extend(str(entry["canonical"]).split())
                index += size
                matched = True
                break
            if matched:
                continue
            replaced.append(tokens[index])
            index += 1
        return " ".join(replaced).strip()

    def normalize_query(self, text: str) -> str:
        current = self.normalizeText(text)
        if not current:
            return ""
        for _ in range(2):
            updated = self.replaceAliases(current)
            updated = self.normalizeText(updated)
            if updated == current:
                break
            current = updated
        return current

    @property
    def entry_count(self) -> int:
        if not self._loaded:
            self.loadDictionary()
        return self._entry_count


def build_dictionary_service(csv_path: Optional[str] = None) -> DictionaryService:
    service = DictionaryService(csv_path=csv_path)
    service.loadDictionary()
    return service
