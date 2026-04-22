import ast
import json
import pathlib
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN_DIR = ROOT / 'plugin' / 'power_bi_summarizer'
I18N_DIR = PLUGIN_DIR / 'i18n'
REPORT_DIR = ROOT / 'scripts' / '_reports'

FILES = {
    'en': [I18N_DIR / 'runtime_en.json', I18N_DIR / 'runtime_overrides_en.json'],
    'es': [I18N_DIR / 'runtime_es.json', I18N_DIR / 'runtime_overrides_es.json'],
}

TARGET_ATTR = {
    'setText','setToolTip','setPlaceholderText','setWindowTitle','setTitle','setStatusTip','setWhatsThis',
    'addAction','addMenu','setTabText','setHeaderLabel','setLabelText','setHtml','setPlainText','addItem','insertItem'
}
TARGET_CALL = {'QLabel','QPushButton','QToolButton','QAction','QGroupBox','QCheckBox','QRadioButton','QMessageBox'}

PT_HINTS = {
    'projeto','camada','camadas','grafico','gráfico','filtro','filtros','relatorio','relatório','dados',
    'selecione','selecionar','exportar','abrir','salvar','relacao','relação','modelo','dashboard','pergunte',
    'categoria','quantidade','área','extensão','banco','conexao','conexão','erro','aviso','sucesso','nuvem',
}

SUSPICIOUS = {
    'en': {'to update','bank','graphic'},
    'es': {'abierto','verja','agregaci?n','autom?tico','para actualizar'},
}


def strip_accents(text: str) -> str:
    n = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in n if not unicodedata.combining(ch))


def looks_user_facing_text(text: str) -> bool:
    t = str(text or '').strip()
    if not t or len(t) > 220:
        return False
    if t.startswith(('#','.', '_')):
        return False
    if any(token in t for token in ('QWidget#','font-','border:','background:','rgba(','px;','::','\\','*.xlsx','*.csv','*.pdf','*.json')):
        return False
    low = strip_accents(t.lower())
    if any(h in low for h in PT_HINTS):
        return True
    if len(t.split()) >= 2 and low.isascii():
        return True
    return False


def collect_strings():
    out = set()
    for path in PLUGIN_DIR.rglob('*.py'):
        raw = path.read_text(encoding='utf-8', errors='ignore')
        try:
            tree = ast.parse(raw.lstrip('\ufeff'))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                attr_name = getattr(node.func, 'attr', None)
                call_name = getattr(node.func, 'id', None)
                if attr_name in TARGET_ATTR or call_name in TARGET_CALL:
                    for arg in node.args[:3]:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            v = arg.value.strip()
                            if looks_user_facing_text(v):
                                out.add(v)
    return out


def load_map(locale: str):
    data = {}
    for p in FILES[locale]:
        if not p.exists():
            continue
        payload = json.loads(p.read_text(encoding='utf-8-sig'))
        if isinstance(payload, dict):
            data.update({str(k): str(v) for k, v in payload.items()})
    return data


def is_suspicious(source: str, translated: str, locale: str):
    s = str(source or '').strip()
    t = str(translated or '').strip()
    if not s or not t:
        return True
    if t == s and any(h in strip_accents(s.lower()) for h in PT_HINTS):
        return True
    if 'Ã' in t or 'Â' in t or '�' in t:
        return True
    low = strip_accents(t.lower())
    if any(h in low for h in PT_HINTS):
        return True
    if low in SUSPICIOUS.get(locale, set()):
        return True
    return False


def main():
    strings = sorted(collect_strings())
    print(f'Collected strings: {len(strings)}')
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    for locale in ('en','es'):
        mapping = load_map(locale)
        missing = []
        suspicious = []
        for s in strings:
            tr = mapping.get(s)
            if not tr:
                missing.append(s)
                continue
            if is_suspicious(s, tr, locale):
                suspicious.append((s, tr))
        print(f'[{locale}] map entries: {len(mapping)} | missing: {len(missing)} | suspicious: {len(suspicious)}')
        out_missing = REPORT_DIR / f'audit_missing_{locale}.txt'
        out_susp = REPORT_DIR / f'audit_suspicious_{locale}.txt'
        out_missing.write_text('\n'.join(missing), encoding='utf-8')
        out_susp.write_text('\n'.join(f'{s} => {t}' for s, t in suspicious), encoding='utf-8')
        print(f'  wrote: {out_missing.name}, {out_susp.name}')


if __name__ == '__main__':
    main()
