import json
import re
import unicodedata
from pathlib import Path

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import (
    QAction,
    QAbstractButton,
    QComboBox,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QListWidget,
    QTabWidget,
    QTableWidget,
    QTextEdit,
    QWidget,
)


_RUNTIME_DIR = Path(__file__).resolve().parents[1] / "i18n"
_RUNTIME_FILES = {
    "en": _RUNTIME_DIR / "runtime_en.json",
    "es": _RUNTIME_DIR / "runtime_es.json",
}
_OVERRIDE_FILES = {
    "en": _RUNTIME_DIR / "runtime_overrides_en.json",
    "es": _RUNTIME_DIR / "runtime_overrides_es.json",
}

# Fallbacks override machine-generated entries when needed.
_FALLBACK = {
    "en": {
        "Idioma": "Language",
        "Automático": "Automatic",
        "Automatica": "Automatic",
        "Limpar": "Clear",
        "Gerar": "Generate",
        "Edicao": "Edit",
        "Edição": "Edit",
        "Pre-visualizar": "Preview",
        "Pré-visualizar": "Preview",
        "Alternar entre modo de edicao e pre-visualizacao": "Switch between edit and preview mode",
        "Alternar entre modo de edição e pré-visualização": "Switch between edit and preview mode",
        "Mover": "Move",
        "Projeto atual": "Current project",
        "Projeto atual · {total_layers} camada(s)": "Current project · {total_layers} layer(s)",
        "IA: Automatica": "AI: Automatic",
        "IA: Automática": "AI: Automatic",
        "Converse com os dados do projeto": "Talk to project data",
        "Faça perguntas sobre suas camadas e gere gráficos automaticamente": "Ask questions about your layers and generate charts automatically",
        "Digite uma pergunta para gerar o relatório.": "Type a question to generate the report.",
        "Abra pelo menos uma camada vetorial para usar os relatórios.": "Open at least one vector layer to use reports.",
        "Não encontrei dados compatíveis com essa pergunta.": "I couldn't find data compatible with that question.",
        "Encontrei mais de uma camada compatível com essa pergunta.": "I found more than one layer compatible with that question.",
        "Atualize apenas o texto exibido neste gráfico.": "Update only the text shown in this chart.",
        "Atualize apenas o texto exibido na legenda deste gráfico.": "Update only the text shown in this chart legend.",
        "Não encontrei a camada usada neste gráfico: {layer_name}.": "I couldn't find the layer used in this chart: {layer_name}.",
        "Não foi possível localizar feições para a categoria {category_label}.": "Could not locate features for category {category_label}.",
        "Não foi possível atualizar a seleção no mapa.": "Could not update map selection.",
        "O campo de categoria nao existe na camada selecionada.": "The category field does not exist in the selected layer.",
        "O campo de metrica nao existe na camada selecionada.": "The metric field does not exist in the selected layer.",
        "Fechar projeto e voltar para a tela inicial": "Close project and return to the home screen",
        "O painel atual tem alterações não salvas. Deseja salvar antes de fechar?": "The current panel has unsaved changes. Do you want to save before closing?",
        "Adicionar pagina": "Add page",
        "Pagina {index}": "Page {index}",
        "Renomear pagina": "Rename page",
        "Novo nome da pagina": "New page name",
        "Excluir pagina": "Delete page",
        "O painel precisa manter ao menos uma pagina.": "The panel must keep at least one page.",
        "Excluir a pagina \"{title}\"?": "Delete the page \"{title}\"?",
    },
    "es": {
        "Idioma": "Idioma",
        "Automático": "Automático",
        "Automatica": "Automática",
        "Limpar": "Limpiar",
        "Gerar": "Generar",
        "Edicao": "Edición",
        "Edição": "Edición",
        "Pre-visualizar": "Vista previa",
        "Pré-visualizar": "Vista previa",
        "Alternar entre modo de edicao e pre-visualizacao": "Cambiar entre modo edición y vista previa",
        "Alternar entre modo de edição e pré-visualização": "Cambiar entre modo edición y vista previa",
        "Mover": "Mover",
        "Projeto atual": "Proyecto actual",
        "Projeto atual · {total_layers} camada(s)": "Proyecto actual · {total_layers} capa(s)",
        "IA: Automatica": "IA: Automática",
        "IA: Automática": "IA: Automática",
        "Converse com os dados do projeto": "Conversa con los datos del proyecto",
        "Faça perguntas sobre suas camadas e gere gráficos automaticamente": "Haz preguntas sobre tus capas y genera gráficos automáticamente",
        "Digite uma pergunta para gerar o relatório.": "Escriba una pregunta para generar el informe.",
        "Abra pelo menos uma camada vetorial para usar os relatórios.": "Abra al menos una capa vectorial para usar los informes.",
        "Não encontrei dados compatíveis com essa pergunta.": "No encontré datos compatibles con esa pregunta.",
        "Encontrei mais de uma camada compatível com essa pergunta.": "Encontré más de una capa compatible con esa pregunta.",
        "Atualize apenas o texto exibido neste gráfico.": "Actualice solo el texto mostrado en este gráfico.",
        "Atualize apenas o texto exibido na legenda deste gráfico.": "Actualice solo el texto mostrado en la leyenda de este gráfico.",
        "Não encontrei a camada usada neste gráfico: {layer_name}.": "No encontré la capa utilizada en este gráfico: {layer_name}.",
        "Não foi possível localizar feições para a categoria {category_label}.": "No fue posible localizar entidades para la categoría {category_label}.",
        "Não foi possível atualizar a seleção no mapa.": "No fue posible actualizar la selección en el mapa.",
        "O campo de categoria nao existe na camada selecionada.": "El campo de categoría no existe en la capa seleccionada.",
        "O campo de metrica nao existe na camada selecionada.": "El campo de métrica no existe en la capa seleccionada.",
        "Fechar projeto e voltar para a tela inicial": "Cerrar el proyecto y volver a la pantalla inicial",
        "O painel atual tem alterações não salvas. Deseja salvar antes de fechar?": "El panel actual tiene cambios sin guardar. ¿Desea guardar antes de cerrarlo?",
        "Adicionar pagina": "Agregar página",
        "Pagina {index}": "Página {index}",
        "Renomear pagina": "Renombrar página",
        "Novo nome da pagina": "Nuevo nombre de la página",
        "Excluir pagina": "Eliminar página",
        "O painel precisa manter ao menos uma pagina.": "El panel debe conservar al menos una página.",
        "Excluir a pagina \"{title}\"?": "¿Eliminar la página \"{title}\"?",
    },
}

