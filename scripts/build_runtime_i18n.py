import ast
import json
import pathlib
import re
from typing import Dict, Set

from deep_translator import GoogleTranslator


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / "plugin" / "power_bi_summarizer"
I18N_DIR = PLUGIN_DIR / "i18n"
RUNTIME_EN_PATH = I18N_DIR / "runtime_en.json"
RUNTIME_ES_PATH = I18N_DIR / "runtime_es.json"


WHITELIST_ATTR = {
    "setText",
    "setToolTip",
    "setPlaceholderText",
    "setWindowTitle",
    "setTitle",
    "setStatusTip",
    "setWhatsThis",
    "addAction",
    "addMenu",
    "setTabText",
    "setHeaderLabel",
    "setLabelText",
    "setHtml",
    "setPlainText",
    "addItem",
    "insertItem",
}
WHITELIST_CALL = {
    "QLabel",
    "QPushButton",
    "QToolButton",
    "QAction",
    "QGroupBox",
    "QCheckBox",
    "QRadioButton",
    "QMessageBox",
    "_rt",
    "_rt_runtime",
    "tr_text",
}


PT_HINTS = {
    "projeto",
    "camada",
    "camadas",
    "gerar",
    "limpar",
    "resumo",
    "grafico",
    "gráfico",
    "filtro",
    "filtros",
    "dados",
    "selecione",
    "selecionar",
    "exportar",
    "abrir",
    "salvar",
    "relacao",
    "relação",
    "modelo",
    "dashboard",
    "pergunte",
    "categoria",
    "quantidade",
    "área",
    "extensão",
    "banco",
    "conexao",
    "conexão",
    "erro",
    "aviso",
    "sucesso",
}

PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}")


def looks_user_facing_text(text: str) -> bool:
    t = str(text or "").strip()
    if not t or len(t) > 220:
        return False
    if t.startswith(("#", ".", "_")):
        return False
    style_tokens = [
        "QWidget#",
        "font-",
        "border:",
        "background:",
        "rgba(",
        "px;",
        "::",
        "\\\\",
        "*.xlsx",
        "*.csv",
        "*.pdf",
        "*.json",
        "SELECT ",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
    ]
    if any(token in t for token in style_tokens):
        return False
    low = t.lower()
    if any(ch in t for ch in "ãáàâéêíóôõúçÃÁÀÂÉÊÍÓÔÕÚÇ"):
        return True
    if any(hint in low for hint in PT_HINTS):
        return True
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", t):
        return False
    if re.match(r"^[0-9 .,:;_\\-]+$", t):
        return False
    if len(t.split()) >= 2 and low.isascii():
        return True
    return False


def collect_strings() -> Set[str]:
    collected: Set[str] = set()
    for path in PLUGIN_DIR.rglob("*.py"):
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(raw.lstrip("\ufeff"))
        except Exception:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                attr_name = getattr(fn, "attr", None)
                call_name = getattr(fn, "id", None)
                is_target = bool(attr_name in WHITELIST_ATTR or call_name in WHITELIST_CALL)
                if is_target:
                    for arg in node.args[:3]:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            value = arg.value.strip()
                            if looks_user_facing_text(value):
                                collected.add(value)

            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                        continue
                    if key.value not in {"label", "title", "subtitle", "message", "tooltip", "placeholder", "text"}:
                        continue
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        raw = value.value.strip()
                        if looks_user_facing_text(raw):
                            collected.add(raw)
    return collected


def protect_placeholders(text: str):
    placeholders = {}

    def _sub(match):
        token = f"__PH_{len(placeholders)}__"
        placeholders[token] = match.group(0)
        return token

    protected = PLACEHOLDER_RE.sub(_sub, text)
    return protected, placeholders


def restore_placeholders(text: str, placeholders: Dict[str, str]) -> str:
    out = text
    for token, original in placeholders.items():
        out = out.replace(token, original)
    return out


def translate_map(strings: Set[str], target: str) -> Dict[str, str]:
    translator = GoogleTranslator(source="pt", target=target)
    result = {}
    for source in sorted(strings):
        protected, placeholders = protect_placeholders(source)
        try:
            translated = translator.translate(protected)
            if not translated:
                translated = source
        except Exception:
            translated = source
        translated = restore_placeholders(str(translated), placeholders)
        result[source] = translated
    return result


def main():
    I18N_DIR.mkdir(parents=True, exist_ok=True)
    strings = collect_strings()
    en = translate_map(strings, "en")
    es = translate_map(strings, "es")
    RUNTIME_EN_PATH.write_text(json.dumps(en, ensure_ascii=False, indent=2), encoding="utf-8")
    RUNTIME_ES_PATH.write_text(json.dumps(es, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Runtime dictionaries generated: {len(strings)} entries")
    print(str(RUNTIME_EN_PATH))
    print(str(RUNTIME_ES_PATH))


if __name__ == "__main__":
    main()
