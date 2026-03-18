import re
import unicodedata
from typing import Iterable, List


def normalize_text(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    text = re.sub(r"[^a-z0-9_]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_compact(value) -> str:
    return normalize_text(value).replace(" ", "")


def tokenize_text(value) -> List[str]:
    return [token for token in normalize_text(value).replace("_", " ").split() if token]


def contains_hint_tokens(value: str, hints: Iterable[str]) -> bool:
    tokens = tokenize_text(value)
    if not tokens:
        return False
    joined = " ".join(tokens)
    for hint in hints:
        hint_tokens = tokenize_text(hint)
        if not hint_tokens:
            continue
        hint_text = " ".join(hint_tokens)
        if len(hint_tokens) == 1:
            hint_token = hint_tokens[0]
            if any(token == hint_token or token.startswith(hint_token) for token in tokens):
                return True
            continue
        if f" {hint_text} " in f" {joined} ":
            return True
    return False