_CACHE = {"en": None, "es": None}
_MISSING_REPORTED = {"en": set(), "es": set()}
_SUSPICIOUS_TRANSLATIONS = {
    "en": {
        "to update",
        "bank",
        "postgreSQL bank".lower(),
        "graphic",
    },
    "es": {
        "abierto",
        "verja",
        "agregaci?n",
        "autom?tico",
        "para actualizar",
    },
}
_PT_HINT_WORDS = (
    "atualizar",
    "configurar",
    "escolher",
    "gerenciar",
    "dashboard",
    "interativo",
    "integracao",
    "integração",
    "integracoes",
    "integrações",
    "painel",
    "grupo",
    "procurar",
    "arquivo",
    "destino",
    "modelo",
    "navegador",
    "nó",
    "geometria",
    "propriedades",
    "remover",
    "selecionar",
    "selecione",
    "projeto",
    "camada",
    "camadas",
    "grafico",
    "gráfico",
    "filtro",
    "filtros",
    "relatorio",
    "relatório",
    "banco",
    "conexao",
    "conexão",
    "salvar",
    "abrir",
    "limpar",
    "gerar",
    "usuario",
    "usuário",
    "senha",
    "catalogo",
    "catálogo",
    "nuvem",
)
_PHRASE_GLOSSARY = {
    "en": [
        ("Adicionar ao Model", "Add to Model"),
        ("Adicionar ao modelo", "Add to model"),
        ("Adicionar ao painel atual", "Add to current panel"),
        ("Adicionar gráfico ao painel", "Add chart to panel"),
        ("Adicionar grafico ao painel", "Add chart to panel"),
        ("Adicionar gráfico", "Add chart"),
        ("Adicionar grafico", "Add chart"),
        ("Atualizar lista", "Refresh list"),
        ("Atualizar catálogo", "Update catalog"),
        ("Atualizar", "Update"),
        ("Configurar Summarizer Cloud...", "Configure Summarizer Cloud..."),
        ("Configurar Summarizer Cloud", "Configure Summarizer Cloud"),
        ("Nova conexão PostgreSQL...", "New PostgreSQL connection..."),
        ("Nova conexao PostgreSQL...", "New PostgreSQL connection..."),
        ("Nova conexão PostgreSQL", "New PostgreSQL connection"),
        ("Nova conexao PostgreSQL", "New PostgreSQL connection"),
        ("Conexão PostgreSQL", "PostgreSQL connection"),
        ("Salvar senha junto com a conexão", "Save password together with the connection"),
        ("Abrir no Navegador", "Open in Browser"),
        ("Conexão '{name}' salva. Expanda o nó novamente para ver as tabelas.", "Connection '{name}' saved. Expand the node again to see the tables."),
        ("Conexão PostgreSQL adicionada via Navegador.", "PostgreSQL connection added via Browser."),
        ("Nó Summarizer Cloud carregado no Navegador.", "Summarizer Cloud node loaded in the Browser."),
        ("Camada '{layer_name}' foi excluída com sucesso.", "Layer '{layer_name}' was deleted successfully."),
        ("Nenhuma conexão local disponível.", "No local connection available."),
        ("Não foi possível acessar o registro de providers do Navegador.", "Could not access the Browser provider registry."),
        ("Geometria: {geometry}", "Geometry: {geometry}"),
        ("Tags: {tags}", "Tags: {tags}"),
        ("Converse com os dados do projeto", "Talk to project data"),
        ("Faça perguntas sobre suas camadas e gere gráficos automaticamente", "Ask questions about your layers and generate charts automatically"),
        ("Faça perguntas sobre suas camadas e gere graficos automaticamente", "Ask questions about your layers and generate charts automatically"),
        ("Adicionar dados ao seu relatório", "Add data to your report"),
        ("Adicionar dados ao seu relatorio", "Add data to your report"),
        ("Obter dados para o modelo", "Get data for the model"),
        ("Dados", "Data"),
        ("Camada:", "Layer:"),
        ("Atualização automática", "Automatic update"),
        ("Dashboard Interativo", "Interactive Dashboard"),
        ("Configure o formato e o destino para exportar o resumo.", "Configure the format and destination to export the summary."),
        ("Formato:", "Format:"),
        ("Arquivo de destino:", "Destination file:"),
        ("Selecione o arquivo de destino...", "Select the destination file..."),
        ("Procurar...", "Browse..."),
        ("Adicionar data e hora ao nome do arquivo", "Add date and time to the filename"),
        ("Integrações externas serão exibidas aqui.", "External integrations will appear here."),
        ("Gerenciar conexões", "Manage connections"),
        ("Summarizer - QGIS", "Summarizer - QGIS"),
        ("Min", "Min"),
        ("Max", "Max"),
        ("PT", "PT"),
        ("Nenhum painel aberto", "No panel open"),
        ("Adicionar gráfico ao painel", "Add chart to panel"),
        ("Gráfico selecionado: {chart_title}", "Selected chart: {chart_title}"),
        ("Gráfico sem título", "Untitled chart"),
        ("Escolher painel salvo", "Choose saved panel"),
        ("Nenhum painel selecionado", "No panel selected"),
        ("Escolher", "Choose"),
        ("Nenhum painel recente encontrado ainda.", "No recent panel found yet."),
        ("Recentes: ", "Recent: "),
        ("Selecione um painel recente para continuar.", "Select a recent panel to continue."),
        ("Nova conexão PostgreSQL", "New PostgreSQL connection"),
        ("Nova conexão PostgreSQL...", "New PostgreSQL connection..."),
        ("Informe os parâmetros da instância PostgreSQL. A conexão será salva localmente no registro do plugin e exibida imediatamente no Navegador. Salve a senha apenas se confiar nesta estação de trabalho.", "Enter the PostgreSQL instance parameters. The connection will be saved locally in the plugin registry and shown immediately in the Browser. Save the password only if you trust this workstation."),
        ("Nome da conexão", "Connection name"),
        ("Host ou IP", "Host or IP"),
        ("Porta", "Port"),
        ("Banco", "Database"),
        ("Nome, host, banco e usuário são obrigatórios.", "Name, host, database and user are required."),
        ("Escolha uma fonte para começar.", "Choose a data source to start."),
        ("Escolha uma fonte para comecar.", "Choose a data source to start."),
        ("Os dados carregados serão exibidos no painel Resumo.", "Loaded data will be shown in the Summary panel."),
        ("Os dados carregados serao exibidos no painel Resumo.", "Loaded data will be shown in the Summary panel."),
        ("Usuário", "User"),
        ("Usuario", "User"),
        ("Senha", "Password"),
        ("Entrar", "Sign in"),
        ("Sair", "Sign out"),
        ("Salvar", "Save"),
        ("Salvar como", "Save as"),
        ("Abrir", "Open"),
        ("Exportar", "Export"),
        ("Categoria", "Category"),
        ("Métrica", "Metric"),
        ("Metrica", "Metric"),
        ("Agregação", "Aggregation"),
        ("Agregacao", "Aggregation"),
        ("Tipo", "Type"),
        ("Título", "Title"),
        ("Titulo", "Title"),
        ("Camada", "Layer"),
        ("Campos", "Fields"),
        ("Linhas", "Rows"),
        ("Colunas", "Columns"),
        ("Valores", "Values"),
        ("Buscar", "Search"),
        ("Limpar", "Clear"),
        ("Sobre", "About"),
        ("Relação", "Relationship"),
        ("Relação", "Relationship"),
        ("Relação", "Relationship"),
        ("Não", "No"),
        ("Sim", "Yes"),
    ],
    "es": [
        ("Adicionar ao Model", "Agregar al Modelo"),
        ("Adicionar ao modelo", "Agregar al modelo"),
        ("Adicionar ao painel atual", "Agregar al panel actual"),
        ("Adicionar gráfico", "Agregar gráfico"),
        ("Adicionar grafico", "Agregar gráfico"),
        ("Atualizar catálogo", "Actualizar catálogo"),
        ("Atualizar", "Actualizar"),
        ("Abrir no Navegador", "Abrir en el navegador"),
        ("Banco:", "Base de datos:"),
        ("Direcao do filtro:", "Dirección del filtro:"),
        ("Exportar camada (preview herdado)", "Exportar capa (vista previa heredada)"),
        ("Filtros por Categoria", "Filtros por categoría"),
        ("Limpar filtros", "Limpiar filtros"),
        ("Visão de Categorias", "Vista de categorías"),
        ("Configurar Summarizer Cloud...", "Configurar Summarizer Cloud..."),
        ("Nova conexão PostgreSQL...", "Nueva conexión PostgreSQL..."),
        ("Nova conexão PostgreSQL", "Nueva conexión PostgreSQL"),
        ("Salvar senha junto com a conexão", "Guardar contraseña junto con la conexión"),
        ("Obter dados para o modelo", "Obtener datos para el modelo"),
        ("Dados", "Datos"),
        ("Camada:", "Capa:"),
        ("Atualização automática", "Actualización automática"),
        ("Dashboard Interativo", "Panel interactivo"),
        ("Configure o formato e o destino para exportar o resumo.", "Configura el formato y el destino para exportar el resumen."),
        ("Formato:", "Formato:"),
        ("Arquivo de destino:", "Archivo de destino:"),
        ("Selecione o arquivo de destino...", "Seleccione el archivo de destino..."),
        ("Procurar...", "Buscar..."),
        ("Adicionar data e hora ao nome do arquivo", "Agregar fecha y hora al nombre del archivo"),
        ("Integrações externas serão exibidas aqui.", "Las integraciones externas se mostrarán aquí."),
        ("Gerenciar conexões", "Administrar conexiones"),
        ("Summarizer - QGIS", "Summarizer - QGIS"),
        ("Min", "Min"),
        ("Max", "Max"),
        ("PT", "PT"),
        ("Conexão PostgreSQL", "Conexión PostgreSQL"),
        ("Conexão '{name}' salva. Expanda o nó novamente para ver as tabelas.", "Conexión '{name}' guardada. Expande el nodo nuevamente para ver las tablas."),
        ("Conexão PostgreSQL adicionada via Navegador.", "Conexión PostgreSQL agregada vía Navegador."),
        ("Nó Summarizer Cloud carregado no Navegador.", "Nodo Summarizer Cloud cargado en el Navegador."),
        ("Converse com os dados do projeto", "Conversa con los datos del proyecto"),
        ("Faça perguntas sobre suas camadas e gere gráficos automaticamente", "Haz preguntas sobre tus capas y genera gráficos automáticamente"),
        ("Faça perguntas sobre suas camadas e gere graficos automaticamente", "Haz preguntas sobre tus capas y genera gráficos automáticamente"),
        ("Adicionar dados ao seu relatório", "Agrega datos a tu informe"),
        ("Adicionar dados ao seu relatorio", "Agrega datos a tu informe"),
        ("Escolha uma fonte para começar.", "Elige una fuente de datos para empezar."),
        ("Escolha uma fonte para comecar.", "Elige una fuente de datos para empezar."),
        ("Os dados carregados serão exibidos no painel Resumo.", "Los datos cargados se mostrarán en el panel Resumen."),
        ("Os dados carregados serao exibidos no painel Resumo.", "Los datos cargados se mostrarán en el panel Resumen."),
        ("Usuário", "Usuario"),
        ("Usuario", "Usuario"),
        ("Senha", "Contraseña"),
        ("Entrar", "Iniciar sesión"),
        ("Sair", "Cerrar sesión"),
        ("Salvar", "Guardar"),
        ("Salvar como", "Guardar como"),
        ("Abrir", "Abrir"),
        ("Exportar", "Exportar"),
        ("Categoria", "Categoría"),
        ("Métrica", "Métrica"),
        ("Metrica", "Métrica"),
        ("Agregação", "Agregación"),
        ("Agregacao", "Agregación"),
        ("Tipo", "Tipo"),
        ("Título", "Título"),
        ("Titulo", "Título"),
        ("Camada", "Capa"),
        ("Campos", "Campos"),
        ("Linhas", "Filas"),
        ("Colunas", "Columnas"),
        ("Valores", "Valores"),
        ("Buscar", "Buscar"),
        ("Limpar", "Limpiar"),
        ("Sobre", "Acerca de"),
        ("Relação", "Relación"),
        ("Relação", "Relación"),
        ("Relação", "Relación"),
        ("Não", "No"),
        ("Sim", "Sí"),
    ],
}


