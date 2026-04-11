import base64
import os
import re
from datetime import datetime
from typing import Dict, Optional, List
from string import Template

import numpy as np
import pandas as pd
from pandas.api import types as ptypes
from qgis.PyQt.QtCore import QBuffer, QCoreApplication, QSettings, QTimer, QTranslator, Qt, QVariant, QRectF
from qgis.PyQt.QtGui import QFont, QImage, QPainter
from qgis.PyQt.QtWidgets import (
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QFrame,
)

from .report_view.visuals import BarChartRenderer, VisualDefinition, VisualTheme
from qgis.core import (
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsMapLayerProxyModel,
    QgsGeometry,
    QgsMapLayerStyle,
    QgsProject,
    QgsMessageLog,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
    Qgis,
)

from .dashboard_widget import DashboardWidget
from .model_tab import ModelTab
from .export_manager import ExportManager
from .result_style import apply_result_style
from .ui_main_dialog import Ui_PowerBISummarizerDialog
from .layout_nav import SidebarController
from .integration_panel import IntegrationPanel, DatabaseImportDialog
from .interactive_table import InteractiveTable
from .pivot_table_widget import PivotTableWidget
from .palette import palette_context
from .slim_dialogs import SlimDialogBase, SlimLayerSelectionDialog, slim_get_item
from .utils.resources import svg_icon
from .browser_integration import (
    register_browser_provider,
    unregister_browser_provider,
    connection_registry,
)
from .model_view import ModelCanvasScene, ModelCanvasView, ModelManager
from .cloud_session import cloud_session
from .report_view import ReportsWidget
from .utils.plugin_logging import log_error

PROTECTED_COLUMNS_DEFAULT = {"__feature_id", "__geometry_wkb", "__target_feature_id"}


def __apply_theme_once(target):
    """Tenta aplicar o stylesheet do plugin uma única vez."""
    try:
        base_dir = os.path.dirname(__file__)
        qss_path = os.path.join(base_dir, "resources", "style.qss")
        if os.path.exists(qss_path):
            with open(qss_path, "r", encoding="utf-8") as handler:
                qss = handler.read()
            try:
                qss = Template(qss).safe_substitute(palette_context())
            except Exception:
                pass
            if hasattr(target, "iface") and hasattr(target.iface, "mainWindow"):
                target.iface.mainWindow().setStyleSheet(qss)
            elif hasattr(target, "setStyleSheet"):
                target.setStyleSheet(qss)
    except Exception:
        pass


class PowerBISummarizer:
    def __init__(self, iface):
        try:
            __apply_theme_once(self)
        except Exception:
            pass

        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)

        locale = QSettings().value("locale/userLocale")[0:2]
        locale_path = os.path.join(
            self.plugin_dir, "i18n", f"PowerBISummarizer_{locale}.qm"
        )
        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        self.actions = []
        self.menu = self.tr("Power BI Summarizer")
        self.dlg = None
        self._browser_provider = None

    def tr(self, message):
        return QCoreApplication.translate("PowerBISummarizer", message)

    def initGui(self):
        plugin_icon = svg_icon("PowerPages.svg")
        self.action = QAction(
            plugin_icon,
            self.tr("Power BI Summarizer"),
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.run)
        self.action.setWhatsThis(
            self.tr("Resume dados de diferentes camadas como no Power BI")
        )

        self.actions.append(self.action)
        self.iface.addPluginToMenu(self.menu, self.action)
        self.iface.addToolBarIcon(self.action)

        # Add Integration menu action (standalone page)
        self.integration_action = QAction(
            plugin_icon,
            self.tr("Integração / Fontes Externas"),
            self.iface.mainWindow(),
        )
        self.integration_action.triggered.connect(self.open_integration_dialog)
        self.actions.append(self.integration_action)
        self.iface.addPluginToMenu(self.menu, self.integration_action)

        try:
            if self._browser_provider is None:
                self._browser_provider = register_browser_provider()
        except Exception as exc:
            self._browser_provider = None
            message = f"Falha ao registrar nó PowerBI Summarizer no Navegador: {exc}"
            QgsMessageLog.logMessage(message, "PowerBISummarizer", Qgis.Critical)
            log_error(message)

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
        if self._browser_provider is not None:
            try:
                unregister_browser_provider(self._browser_provider)
            finally:
                self._browser_provider = None

    def run(self):
        try:
            __apply_theme_once(self)
        except Exception:
            pass

        if not self.dlg:
            self.dlg = PowerBISummarizerDialog(self.iface)
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()

    def open_integration_dialog(self):
        # Open as a full page inside the main plugin dialog, similar to 'Sobre'
        try:
            if not self.dlg:
                self.dlg = PowerBISummarizerDialog(self.iface)
            self.dlg.show()
            self.dlg.raise_()
            self.dlg.activateWindow()
            if hasattr(self.dlg, "sidebar") and self.dlg.sidebar:
                try:
                    self.dlg.sidebar.show_integration_page()
                except Exception:
                    pass
        except Exception as exc:
            QMessageBox.critical(self.iface.mainWindow(), "Integração", f"Falha ao abrir: {exc}")

    # Exposed to SidebarController to open the in-dialog full page
    def open_external_integration_dialog(self):
        try:
            if not self.dlg:
                self.dlg = PowerBISummarizerDialog(self.iface)
            self.dlg.show()
            self.dlg.raise_()
            self.dlg.activateWindow()
            if hasattr(self.dlg, "sidebar") and self.dlg.sidebar:
                self.dlg.sidebar.show_integration_page()
        except Exception as exc:
            QMessageBox.critical(self, "Integração", f"Falha ao abrir: {exc}")

    def _get_layer_by_name(self, layer_name: str):
        """Retorna a primeira camada cujo nome corresponde exatamente ao informado."""
        if not layer_name:
            return None

        matches = QgsProject.instance().mapLayersByName(layer_name)
        return matches[0] if matches else None


