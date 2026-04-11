from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsMapLayerProxyModel
from qgis.gui import QgsMapLayerComboBox

from .utils.resources import svg_icon


class Ui_PowerBISummarizerDialog(object):
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.resize(1200, 800)
        Dialog.setWindowTitle("Power BI Summarizer - QGIS")

        self.verticalLayout = QVBoxLayout(Dialog)
        self.verticalLayout.setContentsMargins(6, 6, 6, 6)
        self.verticalLayout.setSpacing(6)

        self.header_widget = QFrame()
        self.header_widget.setObjectName("headerBar")
        self.header_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(10)

        self.logo_label = QLabel()
        logo_icon = svg_icon("PowerPages.svg")
        if not logo_icon.isNull():
            self.logo_label.setPixmap(logo_icon.pixmap(QSize(40, 40)))
        header_layout.addWidget(self.logo_label, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self.title_label = QLabel("Power BI Summarizer")
        self.title_label.setProperty("role", "appTitle")
        header_layout.addWidget(self.title_label, 0, Qt.AlignLeft | Qt.AlignVCenter)
        header_layout.addStretch()

        self.minimize_btn = QToolButton()
        self.minimize_btn.setText("Min")
        self.minimize_btn.setToolTip("Minimizar")
        self.minimize_btn.setAutoRaise(True)
        self.minimize_btn.setCursor(Qt.PointingHandCursor)
        header_layout.addWidget(self.minimize_btn, 0, Qt.AlignRight | Qt.AlignVCenter)

        self.maximize_btn = QToolButton()
        self.maximize_btn.setText("Max")
        self.maximize_btn.setToolTip("Maximizar")
        self.maximize_btn.setAutoRaise(True)
        self.maximize_btn.setCursor(Qt.PointingHandCursor)
        header_layout.addWidget(self.maximize_btn, 0, Qt.AlignRight | Qt.AlignVCenter)

        self.verticalLayout.addWidget(self.header_widget)

        self.ribbon_bar = QFrame()
        self.ribbon_bar.setObjectName("ribbonBar")
        self.ribbon_bar.setFixedHeight(68)
        self.ribbon_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        ribbon_layout = QHBoxLayout(self.ribbon_bar)
        ribbon_layout.setContentsMargins(8, 6, 8, 6)
        ribbon_layout.setSpacing(12)

        def make_separator():
            line = QFrame(self.ribbon_bar)
            line.setFrameShape(QFrame.VLine)
            line.setFrameShadow(QFrame.Plain)
            line.setObjectName("ribbonSeparator")
            line.setFixedWidth(1)
            return line

        def make_group(title: str):
            group = QFrame(self.ribbon_bar)
            group.setProperty("ribbonGroup", True)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(4, 0, 4, 0)
            group_layout.setSpacing(4)
            title_label = QLabel(title, group)
            title_label.setProperty("ribbonGroupTitle", True)
            group_layout.addWidget(title_label, 0, Qt.AlignLeft)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            group_layout.addLayout(row)
            return group, row

        def make_button(text: str, icon: QIcon):
            btn = QToolButton(self.ribbon_bar)
            btn.setProperty("ribbonButton", True)
            btn.setText(text)
            btn.setIcon(icon)
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setIconSize(QSize(20, 20))
            btn.setAutoRaise(False)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumWidth(88)
            btn.setFixedHeight(56)
            btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            btn.setToolTip(text.replace("\n", " "))
            return btn

        def icon(name: str) -> QIcon:
            return svg_icon(name)

        dados_group, dados_row = make_group("Dados")
        self.ribbon_get_data_btn = make_button("Dados", icon("Import.svg"))
        self.ribbon_get_data_btn.setToolTip("Obter dados para o modelo")
        dados_row.addWidget(self.ribbon_get_data_btn)
        ribbon_layout.addWidget(dados_group, 0, Qt.AlignVCenter)

        ribbon_layout.addStretch(1)
        self.verticalLayout.addWidget(self.ribbon_bar)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.progress_bar.setFixedHeight(14)
        self.verticalLayout.addWidget(self.progress_bar)

        self.central_frame = QFrame()
        central_layout = QHBoxLayout(self.central_frame)
        central_layout.setContentsMargins(0, 4, 0, 4)
        central_layout.setSpacing(8)

        self.sidebar_container = QFrame()
        self.sidebar_container.setObjectName("sidebarContainer")
        sidebar_layout = QVBoxLayout(self.sidebar_container)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(12)
        self.sidebar_container.setMaximumWidth(72)
        self.sidebar_container.setMinimumWidth(64)
        central_layout.addWidget(self.sidebar_container, 0, Qt.AlignTop)

        self.content_frame = QFrame()
        content_layout = QVBoxLayout(self.content_frame)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        self.stackedWidget = QStackedWidget()
        content_layout.addWidget(self.stackedWidget, 1)
        central_layout.addWidget(self.content_frame, 1)

        self.pageResultados = QWidget()
        self.pageResultados.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        resultados_layout = QVBoxLayout(self.pageResultados)
        resultados_layout.setContentsMargins(0, 0, 0, 0)
        resultados_layout.setSpacing(12)
        resultados_layout.setSizeConstraint(QLayout.SetNoConstraint)

        self.results_header_frame = QFrame()
        header_layout = QVBoxLayout(self.results_header_frame)
        header_layout.setContentsMargins(16, 16, 16, 8)
        header_layout.setSpacing(10)

        layer_row = QHBoxLayout()
        self.layer_label = QLabel("Camada:")
        layer_row.addWidget(self.layer_label)
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(QgsMapLayerProxyModel.VectorLayer)
        layer_row.addWidget(self.layer_combo, 1)
        header_layout.addLayout(layer_row)

        actions_row = QHBoxLayout()
        self.auto_update_check = QCheckBox("Atualização automática")
        self.auto_update_check.setChecked(True)
        self.auto_update_check.setProperty("role", "helper")
        actions_row.addWidget(self.auto_update_check)
        actions_row.addStretch()
        self.dashboard_btn = QPushButton("Dashboard Interativo")
        self.dashboard_btn.setProperty("variant", "secondary")
        actions_row.addWidget(self.dashboard_btn)
        header_layout.addLayout(actions_row)

        resultados_layout.addWidget(self.results_header_frame)

        self.results_body = QFrame()
        self.results_body.setObjectName("resultsBody")
        self.results_body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.results_body_layout = QVBoxLayout(self.results_body)
        self.results_body_layout.setContentsMargins(0, 0, 0, 0)
        self.results_body_layout.setSpacing(12)
        self.results_body_layout.setSizeConstraint(QLayout.SetNoConstraint)
        resultados_layout.addWidget(self.results_body, 1)

        self.export_card = QFrame()
        self.export_card.setObjectName("exportCard")
        self.export_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        export_layout = QVBoxLayout(self.export_card)
        export_layout.setContentsMargins(16, 16, 16, 16)
        export_layout.setSpacing(12)

        self.export_info_label = QLabel("Configure o formato e o destino para exportar o resumo.")
        self.export_info_label.setWordWrap(True)
        self.export_info_label.setProperty("role", "helper")
        export_layout.addWidget(self.export_info_label)

        export_form_layout = QGridLayout()
        export_form_layout.addWidget(QLabel("Formato:"), 0, 0)
        self.export_format_combo = QComboBox()
        export_form_layout.addWidget(self.export_format_combo, 0, 1, 1, 2)

        export_form_layout.addWidget(QLabel("Arquivo de destino:"), 1, 0)
        self.export_path_edit = QLineEdit()
        self.export_path_edit.setPlaceholderText("Selecione o arquivo de destino...")
        export_form_layout.addWidget(self.export_path_edit, 1, 1)
        self.export_browse_btn = QPushButton("Procurar...")
        self.export_browse_btn.setProperty("variant", "secondary")
        export_form_layout.addWidget(self.export_browse_btn, 1, 2)

        export_layout.addLayout(export_form_layout)

        self.export_include_timestamp_check = QCheckBox("Adicionar data e hora ao nome do arquivo")
        self.export_include_timestamp_check.setChecked(True)
        self.export_include_timestamp_check.setProperty("role", "helper")
        export_layout.addWidget(self.export_include_timestamp_check)

        export_button_layout = QHBoxLayout()
        export_button_layout.addStretch()
        self.export_execute_btn = QPushButton("Exportar")
        export_button_layout.addWidget(self.export_execute_btn)
        export_layout.addLayout(export_button_layout)

        self.export_card.setVisible(False)
        self.stackedWidget.addWidget(self.pageResultados)

        self.pageRelatorios = QWidget()
        relatorios_layout = QVBoxLayout(self.pageRelatorios)
        relatorios_layout.setContentsMargins(0, 0, 0, 0)
        relatorios_layout.setSpacing(0)

        self.stackedWidget.addWidget(self.pageRelatorios)

        self.pageModel = QWidget()
        model_layout = QVBoxLayout(self.pageModel)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.setSpacing(0)

        self.stackedWidget.addWidget(self.pageModel)

        self.pageIntegracao = QWidget()
        integracao_layout = QVBoxLayout(self.pageIntegracao)
        integracao_layout.setContentsMargins(0, 0, 0, 0)
        integracao_layout.setSpacing(12)

        self.integration_placeholder = QLabel("Integrações externas serão exibidas aqui.")
        self.integration_placeholder.setAlignment(Qt.AlignCenter)
        self.integration_placeholder.setProperty("role", "helper")

        integracao_layout.addStretch()
        integracao_layout.addWidget(self.integration_placeholder)
        integracao_layout.addStretch()

        self.stackedWidget.addWidget(self.pageIntegracao)

        self.verticalLayout.addWidget(self.central_frame, 1)

        self.footer_bar = QFrame()
        self.footer_bar.setObjectName("footerBar")
        footer_layout = QHBoxLayout(self.footer_bar)
        footer_layout.setContentsMargins(12, 8, 12, 8)
        footer_layout.setSpacing(8)

        footer_layout.addStretch()
        self.manage_connections_btn = QPushButton("Gerenciar conexões")
        self.manage_connections_btn.setProperty("variant", "secondary")
        self.manage_connections_btn.setVisible(False)
        footer_layout.addWidget(self.manage_connections_btn)

        self.footer_about_btn = QPushButton("Sobre")
        self.footer_about_btn.setProperty("variant", "secondary")
        footer_layout.addWidget(self.footer_about_btn)

        self.verticalLayout.addWidget(self.footer_bar)

        self.stackedWidget.setCurrentWidget(self.pageResultados)