def _normalize_locale(locale_code: str) -> str:
    code = str(locale_code or "").strip().lower()
    if not code or code == "auto":
        try:
            user = str(QSettings().value("locale/userLocale", "") or "").strip().lower()
        except Exception:
            user = ""
        code = user
    if code.startswith("qgis_") or code.startswith("qgis-"):
        code = code[5:]
    short = re.split(r"[-_]", code, maxsplit=1)[0].strip().lower()
    if short in {"pt", "en", "es"}:
        return short
    return "en"


def current_locale() -> str:
    try:
        forced = str(QSettings().value("PowerBISummarizer/uiLocale", "auto") or "auto").strip()
    except Exception:
        forced = "auto"
    return _normalize_locale(forced)


def _looks_like_mojibake(text: str) -> bool:
    source = str(text or "")
    return any(marker in source for marker in ("Ã", "Â", "�", "ï¿½"))


def _repair_mojibake(text: str) -> str:
    source = str(text or "")
    if not source or not _looks_like_mojibake(source):
        return source
    for source_encoding, target_encoding in (("latin1", "utf-8"), ("cp1252", "utf-8")):
        try:
            repaired = source.encode(source_encoding).decode(target_encoding)
            if repaired:
                return repaired
        except Exception:
            continue
    return source


def _text_variants(text: str):
    source = str(text or "")
    raw_candidates = [source, source.strip(), _repair_mojibake(source), _repair_mojibake(source.strip())]
    variants = []
    for candidate in raw_candidates:
        value = str(candidate or "")
        if not value:
            continue
        for normalized in (value, unicodedata.normalize("NFC", value)):
            if normalized and normalized not in variants:
                variants.append(normalized)
    return variants