class PowerBISummarizerDialog(QDialog):
    def __init__(self, iface):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.ui = Ui_PowerBISummarizerDialog()
        self.ui.setupUi(self)
        self._square_scopes = []
        for attr in ("pageResultados",):
            scope = getattr(self.ui, attr, None)
            if scope is not None:
                scope.setProperty("squareScope", True)
                self._square_scopes.append(scope)
        self._square_theme_applied = False
        try:
            self.ui.minimize_btn.clicked.connect(self.showMinimized)
            self.ui.maximize_btn.clicked.connect(self.toggle_window_state)
        except Exception:
            pass

        # External integration state (not used in main dialog anymore)
        self.external_df = None
        self.external_last_path_key = "PowerBISummarizer/external/lastPath"

        self.setWindowIcon(svg_icon("PowerPages.svg"))

        context = palette_context()
        base_font = QFont(context.get("font_family", "Segoe UI"))
        base_font.setPixelSize(int(context.get("font_body_px", 13)))
        base_font.setWeight(QFont.Normal)
        self.setFont(base_font)

        self.export_manager = ExportManager()
        self.dashboard_widget = DashboardWidget()
        try:
            self.dashboard_widget.primary_chart.addToModelRequested.connect(self.handle_add_chart_to_model_request)
            self.dashboard_widget.secondary_chart.addToModelRequested.connect(self.handle_add_chart_to_model_request)
        except Exception:
            pass
        # Inject QuickOSM-like sidebar navigation without altering the ui file
        try:
            self.sidebar = SidebarController(self)
        except Exception:
            self.sidebar = None
        try:
            self._set_ribbon_visible(False)
        except Exception:
            pass

        self.export_formats = {
            "Excel (.xlsx)": {"filter": "Excel (*.xlsx)", "extension": ".xlsx"},
            "CSV (.csv)": {"filter": "CSV (*.csv)", "extension": ".csv"},
            "PDF (.pdf)": {"filter": "PDF (*.pdf)", "extension": ".pdf"},
            "JSON (.json)": {"filter": "JSON (*.json)", "extension": ".json"},
        }
        self._timestamp_pattern = re.compile(r"_\d{8}_\d{6}$")
        self._updating_export_path = False
        self._export_base_path = ""

        self.current_summary_data = None
        self.integration_datasets: Dict[str, pd.DataFrame] = {}
        self._active_numeric_field = None

        self.ui.export_format_combo.addItems(self.export_formats.keys())
        self.ui.export_format_combo.setCurrentIndex(0)

        self._apply_card_markers()

        # Prepare widgets for the Results view
        try:
            layout = self.ui.results_body_layout
            self.pivot_widget = PivotTableWidget(iface=self.iface, parent=self.ui.results_body, host=self)
            self.pivot_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            layout.addWidget(self.pivot_widget)
            try:
                self.pivot_widget.set_layer_combo(self.ui.layer_combo)
            except Exception:
                pass
            try:
                self.pivot_widget.set_auto_update_checkbox(self.ui.auto_update_check)
            except Exception:
                pass
            try:
                self.pivot_widget.add_dashboard_button(self.ui.dashboard_btn)
            except Exception:
                pass
            try:
                self.ui.results_header_frame.setVisible(False)
            except Exception:
                pass

            self.summary_message_widget = QTextEdit(self.ui.results_body)
            self.summary_message_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.summary_message_widget.setReadOnly(True)
            self.summary_message_widget.setStyleSheet(
                Template(
                    "font-family: ${font_ui_stack}; font-size: ${font_body_px}px;"
                ).safe_substitute(context)
            )
            self.summary_message_widget.setVisible(False)
            layout.addWidget(self.summary_message_widget)

            self.table_view = InteractiveTable(self.ui.results_body)
            self.table_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            layout.addWidget(self.table_view)
            self.table_view.setVisible(False)
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Falha ao construir a aba de tabela dinamica: {exc}",
                "PowerBISummarizer",
                Qgis.Critical,
            )
            self.pivot_widget = None
            self.summary_message_widget = None
            self.table_view = None

        self.setup_connections()
        self.load_layers()
        self.apply_styles()
        self.on_export_format_changed()

        try:
            self.show_summary_prompt()
        except Exception:
            pass
        QTimer.singleShot(0, self._reset_initial_summary_layer_selection)

        self.model_manager = None
        self._model_backend_host = QWidget(self)
        self._model_backend_host.hide()
        self._model_scene = ModelCanvasScene(self._model_backend_host)
        self._model_view = ModelCanvasView(self._model_scene, self._model_backend_host)
        try:
            self.model_manager = ModelManager(self._model_scene, self._model_view, self)
            self.model_manager.refresh_model()
        except Exception:
            self.model_manager = None

        try:
            self._init_ribbon_actions()
        except Exception:
            pass

        self.reports_widget = None
        try:
            layout = self.ui.pageRelatorios.layout()
            if layout is None:
                layout = QVBoxLayout(self.ui.pageRelatorios)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)

            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

            widget = ReportsWidget(plugin=self, parent=self.ui.pageRelatorios)
            layout.addWidget(widget)
            self.reports_widget = widget
        except Exception:
            self.reports_widget = None

        self.model_tab = None
        try:
            layout = self.ui.pageModel.layout()
            if layout is None:
                layout = QVBoxLayout(self.ui.pageModel)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)

            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

            widget = ModelTab(parent=self.ui.pageModel)
            layout.addWidget(widget)
            self.model_tab = widget
        except Exception:
            self.model_tab = None

        self.integration_panel = None
        self.integration_scroll = None
        try:
            layout = self.ui.pageIntegracao.layout()
            if layout is None:
                layout = QVBoxLayout(self.ui.pageIntegracao)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)

            placeholder = getattr(self.ui, "integration_placeholder", None)
            if placeholder is not None:
                layout.removeWidget(placeholder)
                placeholder.deleteLater()
                self.ui.integration_placeholder = None

            scroll = QScrollArea(self.ui.pageIntegracao)
            scroll.setObjectName("integrationScrollArea")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            layout.addWidget(scroll, 1)
            self.integration_scroll = scroll

            panel = IntegrationPanel(self, self.iface)
            scroll.setWidget(panel)
            self.integration_panel = panel

            manage_btn = getattr(self.ui, "manage_connections_btn", None)
            if manage_btn is not None:
                manage_btn.clicked.connect(panel.open_connections_manager)
        except Exception:
            self.integration_panel = None
    def toggle_window_state(self):
        if self.isMaximized():
            self.showNormal()
            try:
                self.ui.maximize_btn.setText("Max")
                self.ui.maximize_btn.setToolTip("Maximizar")
            except Exception:
                pass
        else:
            self.showMaximized()
            try:
                self.ui.maximize_btn.setText("Res")
                self.ui.maximize_btn.setToolTip("Restaurar")
            except Exception:
                pass

    # ---------------------------------------------------------------- Ribbon
    def _init_ribbon_actions(self):
        ui = self.ui
        btn = getattr(ui, "ribbon_get_data_btn", None)
        if btn is not None:
            btn.clicked.connect(self.open_get_data_dialog)
        self._set_ribbon_visible(False)

    def _set_ribbon_visible(self, visible: bool):
        bar = getattr(self.ui, "ribbon_bar", None)
        if bar is None:
            return
        bar.setVisible(bool(visible))
        # Garantir que o stack de páginas nunca seja ocultado
        stacked = getattr(self.ui, "stackedWidget", None)
        if stacked is not None:
            stacked.setVisible(True)
        central = getattr(self.ui, "central_frame", None)
        if central is not None:
            central.setVisible(True)

    def _apply_card_markers(self):
        """Marca frames e layouts para o tema de cards."""
        cards = [
            getattr(self.ui, "results_header_frame", None),
            getattr(self.ui, "results_body", None),
            getattr(self.ui, "export_card", None),
        ]
        for card in cards:
            if card is not None:
                card.setProperty("card", True)

        titles = [
            getattr(self.ui, "export_info_label", None),
        ]
        for label in titles:
            if label is not None:
                label.setProperty("cardTitle", True)

        layout = getattr(self.ui, "results_body_layout", None)
        if layout is not None:
            layout.setContentsMargins(2, 2, 2, 2)
            layout.setSpacing(4)

    def apply_styles(self):
        """Aplica o style.qss oficial do plugin (arquivo principal de temas)."""
        style_path = os.path.join(os.path.dirname(__file__), "resources", "style.qss")
        if not os.path.exists(style_path):
            self._apply_square_theme()
            return

        try:
            with open(style_path, "r", encoding="utf-8") as handler:
                template = Template(handler.read())
            context = palette_context()
            self.setStyleSheet(template.safe_substitute(context))
        except Exception:
            try:
                with open(style_path, "r", encoding="utf-8") as handler:
                    self.setStyleSheet(handler.read())
            except Exception:
                pass
        if getattr(self, "sidebar", None) is not None:
            try:
                self.sidebar.refresh_styles()
            except Exception:
                pass
        self._apply_square_theme()

    def _apply_square_theme(self):
        if getattr(self, "_square_theme_applied", False):
            return
        if not getattr(self, "_square_scopes", None):
            return
        square_path = os.path.join(os.path.dirname(__file__), "ui", "square.qss")
        if not os.path.exists(square_path):
            return
        try:
            with open(square_path, "r", encoding="utf-8") as handler:
                square_qss = handler.read()
        except Exception:
            return
        existing = self.styleSheet() or ""
        combined = f"{existing}\n{square_qss}" if existing else square_qss
        self.setStyleSheet(combined)
        self._square_theme_applied = True

    def set_model_toolbar_visible(self, visible: bool):
        self._set_ribbon_visible(bool(visible))

    def setup_connections(self):
        self.ui.layer_combo.layerChanged.connect(self.on_layer_changed)
        self.ui.dashboard_btn.clicked.connect(self.show_dashboard)

        self.ui.export_execute_btn.clicked.connect(self.export_results)
        self.ui.export_browse_btn.clicked.connect(self.choose_export_path)
        self.ui.export_format_combo.currentIndexChanged.connect(
            self.on_export_format_changed
        )
        self.ui.export_path_edit.editingFinished.connect(self.on_export_path_edited)
        self.ui.footer_about_btn.clicked.connect(self.show_about_dialog)

        # External integration connections removed (handled by dedicated dialog)

    def _set_results_view(self, mode: str):
        """Switch between pivot (summary), message (HTML) and table (comparison) views."""
        pivot_visible = mode == "pivot"
        message_visible = mode == "message"
        table_visible = mode == "table"

        pivot_widget = getattr(self, "pivot_widget", None)
        if pivot_widget is not None:
            pivot_widget.setVisible(pivot_visible)

        message_widget = getattr(self, "summary_message_widget", None)
        if message_widget is not None:
            message_widget.setVisible(message_visible)

        table_widget = getattr(self, "table_view", None)
        if table_widget is not None:
            table_widget.setVisible(table_visible)

    def show_results_message(self, html: str):
        """Display HTML content in the results area."""
        message_widget = getattr(self, "summary_message_widget", None)
        if message_widget is None:
            return
        try:
            message_widget.setHtml(apply_result_style(html))
        except Exception:
            message_widget.setHtml(html)
        self._set_results_view("message")

    def show_summary_prompt(self):
        self._set_ribbon_visible(False)
        self._set_integration_footer_visible(False)
        pivot = getattr(self, "pivot_widget", None)
        if pivot is not None:
            try:
                pivot.show_welcome_prompt()
                self._set_results_view("pivot")
                return
            except Exception:
                pass
        self.show_results_message(
            "<p style='margin:8px 0;'>Selecione uma camada e clique em Gerar Resumo.</p>"
        )

    def _reset_initial_summary_layer_selection(self):
        combo = getattr(self.ui, "layer_combo", None)
        if combo is None:
            return
        try:
            combo.blockSignals(True)
            try:
                combo.setCurrentLayer(None)
            except Exception:
                pass
            try:
                combo.setCurrentIndex(-1)
            except Exception:
                pass
        finally:
            try:
                combo.blockSignals(False)
            except Exception:
                pass
        self._active_numeric_field = None

    def _set_integration_footer_visible(self, visible: bool):
        btn = getattr(self.ui, "manage_connections_btn", None)
        if btn is not None:
            btn.setVisible(bool(visible))

    def show_integration_page(self):
        self._set_ribbon_visible(False)
        try:
            self.ui.stackedWidget.setCurrentWidget(self.ui.pageIntegracao)
        except Exception:
            pass
        scroll = getattr(self, "integration_scroll", None)
        if scroll is not None:
            try:
                scroll.verticalScrollBar().setValue(0)
            except Exception:
                pass
        self._set_integration_footer_visible(True)
        panel = getattr(self, "integration_panel", None)
        if panel is not None:
            try:
                panel.refresh_recents()
            except Exception:
                pass

    def show_reports_page(self):
        self._set_ribbon_visible(False)
        try:
            self.ui.stackedWidget.setCurrentWidget(self.ui.pageRelatorios)
        except Exception:
            pass

    def show_model_page(self):
        self._set_ribbon_visible(False)
        try:
            self.ui.stackedWidget.setCurrentWidget(self.ui.pageModel)
        except Exception:
            pass

    def handle_add_chart_to_model_request(self, snapshot):
        model_tab = getattr(self, "model_tab", None)
        if model_tab is None or not snapshot:
            return
        added = False
        try:
            added = bool(model_tab.prompt_add_chart(dict(snapshot or {})))
        except Exception as exc:
            QMessageBox.warning(self, "Model", f"Nao foi possivel adicionar o grafico ao Model: {exc}")
            return
        if not added:
            return
        try:
            if getattr(self, "sidebar", None) is not None:
                self.sidebar.show_model_page()
            else:
                self.show_model_page()
        except Exception:
            self.show_model_page()

    def open_get_data_dialog(self):
        dialog = GetDataDialog(self, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        datasets = dialog.results()
        if not datasets:
            return
        for df, metadata in datasets:
            try:
                self.register_integration_dataframe(df, metadata)
            except Exception as exc:
                QMessageBox.warning(self, "Obter Dados", f"Falha ao registrar dados: {exc}")
        try:
            self.sidebar.show_reports_page()
        except Exception:
            self.show_reports_page()

    def register_integration_dataframe(self, df: pd.DataFrame, metadata: Dict) -> Dict:
        if df is None or df.empty:
            return {}

        descriptor = dict(metadata or {})
        descriptor.setdefault("display_name", descriptor.get("source_path") or "Dados externos")
        descriptor.setdefault("connector", descriptor.get("connector") or "Fonte externa")
        descriptor.setdefault("record_count", int(len(df)))
        descriptor.setdefault("timestamp", descriptor.get("timestamp") or datetime.now().isoformat())

        summary_data = self._build_dataframe_summary(df, descriptor)
        self.current_summary_data = summary_data
        self.display_advanced_summary(summary_data)
        self.update_charts_preview(summary_data)
        self.prepare_export_tab_defaults(summary_data)

        layer = self._create_memory_table_from_dataframe(df, descriptor)
        if layer is not None and layer.isValid():
            descriptor["layer_id"] = layer.id()
            descriptor["layer_name"] = layer.name()
            self.integration_datasets[layer.id()] = df.copy()
            try:
                if self.model_manager is not None:
                    self.model_manager.refresh_model()
            except Exception:
                pass
            try:
                if self.reports_widget is not None:
                    self.reports_widget.refresh_from_model()
            except Exception:
                pass

        self.sidebar.show_results_page()
        self._set_integration_footer_visible(False)
        return descriptor

    def _build_dataframe_summary(self, df: pd.DataFrame, descriptor: Dict) -> Dict:
        numeric_columns = [col for col in df.columns if ptypes.is_numeric_dtype(df[col])]
        stats = {
            "total": 0.0,
            "count": int(len(df)),
            "average": 0.0,
            "min": 0.0,
            "max": 0.0,
            "median": 0.0,
            "std_dev": 0.0,
        }
        percentiles = {}

        if numeric_columns:
            series = pd.to_numeric(df[numeric_columns[0]], errors="coerce").dropna()
            if not series.empty:
                stats.update(
                    {
                        "total": float(series.sum()),
                        "average": float(series.mean()),
                        "min": float(series.min()),
                        "max": float(series.max()),
                        "median": float(series.median()),
                        "std_dev": float(series.std()),
                    }
                )
                percentiles = {
                    "p25": float(series.quantile(0.25)),
                    "p50": float(series.quantile(0.50)),
                    "p75": float(series.quantile(0.75)),
                    "p90": float(series.quantile(0.90)),
                    "p95": float(series.quantile(0.95)),
                }

        metadata = {
            "layer_name": descriptor.get("display_name", "Dados externos"),
            "layer_id": descriptor.get("layer_id", ""),
            "field_name": numeric_columns[0] if numeric_columns else "-",
            "timestamp": descriptor.get("timestamp", datetime.now().isoformat()),
            "total_features": len(df),
            "source": descriptor.get("connector"),
            "filter_expression": descriptor.get("filter_expression", ""),
        }

        return {
            "basic_stats": stats,
            "grouped_data": {},
            "percentiles": percentiles,
            "metadata": metadata,
            "filter_description": "Nenhum",
            "raw_data": {
                "columns": list(df.columns),
                "rows": df.to_dict(orient="records"),
            },
        }

    def _create_memory_table_from_dataframe(self, df: pd.DataFrame, descriptor: Dict) -> Optional[QgsVectorLayer]:
        try:
            base_name = (descriptor.get("display_name") or "Tabela externa").strip()
            if not base_name:
                base_name = "Tabela externa"

            project = QgsProject.instance()
            existing_names = {layer.name() for layer in project.mapLayers().values()}
            name = base_name
            suffix = 2
            while name in existing_names:
                name = f"{base_name} ({suffix})"
                suffix += 1

            layer = QgsVectorLayer("None", name, "memory")
            provider = layer.dataProvider()
            fields = QgsFields()
            for column in df.columns:
                variant = self._map_series_to_variant(df[column])
                fields.append(QgsField(column[:254], variant))
            provider.addAttributes(fields)
            layer.updateFields()

            features = []
            columns = list(df.columns)
            for _, row in df.iterrows():
                feature = QgsFeature()
                feature.setFields(fields)
                attrs = []
                for column in columns:
                    value = row[column]
                    if pd.isna(value):
                        attrs.append(None)
                    elif ptypes.is_datetime64_any_dtype(df[column]):
                        try:
                            attrs.append(pd.to_datetime(value).to_pydatetime())
                        except Exception:
                            attrs.append(str(value))
                    else:
                        attrs.append(value.item() if hasattr(value, "item") else value)
                feature.setAttributes(attrs)
                features.append(feature)
            if features:
                provider.addFeatures(features)
            layer.updateExtents()
            project.addMapLayer(layer)
            return layer
        except Exception:
            return None

    def _map_series_to_variant(self, series: pd.Series) -> QVariant.Type:
        if ptypes.is_integer_dtype(series):
            return QVariant.LongLong
        if ptypes.is_float_dtype(series):
            return QVariant.Double
        if ptypes.is_bool_dtype(series):
            return QVariant.Bool
        if ptypes.is_datetime64_any_dtype(series):
            return QVariant.DateTime
        return QVariant.String

    def load_layers(self):
        """QgsMapLayerComboBox já lida automaticamente com as camadas."""
        pass

    def _build_geometry_lookup(self, layer: QgsVectorLayer, id_series: pd.Series):
        if layer is None or not layer.isValid():
            return {}
        if id_series is None or id_series.empty:
            return {}
        try:
            unique_ids = id_series.dropna().unique().tolist()
        except Exception:
            return {}
        candidate_ids = []
        for raw in unique_ids:
            if pd.isna(raw):
                continue
            try:
                candidate_ids.append(int(float(raw)))
            except Exception:
                try:
                    candidate_ids.append(int(str(raw)))
                except Exception:
                    continue
        if not candidate_ids:
            return {}
        lookup = {}
        request = QgsFeatureRequest()
        request.setFilterFids(candidate_ids)
        try:
            for feature in layer.getFeatures(request):
                try:
                    lookup[int(feature.id())] = feature.geometry().clone()
                except Exception:
                    pass
        except Exception:
            return {}
        return lookup

    def _geometry_from_lookup(self, fid_value, geometry_lookup):
        if fid_value is None or pd.isna(fid_value):
            return None
        try:
            fid = int(float(fid_value))
        except Exception:
            try:
                fid = int(str(fid_value))
            except Exception:
                return None
        geometry = geometry_lookup.get(fid)
        if geometry is None:
            return None
        try:
            return geometry.clone()
        except Exception:
            return QgsGeometry(geometry)

    def _create_layer_from_dataframe(
        self,
        df: pd.DataFrame,
        layer_name: str,
        with_geometry: bool,
        geometry_layer: Optional[QgsVectorLayer] = None,
    ):
        if df is None or df.empty:
            return None, "Nenhum dado disponível para materializar."

        display_columns = [c for c in df.columns if c not in PROTECTED_COLUMNS_DEFAULT]
        if not display_columns:
            return None, "Nenhuma coluna disponível após proteger os campos internos."

        qfields = QgsFields()
        field_mapping = {}
        existing_names = []
        for column in display_columns:
            try:
                variant = self._variant_type_for_series(df[column])
            except Exception:
                variant = QVariant.String
            safe_name = self._make_unique_field_name(existing_names, column)
            qfields.append(QgsField(safe_name, variant))
            field_mapping[column] = safe_name
            existing_names.append(safe_name)

        geometry_lookup = {}
        geometry_column_available = False
        geom_type = None
        crs_authid = ""

        if with_geometry:
            if "__geometry_wkb" in df.columns:
                try:
                    geometry_column_available = df["__geometry_wkb"].notna().any()
                except Exception:
                    geometry_column_available = False

            if geometry_layer is not None and geometry_layer.isValid():
                geom_type = QgsWkbTypes.displayString(geometry_layer.wkbType())
                try:
                    crs_authid = geometry_layer.crs().authid()
                except Exception:
                    crs_authid = ""

            if "__target_feature_id" in df.columns and geometry_layer is not None and geometry_layer.isValid():
                geometry_lookup = self._build_geometry_lookup(geometry_layer, df["__target_feature_id"])
                if geometry_lookup:
                    geometry_column_available = True
                    if geom_type is None:
                        geom_type = QgsWkbTypes.displayString(geometry_layer.wkbType())
                        try:
                            crs_authid = geometry_layer.crs().authid()
                        except Exception:
                            crs_authid = ""

            if geom_type is None and geometry_column_available:
                sample_hex = None
                try:
                    for raw in df["__geometry_wkb"]:
                        if isinstance(raw, str) and raw:
                            sample_hex = raw
                            break
                except Exception:
                    sample_hex = None
                if sample_hex:
                    try:
                        sample_geom = QgsGeometry.fromWkb(bytes.fromhex(sample_hex))
                        geom_type = QgsWkbTypes.displayString(sample_geom.wkbType())
                    except Exception:
                        geom_type = None

            if not geometry_column_available:
                return None, "Os dados atuais não possuem geometria disponível."
            if geom_type is None:
                return None, "Não foi possível determinar o tipo de geometria."

        uri = "None"
        if with_geometry:
            uri = geom_type if not crs_authid else f"{geom_type}?crs={crs_authid}"

        temp_layer = QgsVectorLayer(uri, layer_name, "memory")
        if not temp_layer or not temp_layer.isValid():
            return None, "Não foi possível criar a camada em memória."

        provider = temp_layer.dataProvider()
        if not provider.addAttributes(qfields):
            return None, "Falha ao definir os campos da camada."
        temp_layer.updateFields()

        features = []
        for _, row in df.iterrows():
            feature = QgsFeature(temp_layer.fields())
            if with_geometry:
                geometry = None
                geom_hex = row.get("__geometry_wkb") if "__geometry_wkb" in df.columns else None
                if isinstance(geom_hex, str) and geom_hex:
                    try:
                        geometry = QgsGeometry.fromWkb(bytes.fromhex(geom_hex))
                    except Exception:
                        geometry = None
                if geometry is None and geometry_lookup:
                    geometry = self._geometry_from_lookup(row.get("__target_feature_id"), geometry_lookup)
                if geometry is None:
                    continue
                try:
                    feature.setGeometry(geometry)
                except Exception:
                    continue
            attrs = []
            for column in display_columns:
                attrs.append(self._python_value(row[column]))
            feature.setAttributes(attrs)
            features.append(feature)

        if not features:
            return None, "Nenhuma feição gerada a partir dos dados filtrados."

        if not provider.addFeatures(features):
            return None, "Falha ao adicionar as feições na camada."

        temp_layer.updateExtents()
        return temp_layer, None

    def _export_layer_to_gpkg(self, layer: QgsVectorLayer, path: str, layer_name: str):
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name
        options.fileEncoding = "UTF-8"
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        context = QgsProject.instance().transformContext()
        result = QgsVectorFileWriter.writeAsVectorFormatV2(layer, path, context, options)
        error = result[0] if isinstance(result, (list, tuple)) else result
        message = result[1] if isinstance(result, (list, tuple)) and len(result) > 1 else ""
        if error != QgsVectorFileWriter.NoError:
            return False, message
        return True, ""

    def _variant_type_for_series(self, series: pd.Series) -> QVariant.Type:
        try:
            if ptypes.is_bool_dtype(series):
                return QVariant.Bool
            if ptypes.is_integer_dtype(series):
                return QVariant.LongLong
            if ptypes.is_float_dtype(series):
                return QVariant.Double
            if ptypes.is_datetime64_any_dtype(series):
                return QVariant.DateTime
        except Exception:
            pass
        return QVariant.String

    def _python_value(self, value):
        if pd.isna(value):
            return None
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            return float(value)
        if isinstance(value, pd.Timestamp):
            return value.to_pydatetime()
        if isinstance(value, np.bool_):
            return bool(value)
        return value

    def _format_comparison_values(self, values):
        formatted = []
        for value in values:
            if not self._is_meaningful_value(value):
                formatted.append("(vazio)")
            else:
                formatted.append(str(value))
        return ", ".join(formatted)

    def _sanitize_field_name(self, raw_name: str) -> str:
        if not raw_name:
            raw_name = "resultado"
        sanitized = re.sub(r"\W+", "_", raw_name).strip("_")
        if not sanitized:
            sanitized = "resultado"
        if sanitized[0].isdigit():
            sanitized = f"f_{sanitized}"
        return sanitized[:30]

    def _make_unique_field_name(self, existing_names, base_name: str) -> str:
        sanitized = self._sanitize_field_name(base_name)
        candidate = sanitized
        counter = 1
        existing = set(existing_names)
        while candidate in existing:
            counter += 1
            candidate = f"{sanitized}_{counter}"
        return candidate

    def _unique_layer_name(self, base_name: str) -> str:
        base = base_name.strip() if base_name else "Camada_Resultado"
        if not base:
            base = "Camada_Resultado"
        existing_names = {
            layer.name() for layer in QgsProject.instance().mapLayers().values()
        }
        candidate = base
        counter = 1
        while candidate in existing_names:
            counter += 1
            candidate = f"{base} ({counter})"
        return candidate

    def _is_meaningful_value(self, value) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return False
            return stripped.lower() not in {"null", "none"}
        return True

    def _filter_empty_matches(self, matches):
        filtered = {}
        for key, values in matches.items():
            meaningful_values = [value for value in values if self._is_meaningful_value(value)]
            if meaningful_values:
                filtered[key] = meaningful_values
        return filtered

    def on_layer_changed(self):
        layer = self.ui.layer_combo.currentLayer()
        if layer and isinstance(layer, QgsVectorLayer):
            self._active_numeric_field = self._select_default_numeric_field(layer)
        else:
            self._active_numeric_field = None

        if self._active_numeric_field is None:
            self.current_summary_data = None
            self.show_summary_prompt()
            return

        if self.ui.auto_update_check.isChecked():
            QTimer.singleShot(300, self.generate_summary)

    def _select_default_numeric_field(self, layer: QgsVectorLayer) -> Optional[str]:
        if not layer:
            return None
        try:
            for field in layer.fields():
                try:
                    if field.isNumeric():
                        return field.name()
                except Exception:
                    pass
                try:
                    if QVariant.Double == field.type() or QVariant.Int == field.type():
                        return field.name()
                except Exception:
                    pass
        except Exception:
            pass
        return None

    def generate_summary(self):
        layer = self.ui.layer_combo.currentLayer()
        if not layer or not isinstance(layer, QgsVectorLayer):
            return
        field_name = self._active_numeric_field or self._select_default_numeric_field(layer)
        if not field_name:
            QMessageBox.warning(
                self,
                "Resumo",
                "Nenhum campo numérico foi encontrado na camada selecionada.",
            )
            self.show_summary_prompt()
            return
        self._active_numeric_field = field_name
        group_field = None
        filter_field = None
        filter_value = None

        # Ensure pivot view becomes visible when gererating summaries
        self._set_results_view("pivot")
        if getattr(self, "summary_message_widget", None) is not None:
            self.summary_message_widget.clear()

        try:
            summary_data = self.calculate_advanced_summary(
            layer, field_name, group_field, filter_field, filter_value
        )
            self.current_summary_data = summary_data
            self.display_advanced_summary(summary_data)
            self.update_charts_preview(summary_data)
            self.prepare_export_tab_defaults(summary_data)
        except Exception as exc:
            QMessageBox.warning(self, "Erro", f"Erro ao gerar resumo: {exc}")

    def calculate_advanced_summary(
        self,
        layer,
        field_name,
        group_field=None,
        filter_field=None,
        filter_value=None,
    ):
        field_index = layer.fields().indexFromName(field_name)
        group_index = layer.fields().indexFromName(group_field) if group_field else -1
        filter_index = layer.fields().indexFromName(filter_field) if filter_field else -1

        request = QgsFeatureRequest()
        filter_description = "Nenhum"
        if filter_field and filter_value:
            filter_description = f'{filter_field} contém "{filter_value}"'
            expression = f'"{filter_field}" ILIKE \'%{filter_value}%\''
            request.setFilterExpression(expression)

        summary = {
            "basic_stats": {
                "total": 0.0,
                "count": 0,
                "average": 0.0,
                "min": float("inf"),
                "max": float("-inf"),
                "median": 0.0,
                "std_dev": 0.0,
            },
            "grouped_data": {},
            "percentiles": {},
            "metadata": {
                "layer_name": layer.name(),
                "layer_id": layer.id(),
                "field_name": field_name,
                "timestamp": datetime.now().isoformat(),
                "total_features": layer.featureCount(),
                "filter_expression": expression if filter_field and filter_value else "",
            },
            "filter_description": filter_description,
        }

        if field_index < 0:
            raise ValueError(f"Campo numérico '{field_name}' não encontrado na camada.")

        field_names = [f.name() for f in layer.fields()]
        raw_rows = []
        values = []
        grouped_values = {}

        for feature in layer.getFeatures(request):
            attrs = feature.attributes()
            raw_rows.append(
                {field_names[idx]: attrs[idx] for idx in range(len(field_names))}
            )

            value = attrs[field_index]
            if value in (None, ""):
                continue

            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue

            values.append(numeric_value)
            summary["basic_stats"]["total"] += numeric_value
            summary["basic_stats"]["min"] = min(
                summary["basic_stats"]["min"], numeric_value
            )
            summary["basic_stats"]["max"] = max(
                summary["basic_stats"]["max"], numeric_value
            )

            if group_index != -1:
                group_value = feature[group_index]
                grouped_values.setdefault(group_value, []).append(numeric_value)

        if values:
            n = len(values)
            sorted_vals = sorted(values)

            summary["basic_stats"]["count"] = n
            summary["basic_stats"]["average"] = summary["basic_stats"]["total"] / n

            if n % 2 == 0:
                summary["basic_stats"]["median"] = (
                    sorted_vals[n // 2 - 1] + sorted_vals[n // 2]
                ) / 2
            else:
                summary["basic_stats"]["median"] = sorted_vals[n // 2]

            mean = summary["basic_stats"]["average"]
            variance = sum((x - mean) ** 2 for x in values) / n
            summary["basic_stats"]["std_dev"] = variance ** 0.5

            summary["percentiles"] = {
                "p25": np.percentile(sorted_vals, 25),
                "p50": np.percentile(sorted_vals, 50),
                "p75": np.percentile(sorted_vals, 75),
                "p90": np.percentile(sorted_vals, 90),
                "p95": np.percentile(sorted_vals, 95),
            }
        else:
            summary["basic_stats"]["min"] = 0.0
            summary["basic_stats"]["max"] = 0.0

        for group, numbers in grouped_values.items():
            if not numbers:
                continue

            group_sum = sum(numbers)
            summary["grouped_data"][str(group)] = {
                "count": len(numbers),
                "sum": group_sum,
                "average": group_sum / len(numbers),
                "min": min(numbers),
                "max": max(numbers),
                "percentage": (
                    (group_sum / summary["basic_stats"]["total"]) * 100
                    if summary["basic_stats"]["total"]
                    else 0.0
                ),
            }

        summary["raw_data"] = {"columns": field_names, "rows": raw_rows}

        return summary

    def display_advanced_summary(self, summary_data):
        self._set_integration_footer_visible(False)
        pivot = getattr(self, "pivot_widget", None)
        if pivot is not None:
            try:
                pivot.set_summary_data(summary_data)
                self._set_results_view("pivot")
                return
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Tabela dinamica",
                    f"Não foi possível atualizar a tabela dinâmica: {exc}",
                )
                self._set_results_view("message")
                self.show_results_message(
                    "<p style='margin:8px 0;'>Não foi possível exibir a tabela dinâmica para estes dados.</p>"
                )
                return

        self._set_results_view("message")
        self.show_results_message(
            "<p style='margin:8px 0;'>Não foi possível exibir a tabela dinâmica para estes dados.</p>"
        )
        return

    def _escape_html(self, text: str) -> str:
        if text is None:
            return ""
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    def update_charts_preview(self, summary_data):
        if not hasattr(self.ui, "chart_preview_text"):
            return
        pivot_widget = getattr(self, "pivot_widget", None)
        if pivot_widget is not None and hasattr(pivot_widget, "get_current_pivot_result"):
            try:
                pivot_result = pivot_widget.get_current_pivot_result()
            except Exception:
                pivot_result = None
            if pivot_result is not None:
                metadata = dict(getattr(pivot_result, "metadata", {}) or {})
                grouped_data = {}
                totals_source = pivot_result.row_totals or pivot_result.column_totals or {}
                grand_total = float(pivot_result.grand_total or 0.0)
                for key, value in totals_source.items():
                    if value is None:
                        continue
                    label = " / ".join(str(item) for item in (key or ()) if item not in (None, ""))
                    label = label or "Total"
                    numeric_value = float(value)
                    grouped_data[label] = {
                        "sum": numeric_value,
                        "percentage": (numeric_value / grand_total * 100) if grand_total else 0.0,
                    }
                summary_data = dict(summary_data or {})
                summary_data["grouped_data"] = grouped_data
                basic_stats = dict(summary_data.get("basic_stats") or {})
                basic_stats["total"] = grand_total
                summary_data["basic_stats"] = basic_stats
                merged_metadata = dict(summary_data.get("metadata") or {})
                merged_metadata.update(
                    {
                        "layer_name": metadata.get("layer_name", merged_metadata.get("layer_name", "-")),
                        "field_name": metadata.get("value_field", merged_metadata.get("field_name", "-")),
                    }
                )
                summary_data["metadata"] = merged_metadata
        grouped = summary_data.get("grouped_data") or {}
        layer_name = summary_data.get("metadata", {}).get("layer_name", "-")
        field_name = summary_data.get("metadata", {}).get("field_name", "-")
        stats = summary_data.get("basic_stats", {})

        timestamp_str = summary_data.get("metadata", {}).get("timestamp")
        try:
            human_ts = datetime.fromisoformat(timestamp_str).strftime("%d/%m/%Y %H:%M")
        except Exception:
            human_ts = datetime.now().strftime("%d/%m/%Y %H:%M")

        total_label = f"{stats.get('total', 0):,.2f}"

        if not grouped:
            empty_html = f"""
            <div class="preview-card empty">
                <div class="preview-header">
                    <h2>Distribuição percentual dos grupos – "{self._escape_html(field_name)}" em {self._escape_html(layer_name)}</h2>
                    <div class="meta-grid">
                        <div class="meta-item">
                            <span class="meta-label">Camada</span>
                            <span class="meta-value">{self._escape_html(layer_name)}</span>
                        </div>
                        <div class="meta-item">
                            <span class="meta-label">Campo numérico</span>
                            <span class="meta-value">{self._escape_html(field_name)}</span>
                        </div>
                        <div class="meta-item">
                            <span class="meta-label">Total geral</span>
                            <span class="meta-value">{total_label}</span>
                        </div>
                    </div>
                </div>
                <div class="empty-body">
                    Nenhum agrupamento disponível para exibir.
                </div>
                <div class="preview-footer">Gerado em: {human_ts}</div>
            </div>
            """
            self.ui.chart_preview_text.setHtml(
                apply_result_style(empty_html) + self._chart_preview_style_block()
            )
            return

        sorted_groups = sorted(
            grouped.items(), key=lambda item: item[1].get("percentage", 0), reverse=True
        )

        labels = [
            "Sem valor" if key in (None, "") else str(key) for key, _ in sorted_groups
        ]
        values = [max(data.get("percentage", 0.0), 0.0) for _, data in sorted_groups]

        chart_html = ""
        if values and max(values) > 0:
            height_px = max(320, int(len(values) * 38 + 120))
            width_px = 780
            image = QImage(width_px, height_px, QImage.Format_ARGB32)
            theme = VisualTheme()
            image.fill(theme.bg)
            painter = QPainter(image)
            painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
            definition = VisualDefinition(
                tipo="barra",
                categorias=labels,
                valores=values,
                titulo="% do total",
            )
            BarChartRenderer().render(painter, QRectF(0, 0, width_px, height_px), definition, theme)
            painter.end()
            buffer = QBuffer()
            buffer.open(QBuffer.ReadWrite)
            image.save(buffer, "PNG")
            encoded = base64.b64encode(bytes(buffer.data())).decode("utf-8")
            chart_html = (
                f'<img class="preview-chart" src="data:image/png;base64,{encoded}" '
                'alt="Distribuicao percentual dos grupos">'
            )

        html = f"""
        <div class="preview-card">
            <div class="preview-header">
                <h2>Distribuicao percentual dos grupos - "{self._escape_html(field_name)}" em {self._escape_html(layer_name)}</h2>
                <div class="meta-grid">
                    <div class="meta-item">
                        <span class="meta-label">Camada</span>
                        <span class="meta-value">{self._escape_html(layer_name)}</span>
                    </div>
                    <div class="meta-item">
                        <span class="meta-label">Campo numerico</span>
                        <span class="meta-value">{self._escape_html(field_name)}</span>
                    </div>
                    <div class="meta-item">
                        <span class="meta-label">Total geral</span>
                        <span class="meta-value">{total_label}</span>
                    </div>
                </div>
            </div>
            <div class="groups-wrapper">
                {chart_html or '<div class="empty-body">Nenhum agrupamento disponível para exibir.</div>'}
            </div>
            <div class="preview-footer">Gerado em: {human_ts}</div>
        </div>
        """

        self.ui.chart_preview_text.setHtml(
            apply_result_style(html) + self._chart_preview_style_block()
        )

    def _chart_preview_style_block(self) -> str:
        return """
        <style>
            .preview-card {
                background: #f5f6fb;
                border: 1px solid #e3e7f1;
                border-radius: 0px;
                padding: 18px 22px;
                display: flex;
                flex-direction: column;
                gap: 18px;
            }
            .preview-card.empty {
                gap: 24px;
            }
            .preview-header h2 {
                margin: 0 0 12px 0;
                font-size: 18px;
                color: #1d2a4b;
            }
            .meta-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 10px;
            }
            .meta-item {
                background: #ffffff;
                border-radius: 0px;
                border: 1px solid #e6eaf4;
                padding: 10px 12px;
                display: flex;
                flex-direction: column;
                gap: 2px;
            }
            .meta-label {
                font-size: 10pt;
                color: #64748b;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            .meta-value {
                font-size: 12pt;
                font-weight: 600;
                color: #1d2a4b;
            }
            .groups-wrapper {
                display: flex;
                justify-content: center;
                padding: 4px;
            }
            .preview-chart {
                max-width: 100%;
                background: rgba(255, 255, 255, 0.7);
                border-radius: 0px;
                padding: 6px;
                border: 1px solid #e6eaf4;
            }
            .preview-footer {
                margin-top: 8px;
                font-size: 10pt;
                color: #7b8794;
                text-align: right;
            }
            .empty-body {
                background: #ffffff;
                border-radius: 0px;
                border: 1px dashed #d2d8e6;
                padding: 18px;
                text-align: center;
                color: #7b8794;
                font-size: 11pt;
            }
        </style>
        """

    def open_export_tab(self):
        try:
            self.ui.stackedWidget.setCurrentWidget(self.ui.pageResultados)
        except Exception:
            pass
        if self.current_summary_data:
            self.prepare_export_tab_defaults(self.current_summary_data)
        else:
            QMessageBox.information(
                self, "Informação", "Gere um resumo antes de exportar."
            )

    def _current_export_format(self):
        text = self.ui.export_format_combo.currentText()
        return self.export_formats.get(text, next(iter(self.export_formats.values())))

    def _strip_existing_timestamp(self, base_path: str) -> str:
        if self._timestamp_pattern.search(base_path):
            return self._timestamp_pattern.sub("", base_path)
        return base_path

    def _normalize_filename_component(self, value: str) -> str:
        if not value:
            return ""
        normalized = "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value.strip()
        )
        return normalized.strip("_")

    def _build_default_export_basename(self, summary_data):
        metadata = summary_data.get("metadata", {})
        layer_part = self._normalize_filename_component(metadata.get("layer_name", ""))
        field_part = self._normalize_filename_component(metadata.get("field_name", ""))
        parts = [part for part in (layer_part, field_part) if part]
        return "_".join(parts) if parts else "resumo_powerbi"

    def _set_export_path(self, path: str):
        base, ext = os.path.splitext(path)
        base = self._strip_existing_timestamp(base)
        sanitized = base + ext
        self._export_base_path = base
        self._updating_export_path = True
        self.ui.export_path_edit.setText(sanitized)
        self._updating_export_path = False

    def prepare_export_tab_defaults(self, summary_data):
        if not summary_data:
            return
        format_info = self._current_export_format()
        base_name = self._build_default_export_basename(summary_data)
        suggested_dir = self.export_manager.export_dir
        suggested_path = os.path.join(
            suggested_dir, base_name + format_info["extension"]
        )
        self._set_export_path(suggested_path)

    def on_export_format_changed(self):
        format_info = self._current_export_format()
        if self._export_base_path:
            self._set_export_path(self._export_base_path + format_info["extension"])
        elif self.current_summary_data:
            self.prepare_export_tab_defaults(self.current_summary_data)

    def on_export_path_edited(self):
        if self._updating_export_path:
            return
        path = self.ui.export_path_edit.text().strip()
        if not path:
            self._export_base_path = ""
            return

        base, _ = os.path.splitext(path)
        base = self._strip_existing_timestamp(base)
        format_info = self._current_export_format()
        self._set_export_path(base + format_info["extension"])

    def _prompt_layer_selection(self, layers):
        names = [layer.name() or "Camada sem nome" for layer in layers]
        dialog = SlimLayerSelectionDialog("Selecionar camadas", names, parent=self)
        dialog.set_focus_on_search()
        if dialog.exec_() != QDialog.Accepted:
            return None
        indices = dialog.selected_indices()
        return [layers[idx] for idx in indices]

    def export_all_vector_layers(self):
        project = QgsProject.instance()
        if project is None:
            QMessageBox.warning(
                self, "Aviso", "Projeto QGIS não encontrado. Tente novamente."
            )
            return

        vector_layers = [
            layer
            for layer in project.mapLayers().values()
            if isinstance(layer, QgsVectorLayer) and layer.isValid()
        ]

        if not vector_layers:
            QMessageBox.information(
                self,
                "Informação",
                "Nenhuma camada vetorial carregada para exportar.",
            )
            return

        selected_layers = self._prompt_layer_selection(vector_layers)
        if selected_layers is None:
            return
        if not selected_layers:
            QMessageBox.information(
                self,
                "Informação",
                "Nenhuma camada selecionada para exportar.",
            )
            return

        target_dir = self._prompt_layers_export_directory()
        if not target_dir:
            return

        exported_count = 0
        errors = []
        style_warnings = []
        transform_context = project.transformContext()

        for layer in selected_layers:
            layer_name = layer.name() or "camada"
            safe_name = self._normalize_filename_component(layer_name) or "camada"
            destination_path = os.path.join(target_dir, f"{safe_name}.gpkg")
            final_path = destination_path
            suffix = 1
            while os.path.exists(final_path):
                final_path = os.path.join(target_dir, f"{safe_name}_{suffix}.gpkg")
                suffix += 1

            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name
            options.fileEncoding = layer.dataProvider().encoding()

            layer_style = QgsMapLayerStyle()
            try:
                style_captured = layer_style.readFromLayer(layer)
            except Exception:
                style_captured = False

            write_output = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                final_path,
                transform_context,
                options,
            )

            result = write_output
            error_message = ""
            status = write_output
            if isinstance(write_output, tuple):
                if write_output:
                    status = write_output[0]
                if len(write_output) > 1:
                    if isinstance(write_output[1], str):
                        error_message = write_output[1]
                    elif write_output[1]:
                        error_message = str(write_output[1])
                if not error_message and len(write_output) > 2:
                    if isinstance(write_output[2], str):
                        error_message = write_output[2]
                    elif write_output[2]:
                        error_message = str(write_output[2])
            elif hasattr(write_output, "status"):
                status = write_output.status()
                try:
                    error_message = getattr(write_output, "errorMessage", lambda: "")()
                except Exception:
                    error_message = ""
            elif hasattr(write_output, "errorMessage"):
                try:
                    error_message = write_output.errorMessage()
                except Exception:
                    error_message = ""

            is_success = False
            if status == QgsVectorFileWriter.NoError:
                is_success = True
            elif hasattr(status, "value"):
                try:
                    is_success = status.value == QgsVectorFileWriter.NoError
                except Exception:
                    is_success = False
            else:
                try:
                    is_success = int(status) == int(QgsVectorFileWriter.NoError)
                except Exception:
                    is_success = False

            if is_success:
                exported_count += 1
                if style_captured:
                    try:
                        gpkg_uri = f"{final_path}|layername={layer_name}"
                        exported_layer = QgsVectorLayer(gpkg_uri, layer_name, "ogr")
                        if not exported_layer.isValid():
                            exported_layer = QgsVectorLayer(final_path, layer_name, "ogr")
                        if exported_layer.isValid():
                            if not layer_style.writeToLayer(exported_layer):
                                style_warnings.append(
                                    (layer_name, "Não foi possível aplicar o estilo.")
                                )
                            else:
                                try:
                                    save_result = exported_layer.saveStyleToDatabase(
                                        layer_name,
                                        "Estilo exportado automaticamente",
                                        True,
                                    )
                                    saved_ok = False
                                    save_error = ""
                                    if isinstance(save_result, tuple):
                                        if save_result:
                                            saved_ok = bool(save_result[0])
                                            if len(save_result) > 1:
                                                save_error = str(save_result[1])
                                    else:
                                        saved_ok = bool(save_result)
                                    if not saved_ok:
                                        message = (
                                            "Estilo aplicado, mas não pôde ser salvo no GeoPackage."
                                        )
                                        if save_error:
                                            message += f" Detalhes: {save_error}"
                                        style_warnings.append(
                                            (
                                                layer_name,
                                                message,
                                            )
                                        )
                                except Exception as exc:
                                    style_warnings.append(
                                        (
                                            layer_name,
                                            f"Falha ao salvar estilo no GeoPackage: {exc}",
                                        )
                                    )
                        else:
                            style_warnings.append(
                                (
                                    layer_name,
                                    "Camada exportada não pôde ser reaberta para aplicar o estilo.",
                                )
                            )
                        exported_layer = None
                    except Exception as exc:
                        style_warnings.append(
                            (layer_name, f"Falha ao transferir estilo: {exc}")
                        )
            else:
                errors.append((layer_name, error_message or "Erro desconhecido"))
                try:
                    if os.path.exists(final_path):
                        os.remove(final_path)
                except Exception:
                    pass

        summary_lines = [
            f"{exported_count} de {len(selected_layers)} camada(s) exportada(s) para GeoPackage em:",
            target_dir,
        ]

        detail_lines = []
        if errors:
            detail_lines.append("Falhas de exportação:")
            detail_lines.extend(f"- {name}: {msg}" for name, msg in errors)
        if style_warnings:
            detail_lines.append("Avisos de estilo:")
            detail_lines.extend(f"- {name}: {msg}" for name, msg in style_warnings)

        if not errors and not style_warnings:
            QMessageBox.information(
                self,
                "Exportação concluída",
                "\n".join(summary_lines),
            )
        else:
            QMessageBox.warning(
                self,
                "Exportação concluída com avisos",
                "\n".join(summary_lines + [""] + detail_lines),
            )

    def open_cloud_upload_tab(self):
        """Open the Cloud dialog focusing the upload tab (admin only)."""
        try:
            from .cloud_dialogs import open_cloud_dialog
            from .cloud_session import cloud_session

            if not cloud_session.is_authenticated() or not cloud_session.is_admin():
                QMessageBox.information(
                    self,
                    "PowerBI Cloud",
                    "Somente administradores conectados podem enviar camadas para o Cloud.",
                )
                return
            open_cloud_dialog(self, initial_tab="upload")
        except Exception:
            # Safe fallback: ignore failures to open the dialog
            pass

    def _prompt_layers_export_directory(self):
        settings = QSettings()
        last_dir = settings.value("PowerBISummarizer/export/gpkgDir", "")
        fallback_dir = self.export_manager.export_dir
        initial_dir = last_dir if last_dir and os.path.isdir(last_dir) else fallback_dir

        directory = QFileDialog.getExistingDirectory(
            self,
            "Selecionar pasta de destino",
            initial_dir,
        )

        if not directory:
            return None

        try:
            os.makedirs(directory, exist_ok=True)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Exportar camadas",
                f"Não foi possível criar a pasta selecionada:\n{directory}\nDetalhes: {exc}",
            )
            return None

        settings.setValue("PowerBISummarizer/export/gpkgDir", directory)
        return directory

    def choose_export_path(self):
        format_info = self._current_export_format()
        initial_path = self.ui.export_path_edit.text().strip()
        if not initial_path:
            initial_path = os.path.join(self.export_manager.export_dir, "")

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Selecionar arquivo",
            initial_path,
            format_info["filter"],
        )

        if file_path:
            base, _ = os.path.splitext(file_path)
            base = self._strip_existing_timestamp(base)
            self._set_export_path(base + format_info["extension"])
            return True
        return False

    def export_results(self):
        if not self.current_summary_data:
            QMessageBox.warning(self, "Aviso", "Gere um resumo primeiro!")
            self.open_export_tab()
            return

        format_info = self._current_export_format()
        target_path = self.ui.export_path_edit.text().strip()

        if not target_path:
            if not self.choose_export_path():
                QMessageBox.warning(
                    self, "Aviso", "Selecione o arquivo de destino para exportar."
                )
                return
            target_path = self.ui.export_path_edit.text().strip()

        base, _ = os.path.splitext(target_path)
        base = self._strip_existing_timestamp(base)

        if self.ui.export_include_timestamp_check.isChecked():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_path = f"{base}_{stamp}{format_info['extension']}"
        else:
            export_path = base + format_info["extension"]

        try:
            self.export_manager.export_data(
                self.current_summary_data, export_path, format_info["filter"]
            )
            QMessageBox.information(
                self, "Sucesso", f"Dados exportados para:\n{export_path}"
            )
            self._set_export_path(base + format_info["extension"])
        except Exception as exc:
            QMessageBox.critical(self, "Erro", f"Erro na exportação: {exc}")

    def _materialize_dataframe_dialog(
        self,
        df: pd.DataFrame,
        base_name: str,
        can_use_geometry: bool,
        geometry_layer: Optional[QgsVectorLayer],
        settings_key: str,
        dialog_title: str,
        table_prefix: str,
        memory_prefix: str,
        export_prefix: str,
    ):
        if df is None or df.empty:
            QMessageBox.information(self, dialog_title, "Nenhum dado disponível para materializar.")
            return

        base_name = (base_name or "resultado").strip()
        if not base_name:
            base_name = "resultado"

        options = ["Tabela (somente atributos)"]
        gpkg_label = "Salvar como GPKG"
        if can_use_geometry:
            options.append("Camada temporaria (memoria)")
            options.append(gpkg_label)
        else:
            gpkg_label = "Salvar como GPKG (tabela)"
            options.append(gpkg_label)

        choice, ok = slim_get_item(
            self,
            dialog_title,
            "Escolha como deseja materializar o resultado atual:",
            options,
            current=0,
        )
        if not ok or not choice:
            return

        if choice.startswith("Tabela"):
            table_name = self._unique_layer_name(f"{table_prefix} {base_name}".strip())
            layer, error_message = self._create_layer_from_dataframe(
                df,
                table_name,
                with_geometry=False,
            )
            if layer is None:
                QMessageBox.warning(
                    self,
                    dialog_title,
                    error_message or "Não foi possível gerar a tabela.",
                )
                return
            QgsProject.instance().addMapLayer(layer)
            QMessageBox.information(
                self,
                dialog_title,
                f"Tabela '{layer.name()}' criada com {layer.featureCount()} registros.",
            )
            return

        if choice.startswith("Camada temporaria"):
            layer_name = self._unique_layer_name(f"{memory_prefix} {base_name}".strip())
            layer, error_message = self._create_layer_from_dataframe(
                df,
                layer_name,
                with_geometry=True,
                geometry_layer=geometry_layer,
            )
            fallback_note = ""
            if (
                layer is None
                and can_use_geometry
                and error_message
                and "Nenhuma feição" in error_message
            ):
                layer, error_message = self._create_layer_from_dataframe(
                    df,
                    layer_name,
                    with_geometry=False,
                    geometry_layer=None,
                )
                if layer is not None:
                    fallback_note = (
                        "\n\nAs transformacoes removeram as geometrias. "
                        "Foi criada uma tabela temporaria sem geometria."
                    )
            if layer is None:
                QMessageBox.warning(
                    self,
                    dialog_title,
                    error_message or "Não foi possível criar a camada temporária.",
                )
                return
            QgsProject.instance().addMapLayer(layer)
            QMessageBox.information(
                self,
                dialog_title,
                f"Camada '{layer.name()}' criada com {layer.featureCount()} feições.{fallback_note}",
            )
            return

        if choice.startswith("Salvar como GPKG"):
            suggested_name = re.sub(r"[^a-zA-Z0-9_\\-]+", "_", base_name).strip("_") or "resultado"
            last_dir = ""
            if settings_key:
                try:
                    last_dir = QSettings().value(settings_key, "", type=str)
                except Exception:
                    last_dir = ""
            default_path = (
                os.path.join(last_dir, f"{suggested_name}.gpkg") if last_dir else f"{suggested_name}.gpkg"
            )
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Salvar GeoPackage",
                default_path,
                "GeoPackage (*.gpkg)",
            )
            if not path:
                return
            directory = os.path.dirname(path)
            if settings_key and directory:
                QSettings().setValue(settings_key, directory)
            if not path.lower().endswith(".gpkg"):
                path += ".gpkg"

            with_geometry = can_use_geometry and not choice.endswith("(tabela)")
            export_layer_name = f"{export_prefix} {base_name}".strip() or base_name
            layer, error_message = self._create_layer_from_dataframe(
                df,
                export_layer_name,
                with_geometry=with_geometry,
                geometry_layer=geometry_layer,
            )
            fallback_note = ""
            if (
                layer is None
                and with_geometry
                and error_message
                and "Nenhuma feição" in error_message
            ):
                layer, error_message = self._create_layer_from_dataframe(
                    df,
                    export_layer_name,
                    with_geometry=False,
                    geometry_layer=None,
                )
                if layer is not None:
                    fallback_note = (
                        "\n\nAs transformacoes removeram as geometrias. "
                        "O arquivo foi salvo apenas com atributos."
                    )
            if layer is None:
                QMessageBox.warning(
                    self,
                    dialog_title,
                    error_message or "Não foi possível preparar os dados para exportação.",
                )
                return

            success, writer_message = self._export_layer_to_gpkg(layer, path, export_layer_name)
            if not success:
                QMessageBox.critical(
                    self,
                    dialog_title,
                    writer_message or "Falha ao exportar o GeoPackage.",
                )
                return

            try:
                uri = f"{path}|layername={export_layer_name}"
                exported_layer = QgsVectorLayer(uri, export_layer_name, "ogr")
                if exported_layer and exported_layer.isValid():
                    QgsProject.instance().addMapLayer(exported_layer)
            except Exception:
                pass

            final_message = f"Arquivo GeoPackage salvo em:\n{path}{fallback_note}"
            QMessageBox.information(
                self,
                dialog_title,
                final_message,
            )

    def show_dashboard(self):
        self._set_ribbon_visible(False)
        try:
            self.ui.stackedWidget.setCurrentWidget(self.ui.pageResultados)
        except Exception:
            pass
        pivot_widget = getattr(self, "pivot_widget", None)
        if pivot_widget is None:
            QMessageBox.warning(
                self,
                "Dashboard",
                "A tabela dinâmica ainda não está disponível para este resumo.",
            )
            return

        try:
            pivot_result = None
            if hasattr(pivot_widget, "get_current_pivot_result"):
                pivot_result = pivot_widget.get_current_pivot_result()
            pivot_df = pivot_widget.get_visible_pivot_dataframe()
            raw_df = getattr(pivot_widget, "raw_df", None)
            metadata = pivot_widget.get_summary_metadata()
            config = pivot_widget.get_current_configuration()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Dashboard",
                f"Não foi possível obter os dados filtrados da tabela dinâmica: {exc}",
            )
            return

        if raw_df is not None and not getattr(raw_df, "empty", True):
            self.dashboard_widget.set_pivot_data(raw_df, metadata, config)
        elif pivot_result is not None and hasattr(self.dashboard_widget, "set_pivot_result"):
            self.dashboard_widget.set_pivot_result(pivot_result)
        else:
            self.dashboard_widget.set_pivot_data(pivot_df, metadata, config)
        self.dashboard_widget.show()
        self.dashboard_widget.raise_()

    def show_about_dialog(self):
        dialog = SlimDialogBase(self, geometry_key="PowerBISummarizer/dialogs/about")
        dialog.setWindowTitle("Sobre")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel("Power BI Summarizer", dialog)
        title.setProperty("sublabel", True)
        layout.addWidget(title)

        body = QLabel(
            "Resumo e exporta??uo de camadas do QGIS com visual inspirado no Power BI.",
            dialog,
        )
        body.setWordWrap(True)
        layout.addWidget(body)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok, dialog)
        ok_button = buttons.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setObjectName("SlimPrimaryButton")
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.exec_()


