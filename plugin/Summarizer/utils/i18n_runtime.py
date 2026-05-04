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
        "Expandir campos": "Expand fields",
        "Recolher campos": "Collapse fields",
        "Expandir filtros": "Expand filters",
        "Recolher filtros": "Collapse filters",
        "Restaurar layout": "Restore layout",
        "Configurações do resumo": "Summary settings",
        "Configuracoes do resumo": "Summary settings",
        "Mostrar ou ocultar camada e filtros": "Show or hide layer and filters",
        "Desfazer (Ctrl+Z)": "Undo (Ctrl+Z)",
        "Refazer (Ctrl+Shift+Z)": "Redo (Ctrl+Shift+Z)",
        "Importar planilha": "Import spreadsheet",
        "Campos": "Fields",
        "Filtros": "Filters",
        "Personalizar tabela": "Customize table",
        "Altura da linha": "Row height",
        "Linhas alternadas": "Alternating rows",
        "Cabeçalho compacto": "Compact header",
        "Cabecalho compacto": "Compact header",
        "Parar análise": "Stop analysis",
        "Cancelando...": "Cancelling...",
        "Análise cancelada. Você pode ajustar a pergunta e tentar novamente.": "Analysis cancelled. You can adjust the question and try again.",
        "A análise foi cancelada pelo usuário.": "The analysis was cancelled by the user.",
        "Tentar outra opção": "Try another option",
        "Vamos tentar outra leitura da sua pergunta.": "Let's try another reading of your question.",
        "Nao encontrei outra interpretacao pronta. Escolha a coluna que mais combina com a pergunta para eu recalcular.": "I did not find another ready interpretation. Choose the column that best matches the question so I can recalculate.",
        (
            "Aba Resumo\n"
            "Objetivo: explorar uma camada em formato de tabela dinâmica, com agrupamentos, totais e leitura rápida dos campos.\n"
            "Quando usar: use esta aba quando quiser investigar os dados manualmente, comparar categorias ou montar uma visão tabular antes de gerar gráficos.\n"
            "Como fazer:\n"
            "1. Abra a aba Resumo no menu lateral.\n"
            "2. Escolha a camada que deseja analisar.\n"
            "3. Selecione campos, medidas e agrupamentos conforme a estrutura da camada.\n"
            "4. Use filtros e seleção de campos para refinar a tabela.\n"
            "5. Quando precisar de uma resposta conversada ou gráfico automático, volte para a aba Relatórios.\n"
            "Dica: a aba Resumo é melhor para conferência e exploração; a aba Relatórios é melhor para perguntas em linguagem natural."
        ): (
            "Summary Tab\n"
            "Purpose: explore a layer as a pivot-style table, with groupings, totals, and a quick reading of fields.\n"
            "When to use it: use this tab when you want to inspect data manually, compare categories, or build a tabular view before generating charts.\n"
            "How to use it:\n"
            "1. Open the Summary tab from the side menu.\n"
            "2. Choose the layer you want to analyze.\n"
            "3. Select fields, measures, and groupings according to the layer structure.\n"
            "4. Use filters and field selection to refine the table.\n"
            "5. When you need a conversational answer or an automatic chart, return to the Reports tab.\n"
            "Tip: the Summary tab is best for checking and exploring; the Reports tab is best for natural-language questions."
        ),
        (
            "Aba Relatórios\n"
            "Objetivo: transformar perguntas em análises, tabelas e gráficos automáticos usando as camadas do projeto.\n"
            "Quando usar: use esta aba quando quiser perguntar algo como totais, rankings, comparações, distribuições ou filtros por atributo.\n"
            "Como fazer:\n"
            "1. Digite a pergunta no campo do chat.\n"
            "2. Escolha uma ou mais camadas quando a janela de seleção aparecer.\n"
            "3. Clique em Analisar para executar a pergunta somente nas camadas marcadas.\n"
            "4. Se o chat tiver dúvida sobre a coluna correta, selecione uma das opções sugeridas.\n"
            "5. Continue perguntando: as camadas escolhidas permanecem em foco até você clicar em Limpar.\n"
            "Dica: para reiniciar tudo e escolher outras camadas, use o botão Limpar."
        ): (
            "Reports Tab\n"
            "Purpose: turn questions into analyses, tables, and automatic charts using the project layers.\n"
            "When to use it: use this tab when you want totals, rankings, comparisons, distributions, or attribute filters.\n"
            "How to use it:\n"
            "1. Type your question in the chat field.\n"
            "2. Choose one or more layers when the selection window appears.\n"
            "3. Click Analyze to run the question only on the selected layers.\n"
            "4. If the chat is unsure about the correct column, choose one of the suggested options.\n"
            "5. Keep asking questions: the selected layers stay in focus until you click Clear.\n"
            "Tip: to restart and choose other layers, use the Clear button."
        ),
        (
            "Aba Modelo/Dashboard\n"
            "Objetivo: organizar gráficos, cards e visuais em uma página de apresentação do projeto.\n"
            "Quando usar: use esta aba quando quiser montar um painel visual, posicionar elementos e preparar uma leitura executiva dos resultados.\n"
            "Como fazer:\n"
            "1. Gere um gráfico ou resultado na aba Relatórios.\n"
            "2. Use a opção de adicionar ao modelo quando ela estiver disponível.\n"
            "3. Na aba Modelo, organize os visuais no canvas.\n"
            "4. Ajuste tamanho, posição, aparência e leitura dos elementos.\n"
            "5. Volte à aba Relatórios sempre que precisar criar novas análises.\n"
            "Dica: pense nessa aba como a área de montagem final do dashboard."
        ): (
            "Model/Dashboard Tab\n"
            "Purpose: arrange charts, cards, and visuals into a presentation page for the project.\n"
            "When to use it: use this tab when you want to build a visual panel, position elements, and prepare an executive view of the results.\n"
            "How to use it:\n"
            "1. Generate a chart or result in the Reports tab.\n"
            "2. Use the add-to-model option when it is available.\n"
            "3. In the Model tab, arrange the visuals on the canvas.\n"
            "4. Adjust size, position, appearance, and readability.\n"
            "5. Return to the Reports tab whenever you need to create new analyses.\n"
            "Tip: think of this tab as the final dashboard assembly area."
        ),
        (
            "Aba Conexões/Integrações\n"
            "Objetivo: centralizar origens externas e facilitar o acesso a dados que não estão diretamente no projeto.\n"
            "Quando usar: use esta área para configurar conexões, abrir fontes recentes ou preparar dados externos para análise.\n"
            "Como fazer:\n"
            "1. Abra a área de Conexões ou Integrações no plugin.\n"
            "2. Cadastre, selecione ou reabra uma origem de dados disponível.\n"
            "3. Carregue as camadas necessárias no projeto quando a origem exigir isso.\n"
            "4. Volte para a aba Relatórios e escolha o contexto correto no topo do chat.\n"
            "5. Faça a pergunta e selecione as camadas que devem ser analisadas.\n"
            "Dica: conexão prepara a origem; a análise acontece na aba Relatórios."
        ): (
            "Connections/Integrations Tab\n"
            "Purpose: centralize external sources and make it easier to access data that is not directly in the project.\n"
            "When to use it: use this area to configure connections, open recent sources, or prepare external data for analysis.\n"
            "How to use it:\n"
            "1. Open Connections or Integrations in the plugin.\n"
            "2. Register, select, or reopen an available data source.\n"
            "3. Load the required layers into the project when the source requires it.\n"
            "4. Return to the Reports tab and choose the correct context at the top of the chat.\n"
            "5. Ask your question and select the layers that should be analyzed.\n"
            "Tip: the connection prepares the source; the analysis happens in the Reports tab."
        ),
        (
            "Aba Sobre\n"
            "Objetivo: apresentar informações institucionais e técnicas do Summarizer.\n"
            "Quando usar: use esta aba quando precisar conferir versão, descrição, suporte ou informações gerais do plugin.\n"
            "Como fazer:\n"
            "1. Abra Sobre no rodapé ou na área indicada do plugin.\n"
            "2. Consulte as informações exibidas sobre o produto.\n"
            "3. Use esses dados para suporte, validação de versão ou identificação do plugin.\n"
            "4. Para executar análises, volte para Relatórios, Resumo, Modelo ou Conexões.\n"
            "Dica: a aba Sobre é informativa; ela não altera seus dados nem executa consultas."
        ): (
            "About Tab\n"
            "Purpose: present institutional and technical information about Summarizer.\n"
            "When to use it: use this tab when you need to check the version, description, support, or general plugin information.\n"
            "How to use it:\n"
            "1. Open About in the footer or in the indicated plugin area.\n"
            "2. Review the product information shown there.\n"
            "3. Use that information for support, version validation, or plugin identification.\n"
            "4. To run analyses, return to Reports, Summary, Model, or Connections.\n"
            "Tip: the About tab is informational; it does not change your data or run queries."
        ),
        (
            "Contexto PostgreSQL\n"
            "Objetivo: direcionar perguntas para camadas carregadas a partir de uma conexão PostgreSQL/PostGIS.\n"
            "Quando usar: use este contexto quando a análise deve considerar dados do banco, e não todas as camadas do projeto.\n"
            "Como fazer:\n"
            "1. Configure ou carregue as camadas PostgreSQL no projeto.\n"
            "2. No topo do chat, abra o seletor de contexto.\n"
            "3. Escolha Banco PostgreSQL.\n"
            "4. Digite sua pergunta e selecione uma ou mais camadas PostgreSQL quando a janela aparecer.\n"
            "5. Clique em Analisar. As próximas perguntas continuam usando essas camadas até você clicar em Limpar.\n"
            "Dica: se nenhuma camada aparecer, verifique se a conexão está configurada e se as camadas foram carregadas no QGIS."
        ): (
            "PostgreSQL Context\n"
            "Purpose: direct questions to layers loaded from a PostgreSQL/PostGIS connection.\n"
            "When to use it: use this context when the analysis should consider database data, not every layer in the project.\n"
            "How to use it:\n"
            "1. Configure or load the PostgreSQL layers into the project.\n"
            "2. At the top of the chat, open the context selector.\n"
            "3. Choose PostgreSQL Database.\n"
            "4. Type your question and select one or more PostgreSQL layers when the window appears.\n"
            "5. Click Analyze. The next questions keep using those layers until you click Clear.\n"
            "Tip: if no layer appears, check whether the connection is configured and the layers were loaded in QGIS."
        ),
        (
            "Seleção de camadas no chat\n"
            "Objetivo: garantir que a resposta seja calculada somente nas camadas escolhidas por você.\n"
            "Quando usar: sempre que a pergunta for sobre dados do projeto, o chat precisa saber quais camadas deve analisar.\n"
            "Como fazer:\n"
            "1. Digite a pergunta no chat.\n"
            "2. Quando a janela abrir, marque uma ou mais camadas.\n"
            "3. Clique em Analisar para confirmar a seleção.\n"
            "4. Continue perguntando normalmente; a seleção permanece ativa.\n"
            "5. Para trocar as camadas, clique em Limpar e faça uma nova pergunta.\n"
            "Dica: selecionar poucas camadas tende a gerar respostas mais precisas."
        ): (
            "Layer Selection in Chat\n"
            "Purpose: ensure the answer is calculated only from the layers you choose.\n"
            "When to use it: whenever the question is about project data, the chat needs to know which layers it should analyze.\n"
            "How to use it:\n"
            "1. Type the question in the chat.\n"
            "2. When the window opens, select one or more layers.\n"
            "3. Click Analyze to confirm the selection.\n"
            "4. Keep asking normally; the selection remains active.\n"
            "5. To switch layers, click Clear and ask a new question.\n"
            "Tip: selecting fewer layers usually produces more precise answers."
        ),
        (
            "Gráficos e resultados visuais\n"
            "Objetivo: transformar uma resposta do chat em visualizações como barras, rankings, totais ou distribuições.\n"
            "Quando usar: use gráficos quando quiser apresentar padrões, comparar categorias ou destacar indicadores do projeto.\n"
            "Como fazer:\n"
            "1. Faça uma pergunta que gere uma métrica, contagem, soma, média, ranking ou agrupamento.\n"
            "2. Selecione as camadas que devem ser analisadas.\n"
            "3. Clique em Gerar ou Analisar.\n"
            "4. Revise o resultado visual criado pelo chat.\n"
            "5. Se quiser montar uma apresentação, adicione o visual ao Modelo/Dashboard.\n"
            "Dica: perguntas com 'por categoria', 'top 10', 'total por' ou 'quantidade por' costumam gerar bons gráficos."
        ): (
            "Charts and Visual Results\n"
            "Purpose: turn a chat answer into visualizations such as bars, rankings, totals, or distributions.\n"
            "When to use it: use charts when you want to present patterns, compare categories, or highlight project indicators.\n"
            "How to use it:\n"
            "1. Ask a question that produces a metric, count, sum, average, ranking, or grouping.\n"
            "2. Select the layers that should be analyzed.\n"
            "3. Click Generate or Analyze.\n"
            "4. Review the visual result created by the chat.\n"
            "5. If you want to build a presentation, add the visual to Model/Dashboard.\n"
            "Tip: questions with 'by category', 'top 10', 'total by', or 'count by' usually generate good charts."
        ),
        (
            "Filtros no chat\n"
            "Objetivo: limitar a análise a um conjunto específico de registros, usando colunas e valores das camadas selecionadas.\n"
            "Quando usar: use filtros quando quiser responder perguntas por local, status, categoria, tipo, data ou qualquer campo existente na camada.\n"
            "Como fazer:\n"
            "1. Escreva o filtro dentro da pergunta, por exemplo: por cidade, por status ou em determinado valor.\n"
            "2. O chat compara o texto com nomes de colunas e valores encontrados na camada.\n"
            "3. Se houver dúvida, ele mostra opções para você escolher a coluna correta.\n"
            "4. Depois da escolha, a consulta é recalculada somente com o filtro selecionado.\n"
            "Dica: quanto mais parecido o texto estiver com o nome da coluna ou valor real, melhor será a interpretação."
        ): (
            "Filters in Chat\n"
            "Purpose: limit the analysis to a specific set of records using columns and values from the selected layers.\n"
            "When to use it: use filters when you want to answer questions by place, status, category, type, date, or any existing field in the layer.\n"
            "How to use it:\n"
            "1. Write the filter inside the question, for example: by city, by status, or with a specific value.\n"
            "2. The chat compares the text with column names and values found in the layer.\n"
            "3. If there is uncertainty, it shows options so you can choose the correct column.\n"
            "4. After the choice, the query is recalculated only with the selected filter.\n"
            "Tip: the closer the text is to the real column name or value, the better the interpretation will be."
        ),
        (
            "Botão Limpar\n"
            "Objetivo: reiniciar o contexto do chat com segurança.\n"
            "Quando usar: use Limpar quando quiser encerrar a análise atual, trocar as camadas em foco ou começar uma nova linha de perguntas.\n"
            "O que acontece:\n"
            "1. O histórico visível do chat é limpo.\n"
            "2. As camadas em foco são removidas.\n"
            "3. A memória da conversa atual é reiniciada.\n"
            "4. Na próxima pergunta de dados, o chat volta a pedir a seleção de camadas.\n"
            "Dica: Limpar não apaga suas camadas do QGIS; ele apenas reinicia o contexto do chat."
        ): (
            "Clear Button\n"
            "Purpose: safely restart the chat context.\n"
            "When to use it: use Clear when you want to finish the current analysis, switch focused layers, or start a new line of questions.\n"
            "What happens:\n"
            "1. The visible chat history is cleared.\n"
            "2. The focused layers are removed.\n"
            "3. The current conversation memory is restarted.\n"
            "4. On the next data question, the chat asks you to select layers again.\n"
            "Tip: Clear does not delete your QGIS layers; it only restarts the chat context."
        ),
        (
            "Idioma e tradução\n"
            "Objetivo: permitir que o plugin seja usado em diferentes idiomas sem perder a lógica de análise.\n"
            "Como funciona:\n"
            "1. Você pode fazer perguntas em português ou inglês.\n"
            "2. O chat normaliza acentos, maiúsculas e sinais para comparar melhor os textos.\n"
            "3. Para perguntas sobre dados, ele prioriza nomes reais de camadas, colunas e valores do projeto.\n"
            "4. Para perguntas sobre o plugin, ele responde como guia de uso, sem pedir camada.\n"
            "5. As respostas de ajuda são preparadas para acompanhar o idioma selecionado no plugin.\n"
            "Dica: em consultas de dados, escrever próximo ao nome real da coluna sempre melhora o resultado."
        ): (
            "Language and Translation\n"
            "Purpose: allow the plugin to be used in different languages without losing analysis logic.\n"
            "How it works:\n"
            "1. You can ask questions in Portuguese or English.\n"
            "2. The chat normalizes accents, capitalization, and symbols to compare text more reliably.\n"
            "3. For data questions, it prioritizes real layer names, column names, and project values.\n"
            "4. For plugin questions, it answers as a usage guide without asking for a layer.\n"
            "5. Help answers are prepared to follow the language selected in the plugin.\n"
            "Tip: in data queries, writing close to the real column name always improves the result."
        ),
        (
            "Ajuda do Summarizer\n"
            "Objetivo: orientar o uso do plugin sem executar consultas desnecessárias.\n"
            "Como funciona:\n"
            "1. Se a pergunta for sobre uma funcionalidade, o chat responde com explicação e passo a passo.\n"
            "2. Se a pergunta for sobre dados, o chat solicita as camadas que devem ser analisadas.\n"
            "3. As camadas escolhidas permanecem em foco até você clicar em Limpar.\n"
            "4. Você pode perguntar sobre Relatórios, Resumo, Modelo/Dashboard, Conexão, PostgreSQL ou Sobre.\n"
            "Dica: para obter uma orientação mais precisa, cite o nome da aba ou do comando que deseja entender."
        ): (
            "Summarizer Help\n"
            "Purpose: guide plugin usage without running unnecessary queries.\n"
            "How it works:\n"
            "1. If the question is about a feature, the chat answers with an explanation and step-by-step guidance.\n"
            "2. If the question is about data, the chat asks which layers should be analyzed.\n"
            "3. The selected layers stay in focus until you click Clear.\n"
            "4. You can ask about Reports, Summary, Model/Dashboard, Connections, PostgreSQL, or About.\n"
            "Tip: for more precise guidance, mention the tab or command you want to understand."
        ),
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
        "Expandir campos": "Expandir campos",
        "Recolher campos": "Ocultar campos",
        "Expandir filtros": "Expandir filtros",
        "Recolher filtros": "Ocultar filtros",
        "Restaurar layout": "Restaurar diseño",
        "Configurações do resumo": "Configuración del resumen",
        "Configuracoes do resumo": "Configuración del resumen",
        "Mostrar ou ocultar camada e filtros": "Mostrar u ocultar capa y filtros",
        "Desfazer (Ctrl+Z)": "Deshacer (Ctrl+Z)",
        "Refazer (Ctrl+Shift+Z)": "Rehacer (Ctrl+Shift+Z)",
        "Importar planilha": "Importar hoja de cálculo",
        "Campos": "Campos",
        "Filtros": "Filtros",
        "Personalizar tabela": "Personalizar tabla",
        "Altura da linha": "Altura de fila",
        "Linhas alternadas": "Filas alternas",
        "Cabeçalho compacto": "Encabezado compacto",
        "Cabecalho compacto": "Encabezado compacto",
        "Parar análise": "Detener análisis",
        "Cancelando...": "Cancelando...",
        "Análise cancelada. Você pode ajustar a pergunta e tentar novamente.": "Análisis cancelado. Puede ajustar la pregunta e intentarlo nuevamente.",
        "A análise foi cancelada pelo usuário.": "El análisis fue cancelado por el usuario.",
        "Tentar outra opção": "Probar otra opción",
        "Vamos tentar outra leitura da sua pergunta.": "Probemos otra lectura de su pregunta.",
        "Nao encontrei outra interpretacao pronta. Escolha a coluna que mais combina com a pergunta para eu recalcular.": "No encontré otra interpretación lista. Elija la columna que mejor coincide con la pregunta para que pueda recalcular.",
        (
            "Aba Resumo\n"
            "Objetivo: explorar uma camada em formato de tabela dinâmica, com agrupamentos, totais e leitura rápida dos campos.\n"
            "Quando usar: use esta aba quando quiser investigar os dados manualmente, comparar categorias ou montar uma visão tabular antes de gerar gráficos.\n"
            "Como fazer:\n"
            "1. Abra a aba Resumo no menu lateral.\n"
            "2. Escolha a camada que deseja analisar.\n"
            "3. Selecione campos, medidas e agrupamentos conforme a estrutura da camada.\n"
            "4. Use filtros e seleção de campos para refinar a tabela.\n"
            "5. Quando precisar de uma resposta conversada ou gráfico automático, volte para a aba Relatórios.\n"
            "Dica: a aba Resumo é melhor para conferência e exploração; a aba Relatórios é melhor para perguntas em linguagem natural."
        ): (
            "Pestaña Resumen\n"
            "Objetivo: explorar una capa como tabla dinámica, con agrupaciones, totales y lectura rápida de campos.\n"
            "Cuándo usarla: use esta pestaña para revisar datos manualmente, comparar categorías o preparar una vista tabular antes de generar gráficos.\n"
            "Cómo hacerlo:\n"
            "1. Abra la pestaña Resumen en el menú lateral.\n"
            "2. Elija la capa que desea analizar.\n"
            "3. Seleccione campos, medidas y agrupaciones según la estructura de la capa.\n"
            "4. Use filtros y selección de campos para refinar la tabla.\n"
            "5. Cuando necesite una respuesta conversacional o un gráfico automático, vuelva a la pestaña Informes.\n"
            "Consejo: Resumen es mejor para revisar y explorar; Informes es mejor para preguntas en lenguaje natural."
        ),
        (
            "Aba Relatórios\n"
            "Objetivo: transformar perguntas em análises, tabelas e gráficos automáticos usando as camadas do projeto.\n"
            "Quando usar: use esta aba quando quiser perguntar algo como totais, rankings, comparações, distribuições ou filtros por atributo.\n"
            "Como fazer:\n"
            "1. Digite a pergunta no campo do chat.\n"
            "2. Escolha uma ou mais camadas quando a janela de seleção aparecer.\n"
            "3. Clique em Analisar para executar a pergunta somente nas camadas marcadas.\n"
            "4. Se o chat tiver dúvida sobre a coluna correta, selecione uma das opções sugeridas.\n"
            "5. Continue perguntando: as camadas escolhidas permanecem em foco até você clicar em Limpar.\n"
            "Dica: para reiniciar tudo e escolher outras camadas, use o botão Limpar."
        ): (
            "Pestaña Informes\n"
            "Objetivo: convertir preguntas en análisis, tablas y gráficos automáticos usando las capas del proyecto.\n"
            "Cuándo usarla: use esta pestaña para obtener totales, rankings, comparaciones, distribuciones o filtros por atributo.\n"
            "Cómo hacerlo:\n"
            "1. Escriba la pregunta en el campo del chat.\n"
            "2. Elija una o más capas cuando aparezca la ventana de selección.\n"
            "3. Haga clic en Analizar para ejecutar la pregunta solo en las capas marcadas.\n"
            "4. Si el chat duda sobre la columna correcta, seleccione una de las opciones sugeridas.\n"
            "5. Siga preguntando: las capas elegidas permanecen activas hasta que haga clic en Limpiar.\n"
            "Consejo: para reiniciar todo y elegir otras capas, use el botón Limpiar."
        ),
        (
            "Aba Modelo/Dashboard\n"
            "Objetivo: organizar gráficos, cards e visuais em uma página de apresentação do projeto.\n"
            "Quando usar: use esta aba quando quiser montar um painel visual, posicionar elementos e preparar uma leitura executiva dos resultados.\n"
            "Como fazer:\n"
            "1. Gere um gráfico ou resultado na aba Relatórios.\n"
            "2. Use a opção de adicionar ao modelo quando ela estiver disponível.\n"
            "3. Na aba Modelo, organize os visuais no canvas.\n"
            "4. Ajuste tamanho, posição, aparência e leitura dos elementos.\n"
            "5. Volte à aba Relatórios sempre que precisar criar novas análises.\n"
            "Dica: pense nessa aba como a área de montagem final do dashboard."
        ): (
            "Pestaña Modelo/Dashboard\n"
            "Objetivo: organizar gráficos, tarjetas y visuales en una página de presentación del proyecto.\n"
            "Cuándo usarla: use esta pestaña para montar un panel visual, posicionar elementos y preparar una lectura ejecutiva de los resultados.\n"
            "Cómo hacerlo:\n"
            "1. Genere un gráfico o resultado en la pestaña Informes.\n"
            "2. Use la opción de agregar al modelo cuando esté disponible.\n"
            "3. En la pestaña Modelo, organice los visuales en el lienzo.\n"
            "4. Ajuste tamaño, posición, apariencia y legibilidad.\n"
            "5. Vuelva a Informes siempre que necesite crear nuevos análisis.\n"
            "Consejo: piense en esta pestaña como el área final de montaje del dashboard."
        ),
        (
            "Aba Conexões/Integrações\n"
            "Objetivo: centralizar origens externas e facilitar o acesso a dados que não estão diretamente no projeto.\n"
            "Quando usar: use esta área para configurar conexões, abrir fontes recentes ou preparar dados externos para análise.\n"
            "Como fazer:\n"
            "1. Abra a área de Conexões ou Integrações no plugin.\n"
            "2. Cadastre, selecione ou reabra uma origem de dados disponível.\n"
            "3. Carregue as camadas necessárias no projeto quando a origem exigir isso.\n"
            "4. Volte para a aba Relatórios e escolha o contexto correto no topo do chat.\n"
            "5. Faça a pergunta e selecione as camadas que devem ser analisadas.\n"
            "Dica: conexão prepara a origem; a análise acontece na aba Relatórios."
        ): (
            "Pestaña Conexiones/Integraciones\n"
            "Objetivo: centralizar fuentes externas y facilitar el acceso a datos que no están directamente en el proyecto.\n"
            "Cuándo usarla: use esta área para configurar conexiones, abrir fuentes recientes o preparar datos externos para análisis.\n"
            "Cómo hacerlo:\n"
            "1. Abra Conexiones o Integraciones en el plugin.\n"
            "2. Registre, seleccione o vuelva a abrir una fuente de datos disponible.\n"
            "3. Cargue las capas necesarias en el proyecto cuando la fuente lo requiera.\n"
            "4. Vuelva a Informes y elija el contexto correcto en la parte superior del chat.\n"
            "5. Haga la pregunta y seleccione las capas que deben analizarse.\n"
            "Consejo: la conexión prepara la fuente; el análisis ocurre en Informes."
        ),
        (
            "Aba Sobre\n"
            "Objetivo: apresentar informações institucionais e técnicas do Summarizer.\n"
            "Quando usar: use esta aba quando precisar conferir versão, descrição, suporte ou informações gerais do plugin.\n"
            "Como fazer:\n"
            "1. Abra Sobre no rodapé ou na área indicada do plugin.\n"
            "2. Consulte as informações exibidas sobre o produto.\n"
            "3. Use esses dados para suporte, validação de versão ou identificação do plugin.\n"
            "4. Para executar análises, volte para Relatórios, Resumo, Modelo ou Conexões.\n"
            "Dica: a aba Sobre é informativa; ela não altera seus dados nem executa consultas."
        ): (
            "Pestaña Acerca de\n"
            "Objetivo: presentar información institucional y técnica de Summarizer.\n"
            "Cuándo usarla: use esta pestaña para revisar versión, descripción, soporte o información general del plugin.\n"
            "Cómo hacerlo:\n"
            "1. Abra Acerca de en el pie o en el área indicada del plugin.\n"
            "2. Consulte la información mostrada sobre el producto.\n"
            "3. Use esos datos para soporte, validación de versión o identificación del plugin.\n"
            "4. Para ejecutar análisis, vuelva a Informes, Resumen, Modelo o Conexiones.\n"
            "Consejo: Acerca de es informativa; no altera sus datos ni ejecuta consultas."
        ),
        (
            "Contexto PostgreSQL\n"
            "Objetivo: direcionar perguntas para camadas carregadas a partir de uma conexão PostgreSQL/PostGIS.\n"
            "Quando usar: use este contexto quando a análise deve considerar dados do banco, e não todas as camadas do projeto.\n"
            "Como fazer:\n"
            "1. Configure ou carregue as camadas PostgreSQL no projeto.\n"
            "2. No topo do chat, abra o seletor de contexto.\n"
            "3. Escolha Banco PostgreSQL.\n"
            "4. Digite sua pergunta e selecione uma ou mais camadas PostgreSQL quando a janela aparecer.\n"
            "5. Clique em Analisar. As próximas perguntas continuam usando essas camadas até você clicar em Limpar.\n"
            "Dica: se nenhuma camada aparecer, verifique se a conexão está configurada e se as camadas foram carregadas no QGIS."
        ): (
            "Contexto PostgreSQL\n"
            "Objetivo: dirigir preguntas a capas cargadas desde una conexión PostgreSQL/PostGIS.\n"
            "Cuándo usarlo: use este contexto cuando el análisis debe considerar datos del banco y no todas las capas del proyecto.\n"
            "Cómo hacerlo:\n"
            "1. Configure o cargue las capas PostgreSQL en el proyecto.\n"
            "2. En la parte superior del chat, abra el selector de contexto.\n"
            "3. Elija Banco PostgreSQL.\n"
            "4. Escriba la pregunta y seleccione una o más capas PostgreSQL cuando aparezca la ventana.\n"
            "5. Haga clic en Analizar. Las próximas preguntas seguirán usando esas capas hasta que haga clic en Limpiar.\n"
            "Consejo: si no aparece ninguna capa, verifique que la conexión esté configurada y que las capas estén cargadas en QGIS."
        ),
        (
            "Seleção de camadas no chat\n"
            "Objetivo: garantir que a resposta seja calculada somente nas camadas escolhidas por você.\n"
            "Quando usar: sempre que a pergunta for sobre dados do projeto, o chat precisa saber quais camadas deve analisar.\n"
            "Como fazer:\n"
            "1. Digite a pergunta no chat.\n"
            "2. Quando a janela abrir, marque uma ou mais camadas.\n"
            "3. Clique em Analisar para confirmar a seleção.\n"
            "4. Continue perguntando normalmente; a seleção permanece ativa.\n"
            "5. Para trocar as camadas, clique em Limpar e faça uma nova pergunta.\n"
            "Dica: selecionar poucas camadas tende a gerar respostas mais precisas."
        ): (
            "Selección de capas en el chat\n"
            "Objetivo: garantizar que la respuesta se calcule solo con las capas elegidas por usted.\n"
            "Cuándo usarla: siempre que la pregunta sea sobre datos del proyecto, el chat necesita saber qué capas debe analizar.\n"
            "Cómo hacerlo:\n"
            "1. Escriba la pregunta en el chat.\n"
            "2. Cuando se abra la ventana, marque una o más capas.\n"
            "3. Haga clic en Analizar para confirmar la selección.\n"
            "4. Siga preguntando normalmente; la selección permanece activa.\n"
            "5. Para cambiar las capas, haga clic en Limpiar y haga una nueva pregunta.\n"
            "Consejo: seleccionar pocas capas suele generar respuestas más precisas."
        ),
        (
            "Gráficos e resultados visuais\n"
            "Objetivo: transformar uma resposta do chat em visualizações como barras, rankings, totais ou distribuições.\n"
            "Quando usar: use gráficos quando quiser apresentar padrões, comparar categorias ou destacar indicadores do projeto.\n"
            "Como fazer:\n"
            "1. Faça uma pergunta que gere uma métrica, contagem, soma, média, ranking ou agrupamento.\n"
            "2. Selecione as camadas que devem ser analisadas.\n"
            "3. Clique em Gerar ou Analisar.\n"
            "4. Revise o resultado visual criado pelo chat.\n"
            "5. Se quiser montar uma apresentação, adicione o visual ao Modelo/Dashboard.\n"
            "Dica: perguntas com 'por categoria', 'top 10', 'total por' ou 'quantidade por' costumam gerar bons gráficos."
        ): (
            "Gráficos y resultados visuales\n"
            "Objetivo: convertir una respuesta del chat en visualizaciones como barras, rankings, totales o distribuciones.\n"
            "Cuándo usarlos: use gráficos para presentar patrones, comparar categorías o destacar indicadores del proyecto.\n"
            "Cómo hacerlo:\n"
            "1. Haga una pregunta que genere una métrica, conteo, suma, promedio, ranking o agrupación.\n"
            "2. Seleccione las capas que deben analizarse.\n"
            "3. Haga clic en Generar o Analizar.\n"
            "4. Revise el resultado visual creado por el chat.\n"
            "5. Si desea montar una presentación, agregue el visual al Modelo/Dashboard.\n"
            "Consejo: preguntas con 'por categoría', 'top 10', 'total por' o 'cantidad por' suelen generar buenos gráficos."
        ),
        (
            "Filtros no chat\n"
            "Objetivo: limitar a análise a um conjunto específico de registros, usando colunas e valores das camadas selecionadas.\n"
            "Quando usar: use filtros quando quiser responder perguntas por local, status, categoria, tipo, data ou qualquer campo existente na camada.\n"
            "Como fazer:\n"
            "1. Escreva o filtro dentro da pergunta, por exemplo: por cidade, por status ou em determinado valor.\n"
            "2. O chat compara o texto com nomes de colunas e valores encontrados na camada.\n"
            "3. Se houver dúvida, ele mostra opções para você escolher a coluna correta.\n"
            "4. Depois da escolha, a consulta é recalculada somente com o filtro selecionado.\n"
            "Dica: quanto mais parecido o texto estiver com o nome da coluna ou valor real, melhor será a interpretação."
        ): (
            "Filtros en el chat\n"
            "Objetivo: limitar el análisis a un conjunto específico de registros usando columnas y valores de las capas seleccionadas.\n"
            "Cuándo usarlos: use filtros para responder preguntas por lugar, estado, categoría, tipo, fecha o cualquier campo existente en la capa.\n"
            "Cómo hacerlo:\n"
            "1. Escriba el filtro dentro de la pregunta, por ejemplo: por ciudad, por estado o con un valor específico.\n"
            "2. El chat compara el texto con nombres de columnas y valores encontrados en la capa.\n"
            "3. Si hay duda, muestra opciones para elegir la columna correcta.\n"
            "4. Después de elegir, la consulta se recalcula solo con el filtro seleccionado.\n"
            "Consejo: cuanto más parecido sea el texto al nombre real de la columna o valor, mejor será la interpretación."
        ),
        (
            "Botão Limpar\n"
            "Objetivo: reiniciar o contexto do chat com segurança.\n"
            "Quando usar: use Limpar quando quiser encerrar a análise atual, trocar as camadas em foco ou começar uma nova linha de perguntas.\n"
            "O que acontece:\n"
            "1. O histórico visível do chat é limpo.\n"
            "2. As camadas em foco são removidas.\n"
            "3. A memória da conversa atual é reiniciada.\n"
            "4. Na próxima pergunta de dados, o chat volta a pedir a seleção de camadas.\n"
            "Dica: Limpar não apaga suas camadas do QGIS; ele apenas reinicia o contexto do chat."
        ): (
            "Botón Limpiar\n"
            "Objetivo: reiniciar el contexto del chat con seguridad.\n"
            "Cuándo usarlo: use Limpiar para finalizar el análisis actual, cambiar las capas en foco o comenzar una nueva línea de preguntas.\n"
            "Qué ocurre:\n"
            "1. Se limpia el historial visible del chat.\n"
            "2. Se eliminan las capas en foco.\n"
            "3. Se reinicia la memoria de la conversación actual.\n"
            "4. En la próxima pregunta de datos, el chat vuelve a pedir la selección de capas.\n"
            "Consejo: Limpiar no borra sus capas de QGIS; solo reinicia el contexto del chat."
        ),
        (
            "Idioma e tradução\n"
            "Objetivo: permitir que o plugin seja usado em diferentes idiomas sem perder a lógica de análise.\n"
            "Como funciona:\n"
            "1. Você pode fazer perguntas em português ou inglês.\n"
            "2. O chat normaliza acentos, maiúsculas e sinais para comparar melhor os textos.\n"
            "3. Para perguntas sobre dados, ele prioriza nomes reais de camadas, colunas e valores do projeto.\n"
            "4. Para perguntas sobre o plugin, ele responde como guia de uso, sem pedir camada.\n"
            "5. As respostas de ajuda são preparadas para acompanhar o idioma selecionado no plugin.\n"
            "Dica: em consultas de dados, escrever próximo ao nome real da coluna sempre melhora o resultado."
        ): (
            "Idioma y traducción\n"
            "Objetivo: permitir que el plugin se use en diferentes idiomas sin perder la lógica de análisis.\n"
            "Cómo funciona:\n"
            "1. Puede hacer preguntas en portugués o inglés.\n"
            "2. El chat normaliza acentos, mayúsculas y signos para comparar mejor los textos.\n"
            "3. Para preguntas sobre datos, prioriza nombres reales de capas, columnas y valores del proyecto.\n"
            "4. Para preguntas sobre el plugin, responde como guía de uso sin pedir capa.\n"
            "5. Las respuestas de ayuda están preparadas para acompañar el idioma seleccionado en el plugin.\n"
            "Consejo: en consultas de datos, escribir parecido al nombre real de la columna siempre mejora el resultado."
        ),
        (
            "Ajuda do Summarizer\n"
            "Objetivo: orientar o uso do plugin sem executar consultas desnecessárias.\n"
            "Como funciona:\n"
            "1. Se a pergunta for sobre uma funcionalidade, o chat responde com explicação e passo a passo.\n"
            "2. Se a pergunta for sobre dados, o chat solicita as camadas que devem ser analisadas.\n"
            "3. As camadas escolhidas permanecem em foco até você clicar em Limpar.\n"
            "4. Você pode perguntar sobre Relatórios, Resumo, Modelo/Dashboard, Conexão, PostgreSQL ou Sobre.\n"
            "Dica: para obter uma orientação mais precisa, cite o nome da aba ou do comando que deseja entender."
        ): (
            "Ayuda de Summarizer\n"
            "Objetivo: orientar el uso del plugin sin ejecutar consultas innecesarias.\n"
            "Cómo funciona:\n"
            "1. Si la pregunta es sobre una funcionalidad, el chat responde con explicación y pasos.\n"
            "2. Si la pregunta es sobre datos, el chat solicita las capas que deben analizarse.\n"
            "3. Las capas elegidas permanecen en foco hasta que haga clic en Limpiar.\n"
            "4. Puede preguntar sobre Informes, Resumen, Modelo/Dashboard, Conexiones, PostgreSQL o Acerca de.\n"
            "Consejo: para una orientación más precisa, cite el nombre de la pestaña o comando que desea entender."
        ),
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
        ("Nova conexão PostgreSQL...", "New PostgreSQL connection..."),
        ("Nova conexao PostgreSQL...", "New PostgreSQL connection..."),
        ("Nova conexão PostgreSQL", "New PostgreSQL connection"),
        ("Nova conexao PostgreSQL", "New PostgreSQL connection"),
        ("Conexão PostgreSQL", "PostgreSQL connection"),
        ("Salvar senha junto com a conexão", "Save password together with the connection"),
        ("Abrir no Navegador", "Open in Browser"),
        ("Conexão '{name}' salva. Expanda o nó novamente para ver as tabelas.", "Connection '{name}' saved. Expand the node again to see the tables."),
        ("Conexão PostgreSQL adicionada via Navegador.", "PostgreSQL connection added via Browser."),
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
        ("Escolha uma fonte útil para fluxos de trabalho no QGIS: arquivos, bancos corporativos, camadas espaciais e dados web.", "Choose a useful source for QGIS workflows: files, corporate databases, spatial layers, and web data."),
        ("Excel", "Excel"),
        ("Arquivos XLSX e XLS", "XLSX and XLS files"),
        ("PostgreSQL", "PostgreSQL"),
        ("Tabelas e views", "Tables and views"),
        ("PostGIS", "PostGIS"),
        ("Camadas e tabelas espaciais", "Spatial layers and tables"),
        ("SQL Server", "SQL Server"),
        ("Dados corporativos", "Corporate data"),
        ("Oracle", "Oracle"),
        ("Ambientes corporativos", "Enterprise environments"),
        ("MySQL", "MySQL"),
        ("Aplicações e serviços", "Applications and services"),
        ("Google Sheets", "Google Sheets"),
        ("Planilhas web públicas", "Public web spreadsheets"),
        ("CSV / TXT", "CSV / TXT"),
        ("Arquivos delimitados", "Delimited files"),
        ("GeoPackage", "GeoPackage"),
        ("Camadas vetoriais", "Vector layers"),
        ("Área de transferência", "Clipboard"),
        ("Colar tabela copiada", "Paste copied table"),
        ("Recentes", "Recents"),
        ("Nenhuma conexão recente…", "No recent connection yet..."),
        ("Ver catálogo completo de fontes →", "View full data source catalog ->"),
        ("Catálogo de fontes disponíveis", "Available data source catalog"),
        ("Conector:", "Connector:"),
        ("Lembrar credenciais neste computador", "Remember credentials on this computer"),
        ("Carregar conexão salva…", "Load saved connection..."),
        ("Testar conexão", "Test connection"),
        ("Mostrar no Navegador", "Show in Browser"),
        ("Selecione uma tabela…", "Select a table..."),
        ("Driver PostgreSQL (QPSQL) não está disponível nesta instalação.", "PostgreSQL driver (QPSQL) is not available in this installation."),
        ("Driver SQL Server (QODBC) não está disponível nesta instalação.", "SQL Server driver (QODBC) is not available in this installation."),
        ("Driver Oracle (QOCI) não está disponível nesta instalação.", "Oracle driver (QOCI) is not available in this installation."),
        ("Driver MySQL (QMYSQL) não está disponível nesta instalação.", "MySQL driver (QMYSQL) is not available in this installation."),
        ("Conector de banco de dados não suportado nesta instalação.", "Database connector is not supported in this installation."),
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
        ("Converse com os dados do projeto", "Conversa con los datos del proyecto"),
        ("Faça perguntas sobre suas camadas e gere gráficos automaticamente", "Haz preguntas sobre tus capas y genera gráficos automáticamente"),
        ("Faça perguntas sobre suas camadas e gere graficos automaticamente", "Haz preguntas sobre tus capas y genera gráficos automáticamente"),
        ("Adicionar dados ao seu relatório", "Agrega datos a tu informe"),
        ("Adicionar dados ao seu relatorio", "Agrega datos a tu informe"),
        ("Escolha uma fonte útil para fluxos de trabalho no QGIS: arquivos, bancos corporativos, camadas espaciais e dados web.", "Elige una fuente útil para flujos de trabajo en QGIS: archivos, bases corporativas, capas espaciales y datos web."),
        ("Excel", "Excel"),
        ("Arquivos XLSX e XLS", "Archivos XLSX y XLS"),
        ("PostgreSQL", "PostgreSQL"),
        ("Tabelas e views", "Tablas y vistas"),
        ("PostGIS", "PostGIS"),
        ("Camadas e tabelas espaciais", "Capas y tablas espaciales"),
        ("SQL Server", "SQL Server"),
        ("Dados corporativos", "Datos corporativos"),
        ("Oracle", "Oracle"),
        ("Ambientes corporativos", "Entornos corporativos"),
        ("MySQL", "MySQL"),
        ("Aplicações e serviços", "Aplicaciones y servicios"),
        ("Google Sheets", "Google Sheets"),
        ("Planilhas web públicas", "Hojas web públicas"),
        ("CSV / TXT", "CSV / TXT"),
        ("Arquivos delimitados", "Archivos delimitados"),
        ("GeoPackage", "GeoPackage"),
        ("Camadas vetoriais", "Capas vectoriales"),
        ("Área de transferência", "Portapapeles"),
        ("Colar tabela copiada", "Pegar tabla copiada"),
        ("Recentes", "Recientes"),
        ("Nenhuma conexão recente…", "Aún no hay conexiones recientes..."),
        ("Ver catálogo completo de fontes →", "Ver catálogo completo de fuentes ->"),
        ("Catálogo de fontes disponíveis", "Catálogo de fuentes disponibles"),
        ("Conector:", "Conector:"),
        ("Lembrar credenciais neste computador", "Recordar credenciales en este equipo"),
        ("Carregar conexão salva…", "Cargar conexión guardada..."),
        ("Testar conexão", "Probar conexión"),
        ("Mostrar no Navegador", "Mostrar en el navegador"),
        ("Selecione uma tabela…", "Seleccione una tabla..."),
        ("Driver PostgreSQL (QPSQL) não está disponível nesta instalação.", "El controlador PostgreSQL (QPSQL) no está disponible en esta instalación."),
        ("Driver SQL Server (QODBC) não está disponível nesta instalação.", "El controlador SQL Server (QODBC) no está disponible en esta instalación."),
        ("Driver Oracle (QOCI) não está disponível nesta instalação.", "El controlador Oracle (QOCI) no está disponible en esta instalación."),
        ("Driver MySQL (QMYSQL) não está disponível nesta instalação.", "El controlador MySQL (QMYSQL) no está disponible en esta instalación."),
        ("Conector de banco de dados não suportado nesta instalação.", "El conector de base de datos no es compatible con esta instalación."),
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
        forced = str(QSettings().value("Summarizer/uiLocale", "auto") or "auto").strip()
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