def _strip_accents(text: str) -> str:
    source = str(text or "")
    if not source:
        return source
    normalized = unicodedata.normalize("NFKD", source)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _load_json_map(path: Path):
    mapping = {}
    try:
        if path.exists():
            mapping = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(mapping, dict):
                mapping = {}
    except Exception:
        mapping = {}
    return mapping


def _augment_variants_map(mapping: dict):
    augmented = {}
    for raw_key, raw_value in dict(mapping or {}).items():
        key = str(raw_key or "")
        if not key:
            continue
        value = str(raw_value or "")
        for variant in _text_variants(key):
            if variant and variant not in augmented:
                augmented[variant] = value
            deaccent = _strip_accents(variant)
            if deaccent and deaccent not in augmented:
                augmented[deaccent] = value
    return augmented


def _load_runtime_map(locale_code: str):
    locale = _normalize_locale(locale_code)
    if locale not in {"en", "es"}:
        return {}
    cached = _CACHE.get(locale)
    if isinstance(cached, dict):
        return cached
    path = _RUNTIME_FILES.get(locale)
    mapping = _load_json_map(path) if path is not None else {}
    combined = dict(mapping)
    # Override weak machine terms with curated fallbacks.
    combined.update(_FALLBACK.get(locale, {}))
    override_path = _OVERRIDE_FILES.get(locale)
    if override_path is not None:
        combined.update(_load_json_map(override_path))
    combined = _augment_variants_map(combined)
    _CACHE[locale] = combined
    return combined