def _vector_layer_to_dataframe(layer) -> Optional[pd.DataFrame]:
    if layer is None or not layer.isValid():
        return None
    field_names = [field.name() for field in layer.fields()]
    rows = []
    for feature in layer.getFeatures():
        row = {field_names[idx]: feature.attributes()[idx] for idx in range(len(field_names))}
        rows.append(row)
    return pd.DataFrame(rows)


class GetDataDialog(QDialog):
    """Diálogo compacto de 'Obter Dados' inspirado no Power BI."""

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.setWindowTitle("Obter Dados")
        self.resize(680, 420)
        self._datasets: list = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        info = QLabel(
            "Escolha a fonte de dados (PostgreSQL ou Power BI Summarizer Cloud). "
            "As tabelas selecionadas serão adicionadas ao modelo sem abrir camadas no mapa."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.source_combo = QComboBox(self)
        self.source_combo.addItem("PostgreSQL / SQL", "database")
        self.source_combo.addItem("Power BI Summarizer Cloud", "cloud")
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        layout.addWidget(self.source_combo)

        self.stack = QStackedWidget(self)
        layout.addWidget(self.stack, 1)

        # Página DB
        db_page = QFrame(self)
        db_layout = QVBoxLayout(db_page)
        db_layout.setContentsMargins(0, 0, 0, 0)
        db_layout.setSpacing(8)
        db_layout.addWidget(QLabel("Usar conexões salvas ou cadastrar nova."))
        self.db_import_btn = QPushButton("Abrir importador de banco...")
        self.db_import_btn.setCursor(Qt.PointingHandCursor)
        db_layout.addWidget(self.db_import_btn, 0, Qt.AlignLeft)
        self.db_status = QLabel("")
        self.db_status.setProperty("role", "helper")
        db_layout.addWidget(self.db_status)
        db_layout.addStretch(1)
        self.db_import_btn.clicked.connect(self._open_db_dialog)
        self.stack.addWidget(db_page)

        # Página Cloud
        cloud_page = QFrame(self)
        cloud_layout = QVBoxLayout(cloud_page)
        cloud_layout.setContentsMargins(0, 0, 0, 0)
        cloud_layout.setSpacing(8)
        cloud_layout.addWidget(QLabel("Selecione camadas disponíveis no Power BI Summarizer Cloud:"))
        self.cloud_list = QListWidget(cloud_page)
        self.cloud_list.setSelectionMode(QListWidget.MultiSelection)
        cloud_layout.addWidget(self.cloud_list, 1)
        cloud_buttons = QHBoxLayout()
        cloud_buttons.setSpacing(6)
        self.cloud_refresh_btn = QPushButton("Atualizar")
        self.cloud_refresh_btn.setProperty("variant", "ghost")
        self.cloud_load_btn = QPushButton("Carregar selecionados")
        for btn in (self.cloud_refresh_btn, self.cloud_load_btn):
            btn.setCursor(Qt.PointingHandCursor)
        cloud_buttons.addWidget(self.cloud_refresh_btn)
        cloud_buttons.addStretch(1)
        cloud_buttons.addWidget(self.cloud_load_btn)
        cloud_layout.addLayout(cloud_buttons)
        self.cloud_status = QLabel("")
        self.cloud_status.setProperty("role", "helper")
        cloud_layout.addWidget(self.cloud_status)
        cloud_layout.addStretch(1)
        self.cloud_refresh_btn.clicked.connect(self._populate_cloud_layers)
        self.cloud_load_btn.clicked.connect(self._load_selected_cloud_layers)
        self.stack.addWidget(cloud_page)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate_cloud_layers()
        self._on_source_changed(0)

    # ------------------------------------------------------------------ Actions
    def _on_source_changed(self, index: int):
        self.stack.setCurrentIndex(index)

    def _open_db_dialog(self):
        try:
            saved = connection_registry.saved_connections()
        except Exception:
            saved = []
        dialog = DatabaseImportDialog(self, saved)
        if dialog.exec_() != QDialog.Accepted:
            return
        df, metadata, connection_meta, session_connection = dialog.result()
        if df is None or df.empty:
            QMessageBox.information(self, "Banco", "Nenhuma tabela carregada.")
            return
        self._datasets.append((df, metadata or {"connector": "PostgreSQL"}))
        self.db_status.setText(f"Tabela carregada: {metadata.get('display_name')}")
        # Replica conexão no Navegador, se houver
        if connection_meta:
            try:
                connection_registry.replace_saved_connections([connection_meta], persist=True)
            except Exception:
                pass
        if session_connection:
            try:
                connection_registry.register_runtime_connection(session_connection)
            except Exception:
                pass

    def _populate_cloud_layers(self):
        self.cloud_list.clear()
        connections = cloud_session.cloud_connections()
        total_layers = 0
        for conn in connections:
            conn_name = conn.get("name") or conn.get("id") or "Conexão"
            for layer_payload in conn.get("layers", []):
                label = f"{conn_name} - {layer_payload.get('name', layer_payload.get('id', 'Camada'))}"
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, layer_payload)
                self.cloud_list.addItem(item)
                total_layers += 1
        self.cloud_status.setText(f"{total_layers} camada(s) disponíveis.")

    def _load_selected_cloud_layers(self):
        selected = self.cloud_list.selectedItems()
        if not selected:
            QMessageBox.information(self, "Cloud", "Selecione ao menos uma camada.")
            return
        loaded = 0
        for item in selected:
            payload = item.data(Qt.UserRole) or {}
            source = payload.get("source") or payload.get("uri") or ""
            provider = payload.get("provider") or "ogr"
            if not source:
                continue
            layer_name = payload.get("name") or payload.get("id") or "Camada"
            layer = QgsVectorLayer(source, layer_name, provider)
            if not layer.isValid():
                continue
            df = _vector_layer_to_dataframe(layer)
            if df is None:
                continue
            metadata = {
                "connector": "PowerBI Cloud",
                "display_name": layer_name,
                "source_path": source,
                "record_count": len(df),
            }
            self._datasets.append((df, metadata))
            loaded += 1
        self.cloud_status.setText(f"{loaded} camada(s) carregadas.")

    # ------------------------------------------------------------------ API
    def results(self) -> List:
        return list(self._datasets)