def _mapping_lookup(mapping: dict, source: str):
    for candidate in _text_variants(source):
        if candidate in mapping:
            return str(mapping.get(candidate) or ""), True
    return source, False


def _contains_pt_hint(text: str) -> bool:
    source = _strip_accents(str(text or "").lower())
    if not source:
        return False
    return any(hint in source for hint in _PT_HINT_WORDS)


def _looks_suspicious_translation(source: str, translated: str, locale: str) -> bool:
    src = str(source or "").strip()
    dst = str(translated or "").strip()
    if not src or not dst:
        return False
    if _looks_like_mojibake(dst):
        return True
    if locale in {"en", "es"} and _contains_pt_hint(dst):
        return True
    suspicious = _SUSPICIOUS_TRANSLATIONS.get(locale, set())
    if dst.lower() in suspicious:
        return True
    # Avoid keeping source text untouched for likely PT phrases in non-PT locales.
    if dst == src and _contains_pt_hint(src):
        return True
    return False


def _replace_phrase_case_aware(text: str, source_phrase: str, target_phrase: str) -> str:
    pattern = re.compile(re.escape(source_phrase), re.IGNORECASE)

    def _replacement(match):
        chunk = match.group(0)
        if chunk.isupper():
            return target_phrase.upper()
        if chunk[:1].isupper():
            return target_phrase[:1].upper() + target_phrase[1:]
        return target_phrase

    return pattern.sub(_replacement, text)


def _glossary_translate(text: str, locale: str) -> str:
    source = _repair_mojibake(str(text or ""))
    if not source or locale not in {"en", "es"}:
        return source
    translated = source
    for phrase, replacement in _PHRASE_GLOSSARY.get(locale, []):
        translated = _replace_phrase_case_aware(translated, phrase, replacement)
    return translated


def tr_text(text: str, locale_code: str = "", **kwargs) -> str:
    source = str(text or "")
    locale = _normalize_locale(locale_code or current_locale())
    if locale == "pt":
        translated = source
        matched = True
    else:
        mapping = _load_runtime_map(locale)
        translated, matched = _mapping_lookup(mapping, source)
        if _looks_suspicious_translation(source, translated, locale):
            fallback_translated = _glossary_translate(source, locale)
            if fallback_translated and fallback_translated != source:
                translated = fallback_translated
                matched = True
        if source and not matched and source not in _MISSING_REPORTED.get(locale, set()):
            try:
                _MISSING_REPORTED.setdefault(locale, set()).add(source)
                missing_file = _RUNTIME_DIR / f"runtime_missing_{locale}.txt"
                with missing_file.open("a", encoding="utf-8") as handler:
                    handler.write(source.replace("\n", "\\n") + "\n")
            except Exception:
                pass
    if kwargs:
        try:
            return translated.format(**kwargs)
        except Exception:
            return translated
    return translated


def _source_text(obj, key: str, current_value: str) -> str:
    prop_key = f"_pbi18n_src_{key}"
    try:
        stored = obj.property(prop_key)
    except Exception:
        stored = None
    if stored is None or str(stored) == "":
        source = str(current_value or "")
        try:
            obj.setProperty(prop_key, source)
        except Exception:
            pass
        return source
    return str(stored)


def _translate_qaction(action: QAction, locale_code: str):
    text = str(action.text() or "")
    if text:
        action.setText(tr_text(_source_text(action, "text", text), locale_code))
    tip = str(action.toolTip() or "")
    if tip:
        action.setToolTip(tr_text(_source_text(action, "tooltip", tip), locale_code))
    status = str(action.statusTip() or "")
    if status:
        action.setStatusTip(tr_text(_source_text(action, "status", status), locale_code))


def apply_widget_translations(root: QWidget, locale_code: str = ""):
    if root is None:
        return
    locale = _normalize_locale(locale_code or current_locale())

    def _apply(widget):
        try:
            title = str(widget.windowTitle() or "")
            if title:
                widget.setWindowTitle(tr_text(_source_text(widget, "window_title", title), locale))
        except Exception:
            pass

        try:
            tip = str(widget.toolTip() or "")
            if tip:
                widget.setToolTip(tr_text(_source_text(widget, "tooltip", tip), locale))
        except Exception:
            pass

        try:
            status = str(widget.statusTip() or "")
            if status:
                widget.setStatusTip(tr_text(_source_text(widget, "status", status), locale))
        except Exception:
            pass

        if isinstance(widget, QLabel):
            text = str(widget.text() or "")
            if text:
                widget.setText(tr_text(_source_text(widget, "text", text), locale))

        if isinstance(widget, QAbstractButton):
            text = str(widget.text() or "")
            if text:
                widget.setText(tr_text(_source_text(widget, "text", text), locale))

        if isinstance(widget, QLineEdit):
            placeholder = str(widget.placeholderText() or "")
            if placeholder:
                widget.setPlaceholderText(tr_text(_source_text(widget, "placeholder", placeholder), locale))

        if isinstance(widget, (QTextEdit, QPlainTextEdit)):
            placeholder = str(widget.placeholderText() or "")
            if placeholder:
                widget.setPlaceholderText(tr_text(_source_text(widget, "placeholder", placeholder), locale))

        if isinstance(widget, QGroupBox):
            title = str(widget.title() or "")
            if title:
                widget.setTitle(tr_text(_source_text(widget, "group_title", title), locale))

        if isinstance(widget, QComboBox):
            for idx in range(widget.count()):
                text = str(widget.itemText(idx) or "")
                if not text:
                    continue
                src = _source_text(widget, f"combo_{idx}", text)
                widget.setItemText(idx, tr_text(src, locale))

        if isinstance(widget, QTableWidget):
            try:
                header = widget.horizontalHeaderItem
                for idx in range(widget.columnCount()):
                    item = header(idx)
                    if item is None:
                        continue
                    text = str(item.text() or "")
                    if not text:
                        continue
                    src = _source_text(item, "text", text)
                    item.setText(tr_text(src, locale))
            except Exception:
                pass

        if isinstance(widget, QListWidget):
            try:
                for idx in range(widget.count()):
                    item = widget.item(idx)
                    if item is None:
                        continue
                    text = str(item.text() or "")
                    if not text:
                        continue
                    src = _source_text(item, "text", text)
                    item.setText(tr_text(src, locale))
            except Exception:
                pass

        if isinstance(widget, QTabWidget):
            for idx in range(widget.count()):
                text = str(widget.tabText(idx) or "")
                if not text:
                    continue
                src = _source_text(widget, f"tab_{idx}", text)
                widget.setTabText(idx, tr_text(src, locale))

        if isinstance(widget, QDialogButtonBox):
            try:
                for button in widget.buttons():
                    text = str(button.text() or "")
                    if not text:
                        continue
                    src = _source_text(button, "text", text)
                    button.setText(tr_text(src, locale))
            except Exception:
                pass

        try:
            for action in widget.actions() or []:
                if isinstance(action, QAction):
                    _translate_qaction(action, locale)
        except Exception:
            pass

    try:
        _apply(root)
    except Exception:
        pass

    try:
        for child in root.findChildren(QWidget):
            try:
                _apply(child)
            except Exception:
                continue
    except Exception:
        pass

