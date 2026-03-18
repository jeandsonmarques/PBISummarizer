from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from qgis.PyQt.QtCore import QDateTime, Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from qgis.core import QgsProject, QgsVectorFileWriter, QgsVectorLayer
from qgis.utils import iface

from .cloud_session import cloud_session
from .slim_dialogs import SlimDialogBase



class PowerBICloudDialog(SlimDialogBase):
    """Popup used both in the Integration tab and Browser shortcuts."""

    def __init__(self, parent: Optional[QWidget] = None, initial_tab: Optional[str] = None):
        super().__init__(parent, geometry_key="PowerBISummarizer/cloud/dialog")
        self.setWindowTitle("PowerBI Cloud (beta)")
        self.resize(640, 420)
        self._upload_layers: List[QgsVectorLayer] = []
        self._build_ui()
        self._connect_signals()
        self._update_session_ui()
        self._update_config_ui()
        self._on_layers_changed()
        self._refresh_upload_layers()
        self._refresh_group_choices()
        self._select_initial_tab(initial_tab)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Gerenciar sessao PowerBI Cloud", self)
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        self.cloud_status_badge = QLabel("Desconectado", self)
        self.cloud_status_badge.setObjectName("cloudDialogStatusBadge")
        header.addWidget(self.cloud_status_badge, 0, Qt.AlignRight)
        layout.addLayout(header)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("cloudDialogTabs")
        layout.addWidget(self.tabs, 1)

        # Session tab ----------------------------------------------------
        session_tab = QWidget(self.tabs)
        session_layout = QGridLayout(session_tab)
        session_layout.setContentsMargins(12, 12, 12, 12)
        session_layout.setHorizontalSpacing(12)
        session_layout.setVerticalSpacing(10)

        self.user_edit = QLineEdit(session_tab)
        self.user_edit.setPlaceholderText("usuario@empresa.com")
        self.password_edit = QLineEdit(session_tab)
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("********")
        self.remember_checkbox = QCheckBox("Salvar login no gerenciador de conexões QGIS", session_tab)
        self.remember_checkbox.setToolTip(
            "Armazena usuario e senha no AuthManager do QGIS para renovar tokens automaticamente."
        )
        self.remember_checkbox.setChecked(cloud_session.has_saved_credentials())

        session_layout.addWidget(QLabel("Usuario", session_tab), 0, 0)
        session_layout.addWidget(self.user_edit, 0, 1)
        session_layout.addWidget(QLabel("Senha", session_tab), 1, 0)
        session_layout.addWidget(self.password_edit, 1, 1)
        session_layout.addWidget(self.remember_checkbox, 2, 0, 1, 2)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(8)
        self.login_btn = QPushButton("Entrar", session_tab)
        self.logout_btn = QPushButton("Sair", session_tab)
        self.logout_btn.setProperty("variant", "secondary")
        self.refresh_btn = QPushButton("Atualizar catalogo", session_tab)
        self.refresh_btn.setProperty("variant", "ghost")
        self.browser_btn = QPushButton("Abrir no Navegador", session_tab)
        self.browser_btn.setProperty("variant", "ghost")
        buttons_row.addWidget(self.login_btn)
        buttons_row.addWidget(self.logout_btn)
        buttons_row.addWidget(self.refresh_btn)
        buttons_row.addWidget(self.browser_btn)
        buttons_row.addStretch(1)
        session_layout.addLayout(buttons_row, 3, 0, 1, 2)

        self.session_detail = QLabel("Status: aguardando login.", session_tab)
        self.session_detail.setWordWrap(True)
        session_layout.addWidget(self.session_detail, 4, 0, 1, 2)

        sync_layout = QHBoxLayout()
        sync_layout.addWidget(QLabel("Ultima sincronizacao mock:", session_tab))
        self.last_sync_label = QLabel("-", session_tab)
        sync_layout.addWidget(self.last_sync_label)
        sync_layout.addStretch(1)
        session_layout.addLayout(sync_layout, 5, 0, 1, 2)

        self.warning_label = QLabel(
            "Cloud em preparacao. Camadas reais serao liberadas quando a hospedagem estiver ativa.",
            session_tab,
        )
        self.warning_label.setWordWrap(True)
        self.warning_label.setProperty("role", "helper")
        session_layout.addWidget(self.warning_label, 6, 0, 1, 2)

        self.session_tab_index = self.tabs.addTab(session_tab, "Sessao")

        # Config tab -----------------------------------------------------
        config_tab = QWidget(self.tabs)
        config_layout = QGridLayout(config_tab)
        config_layout.setContentsMargins(12, 12, 12, 12)
        config_layout.setHorizontalSpacing(12)
        config_layout.setVerticalSpacing(10)

        self.base_url_edit = QLineEdit(config_tab)
        self.login_endpoint_edit = QLineEdit(config_tab)
        self.layers_endpoint_edit = QLineEdit(config_tab)
        self.hosting_checkbox = QCheckBox("Hospedagem ativa (liberar camadas reais)", config_tab)

        config_layout.addWidget(QLabel("Base URL", config_tab), 0, 0)
        config_layout.addWidget(self.base_url_edit, 0, 1)
        config_layout.addWidget(QLabel("Endpoint de login", config_tab), 1, 0)
        config_layout.addWidget(self.login_endpoint_edit, 1, 1)
        config_layout.addWidget(QLabel("Endpoint de camadas", config_tab), 2, 0)
        config_layout.addWidget(self.layers_endpoint_edit, 2, 1)
        config_layout.addWidget(self.hosting_checkbox, 3, 0, 1, 2)

        config_buttons = QHBoxLayout()
        config_buttons.setSpacing(8)
        self.save_config_btn = QPushButton("Salvar configuracoes", config_tab)
        self.test_real_btn = QPushButton("Testar camadas reais", config_tab)
        self.test_real_btn.setProperty("variant", "ghost")
        config_buttons.addWidget(self.save_config_btn)
        config_buttons.addWidget(self.test_real_btn)
        config_buttons.addStretch(1)
        config_layout.addLayout(config_buttons, 4, 0, 1, 2)

        config_hint = QLabel(
            "Sua API do PowerBI Cloud ja esta ativa. "
            "Use a Base URL e os endpoints abaixo normalmente. "
            "Com 'Hospedagem ativa' marcada, o plugin usa apenas camadas reais do servidor (sem dados de teste).",
            config_tab,
        )
        config_hint.setWordWrap(True)
        config_hint.setProperty("role", "helper")
        config_layout.addWidget(config_hint, 5, 0, 1, 2)

        self.config_tab_index = self.tabs.addTab(config_tab, "Configuracoes Cloud")

        # Aba Admin para o cadastro de usuarios Cloud
        admin_tab = QWidget(self.tabs)
        admin_layout = QVBoxLayout(admin_tab)
        admin_layout.setContentsMargins(12, 12, 12, 12)
        admin_layout.setSpacing(12)

        admin_info = QLabel(
            "Apenas o usuario administrador pode criar contas Cloud para outras pessoas.", admin_tab
        )
        admin_info.setWordWrap(True)
        admin_layout.addWidget(admin_info)

        admin_form = QFormLayout()
        admin_form.setLabelAlignment(Qt.AlignLeft)
        self.adminEmailLineEdit = QLineEdit(admin_tab)
        self.adminEmailLineEdit.setPlaceholderText("email do novo usuario (login)")
        admin_form.addRow("E-mail do novo usuario", self.adminEmailLineEdit)

        self.adminPasswordLineEdit = QLineEdit(admin_tab)
        self.adminPasswordLineEdit.setEchoMode(QLineEdit.Password)
        self.adminPasswordLineEdit.setPlaceholderText("senha inicial")
        admin_form.addRow("Senha", self.adminPasswordLineEdit)

        admin_layout.addLayout(admin_form)

        self.createUserButton = QPushButton("Criar usuario Cloud", admin_tab)
        self.createUserButton.setMinimumHeight(40)
        admin_layout.addWidget(self.createUserButton)
        admin_layout.addStretch(1)

        self.admin_tab_index = self.tabs.addTab(admin_tab, "Admin")

        # Aba Upload Cloud (apenas admin)
        upload_tab = QWidget(self.tabs)
        upload_layout = QVBoxLayout(upload_tab)
        upload_layout.setContentsMargins(12, 12, 12, 12)
        upload_layout.setSpacing(10)

        upload_form = QFormLayout()
        upload_form.setLabelAlignment(Qt.AlignLeft)
        self.upload_layer_combo = QComboBox(upload_tab)
        upload_form.addRow("Camada do QGIS", self.upload_layer_combo)

        self.upload_name_edit = QLineEdit(upload_tab)
        self.upload_name_edit.setPlaceholderText("Nome da camada no Cloud")
        upload_form.addRow("Nome no Cloud", self.upload_name_edit)

        self.upload_desc_edit = QLineEdit(upload_tab)
        self.upload_desc_edit.setPlaceholderText("Descricao curta (opcional)")
        upload_form.addRow("Descricao (opcional)", self.upload_desc_edit)
        self.upload_group_combo = QComboBox(upload_tab)
        self.upload_group_combo.setEditable(True)
        self.upload_group_combo.setInsertPolicy(QComboBox.NoInsert)
        upload_form.addRow("Grupo / Pasta da camada (opcional)", self.upload_group_combo)

        upload_layout.addLayout(upload_form)

        upload_hint = QLabel(
            "Sera criado um arquivo GPKG temporario com a camada selecionada e enviado para o servidor. "
            "Funcao disponivel apenas para administrador.",
            upload_tab,
        )
        upload_hint.setWordWrap(True)
        upload_hint.setProperty("role", "helper")
        upload_layout.addWidget(upload_hint)

        self.upload_button = QPushButton("Enviar camada para o Cloud (GPKG)", upload_tab)
        self.upload_button.setMinimumHeight(40)
        upload_layout.addWidget(self.upload_button)

        self.upload_status_label = QLabel("", upload_tab)
        self.upload_status_label.setWordWrap(True)
        self.upload_status_label.setProperty("role", "helper")
        upload_layout.addWidget(self.upload_status_label)
        upload_layout.addStretch(1)

        self.upload_tab_index = self.tabs.addTab(upload_tab, "Upload")
        self._update_admin_tab_visibility()

        button_box = QDialogButtonBox(QDialogButtonBox.Close, self)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _connect_signals(self):
        self.login_btn.clicked.connect(self._handle_login)
        self.password_edit.returnPressed.connect(self._handle_login)
        self.logout_btn.clicked.connect(self._handle_logout)
        self.refresh_btn.clicked.connect(self._refresh_layers)
        self.browser_btn.clicked.connect(self._open_browser_hint)
        self.save_config_btn.clicked.connect(self._save_config)
        self.test_real_btn.clicked.connect(self._handle_real_access_attempt)
        self.createUserButton.clicked.connect(self.on_create_cloud_user_clicked)
        self.upload_layer_combo.currentIndexChanged.connect(lambda *_: self._prefill_upload_name())
        self.upload_button.clicked.connect(self._handle_upload_layer)
        cloud_session.sessionChanged.connect(lambda *_: self._update_session_ui())
        cloud_session.configChanged.connect(lambda *_: self._update_config_ui())
        cloud_session.layersChanged.connect(lambda *_: self._on_layers_changed())

    # ------------------------------------------------------------------ Cloud actions
    def _handle_login(self):
        username = self.user_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            QMessageBox.warning(self, "PowerBI Cloud", "Informe usuario e senha.")
            return
        try:
            session_payload = cloud_session.login(username, password)
            mode = session_payload.get("mode") or "mock"
            if mode == "remote":
                message = (
                    f"Sessao Cloud autenticada para {username}.\n"
                    "Catalogo carregado a partir da API configurada."
                )
            else:
                message = (
                    f"Sessao mock ativa para {username}.\n"
                    "Ative 'Hospedagem ativa' quando o deploy estiver pronto para usar o banco remoto."
                )
            QMessageBox.information(
                self,
                "PowerBI Cloud",
                message,
            )
            # Após login bem-sucedido, atualizamos o e-mail padrão vinculado à conexão ativa.
            self._persist_cloud_user_from_login(username)
            cloud_session.update_saved_credentials(username, password, self.remember_checkbox.isChecked())
        except ValueError as exc:
            QMessageBox.warning(self, "PowerBI Cloud", str(exc))
        except Exception as exc:  # pragma: no cover - runtime safeguard
            QMessageBox.critical(self, "PowerBI Cloud", f"Falha no login: {exc}")
        finally:
            self.password_edit.clear()

    def _handle_logout(self):
        cloud_session.logout()

    def _refresh_layers(self):
        from .browser_integration import reload_cloud_catalog

        reload_cloud_catalog()
        self._on_layers_changed()
        if cloud_session.hosting_ready():
            message = "Catalogo Cloud atualizado a partir do servidor configurado."
        elif cloud_session.session().get("mode") == "remote":
            message = "Catalogo Cloud atualizado."
        else:
            message = "Catalogo mock atualizado."
        QMessageBox.information(self, "PowerBI Cloud", message)

    def _open_browser_hint(self):
        QMessageBox.information(
            self,
            "PowerBI Cloud",
            "Abra o painel Navegador do QGIS e expanda PowerBI Summarizer -> PowerBI Cloud "
            "para carregar as camadas disponiveis.",
        )

    def _save_config(self):
        cloud_session.update_config(
            base_url=self.base_url_edit.text().strip(),
            login_endpoint=self.login_endpoint_edit.text().strip(),
            layers_endpoint=self.layers_endpoint_edit.text().strip(),
            hosting_ready=self.hosting_checkbox.isChecked(),
        )
        QMessageBox.information(self, "PowerBI Cloud", "Configuracoes salvas.")

    def _handle_real_access_attempt(self):
        if not cloud_session.hosting_ready():
            QMessageBox.information(
                self,
                "PowerBI Cloud",
                "Ative 'Hospedagem ativa' para trabalhar apenas com as camadas reais publicadas no servidor.",
            )
            return
        QMessageBox.information(
            self,
            "PowerBI Cloud",
            "Com 'Hospedagem ativa' marcada, o plugin ja usa apenas o catalogo real informado.",
        )

    # ------------------------------------------------------------------ Admin actions
    def on_create_cloud_user_clicked(self):
        """Slot acionado a partir do botao da aba Admin."""
        if not cloud_session.is_admin():
            QMessageBox.warning(
                self,
                "Permissao negada",
                "Apenas usuarios admin podem criar novos usuarios Cloud.",
            )
            return

        email = self.adminEmailLineEdit.text().strip()
        password = self.adminPasswordLineEdit.text().strip()
        if not email or not password:
            QMessageBox.warning(
                self,
                "Dados invalidos",
                "Informe o e-mail e a senha do novo usuario.",
            )
            return

        if not cloud_session.is_authenticated() or not cloud_session.session().get("token"):
            QMessageBox.warning(
                self,
                "Sessao invalida",
                "Voce precisa estar logado como admin@demo.dev para criar usuarios.",
            )
            return

        try:
            status_code, payload = cloud_session.create_cloud_user(email=email, password=password)
        except RuntimeError:
            QMessageBox.critical(
                self,
                "Erro de conexao",
                "Nao foi possivel comunicar com a API Cloud para criar o usuario. Verifique a conexao e tente novamente.",
            )
            return

        detail = ""
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("message") or ""

        if status_code in (200, 201):
            QMessageBox.information(
                self,
                "Usuario criado",
                f"Usuario Cloud {email} criado com sucesso.",
            )
            self.adminEmailLineEdit.clear()
            self.adminPasswordLineEdit.clear()
            return

        if status_code in (400, 409):
            message = detail or "Servidor recusou a criacao do usuario Cloud."
            QMessageBox.warning(self, "Erro ao criar usuario", message)
            return

        if status_code in (401, 403):
            QMessageBox.warning(
                self,
                "Sem permissao",
                "Sessao expirada ou sem permissao. Faca login novamente como admin@demo.dev.",
            )
            return

        fallback = detail or "Falha inesperada ao criar o usuario Cloud."
        QMessageBox.warning(self, "Erro ao criar usuario", fallback)

    # ------------------------------------------------------------------ Upload actions
    def _refresh_upload_layers(self):
        project = QgsProject.instance()
        layers: List[QgsVectorLayer] = []
        if project is not None:
            layers = [
                layer
                for layer in project.mapLayers().values()
                if isinstance(layer, QgsVectorLayer) and layer.isValid()
            ]
            layers.sort(key=lambda lyr: (lyr.name() or "").lower())
        self._upload_layers = layers

        self.upload_layer_combo.blockSignals(True)
        self.upload_layer_combo.clear()
        active_id = None
        try:
            active_layer = iface.activeLayer()
            if isinstance(active_layer, QgsVectorLayer) and active_layer.isValid():
                active_id = active_layer.id()
        except Exception:
            active_id = None

        for layer in layers:
            self.upload_layer_combo.addItem(layer.name() or "Camada sem nome", layer.id())

        if active_id:
            idx = self.upload_layer_combo.findData(active_id)
            if idx >= 0:
                self.upload_layer_combo.setCurrentIndex(idx)
        self.upload_layer_combo.blockSignals(False)

        self._prefill_upload_name()
        if not layers:
            self._set_upload_status("Nenhuma camada vetorial disponivel no projeto atual.", level="error")
        else:
            self._set_upload_status("", level="info")

    def _refresh_group_choices(self):
        if not hasattr(self, "upload_group_combo"):
            return
        groups = cloud_session.cloud_group_names()
        current_text = self.upload_group_combo.currentText()
        self.upload_group_combo.blockSignals(True)
        self.upload_group_combo.clear()
        self.upload_group_combo.addItem("Sem grupo", "")
        for group in groups:
            self.upload_group_combo.addItem(group, group)
        if current_text:
            idx = self.upload_group_combo.findText(current_text, Qt.MatchFixedString)
            if idx >= 0:
                self.upload_group_combo.setCurrentIndex(idx)
            else:
                self.upload_group_combo.setEditText(current_text)
        else:
            self.upload_group_combo.setCurrentIndex(0)
        self.upload_group_combo.blockSignals(False)

    def _prefill_upload_name(self):
        layer = self._current_upload_layer()
        if layer is None:
            self.upload_name_edit.clear()
            return
        if not self.upload_name_edit.text().strip():
            self.upload_name_edit.setText(layer.name() or "")

    def _current_upload_layer(self) -> Optional[QgsVectorLayer]:
        if not self._upload_layers:
            return None
        layer_id = self.upload_layer_combo.currentData()
        for layer in self._upload_layers:
            if layer.id() == layer_id:
                return layer
        idx = self.upload_layer_combo.currentIndex()
        if 0 <= idx < len(self._upload_layers):
            return self._upload_layers[idx]
        return None

    def _selected_group_name(self) -> str:
        combo = getattr(self, "upload_group_combo", None)
        if combo is None:
            return ""
        text = combo.currentText()
        return (text or "").strip()

    def _set_upload_status(self, text: str, level: str = "info"):
        colors = {"info": "#5D5A58", "ok": "#2F8D46", "error": "#B3261E"}
        self.upload_status_label.setText(text or "")
        self.upload_status_label.setStyleSheet(f"color: {colors.get(level, '#5D5A58')};")

    def _handle_upload_layer(self):
        if not cloud_session.is_authenticated() or not cloud_session.is_admin():
            self._set_upload_status(
                "Voce precisa estar conectado ao Cloud como administrador para enviar camadas.",
                level="error",
            )
            QMessageBox.warning(
                self,
                "PowerBI Cloud",
                "Voce precisa estar conectado ao Cloud como administrador para enviar camadas.",
            )
            return

        layer = self._current_upload_layer()
        if layer is None:
            self._set_upload_status("Selecione uma camada do QGIS para enviar.", level="error")
            QMessageBox.information(self, "PowerBI Cloud", "Nenhuma camada vetorial selecionada.")
            return

        layer_name = self.upload_name_edit.text().strip() or layer.name() or "camada"
        description = self.upload_desc_edit.text().strip()
        group_name_value = self._selected_group_name()

        epsg = None
        try:
            epsg = layer.crs().postgisSrid() or None
            if not epsg:
                authid = layer.crs().authid()
                if authid and ":" in authid:
                    _, code = authid.split(":", 1)
                    if code.isdigit():
                        epsg = int(code)
        except Exception:
            epsg = None

        tmp_dir = None
        gpkg_path: Optional[Path] = None

        try:
            source = (layer.source() or "").split("|", 1)[0]
            if source.lower().endswith(".gpkg") and os.path.exists(source):
                gpkg_path = Path(source)
            else:
                tmp_dir = Path(tempfile.mkdtemp(prefix="pbi_cloud_upload_"))
                gpkg_path = tmp_dir / f"{layer_name}.gpkg"
                result = QgsVectorFileWriter.writeAsVectorFormat(
                    layer,
                    str(gpkg_path),
                    "UTF-8",
                    layer.crs(),
                    "GPKG",
                )
                # writeAsVectorFormat returns error code (int) or tuple depending on QGIS version
                error_code = result[0] if isinstance(result, (tuple, list)) else result
                if error_code != QgsVectorFileWriter.NoError:
                    raise RuntimeError("Falha ao exportar camada para GPKG temporario.")

            self._set_upload_status("Enviando camada para o Cloud...", level="info")
            try:
                status_code, payload = cloud_session.upload_layer_gpkg(
                    file_path=str(gpkg_path),
                    name=layer_name,
                    description=description,
                    epsg=epsg,
                    group_name=group_name_value,
                )
            except RuntimeError:
                self._set_upload_status("Erro de comunicacao com o Cloud ao enviar camada.", level="error")
                return

            detail = ""
            if isinstance(payload, dict):
                detail = payload.get("detail") or payload.get("message") or payload.get("error") or ""

            if status_code in (200, 201):
                self._set_upload_status("Camada enviada para o Cloud com sucesso.", level="ok")
                # Atualiza cache remoto para refletir a nova camada
                try:
                    from .browser_integration import reload_cloud_catalog

                    reload_cloud_catalog(force_remote_only=True)
                except Exception:
                    pass
                return

            message = detail or "Erro ao enviar camada para o Cloud."
            self._set_upload_status(f"Erro ao enviar camada para o Cloud: {message}", level="error")
        except RuntimeError as exc:
            self._set_upload_status(str(exc), level="error")
        except Exception:
            self._set_upload_status("Erro ao enviar camada para o Cloud.", level="error")
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------ Helpers
    def _set_status_badge(self, level: str, text: str):
        colors = {"online": "#2F8D46", "offline": "#B3261E", "sync": "#F2994A"}
        color = colors.get(level, "#5D5A58")
        self.cloud_status_badge.setText(text)
        self.cloud_status_badge.setStyleSheet(
            f"""
            QLabel#cloudDialogStatusBadge {{
                padding: 4px 14px;
                border-radius: 14px;
                font-weight: 600;
                color: #FFFFFF;
                background-color: {color};
            }}
            """
        )

    def _format_timestamp(self, iso_text: str) -> str:
        stamp = QDateTime.fromString(iso_text, Qt.ISODate)
        if stamp.isValid():
            return stamp.toString("dd/MM HH:mm")
        return iso_text

    def _update_session_ui(self):
        payload = cloud_session.status_payload()
        level = payload.get("level") or "offline"
        status_text = payload.get("text") or "Desconectado"
        self._set_status_badge(level, status_text)
        self.remember_checkbox.setChecked(cloud_session.has_saved_credentials())
        is_auth = cloud_session.is_authenticated()
        self.login_btn.setEnabled(not is_auth)
        self.user_edit.setEnabled(not is_auth)
        self.password_edit.setEnabled(not is_auth)
        self.logout_btn.setEnabled(is_auth)
        if is_auth:
            self.user_edit.setText(cloud_session.session().get("username", ""))
        session_details = []
        if is_auth:
            session_meta = cloud_session.session()
            issued = session_meta.get("issued")
            if issued:
                session_details.append(f"Iniciada em {self._format_timestamp(issued)}.")
            if session_meta.get("mode") == "remote":
                expires_at = session_meta.get("expires_at")
                if expires_at:
                    session_details.append(f"Token expira em {self._format_timestamp(expires_at)}.")
                session_details.append("Conectado ao banco remoto configurado.")
            else:
                session_details.append("Modo demonstracao usando camadas mock.")
        else:
            session_details.append("Status: aguardando login.")
        self.session_detail.setText("\n".join(session_details))
        self.warning_label.setVisible(not cloud_session.hosting_ready())
        if not is_auth:
            # Carregamos o e-mail padrão salvo por conexão para sugerir o login.
            self._prefill_user_from_connection()
        self._update_admin_tab_visibility()

    def _update_config_ui(self):
        config = cloud_session.config()
        self.base_url_edit.setText(config.get("base_url", ""))
        self.login_endpoint_edit.setText(config.get("login_endpoint", ""))
        self.layers_endpoint_edit.setText(config.get("layers_endpoint", ""))
        self.hosting_checkbox.setChecked(bool(config.get("hosting_ready")))
        self.warning_label.setVisible(not cloud_session.hosting_ready())

    def _on_layers_changed(self):
        stamp = QDateTime.currentDateTime().toString("dd/MM HH:mm")
        self.last_sync_label.setText(stamp)
        self._refresh_upload_layers()
        self._refresh_group_choices()

    def _get_connection_registry(self):
        """Import lazy evita ciclo com browser_integration."""
        try:
            from .browser_integration import connection_registry
        except ImportError:
            return None
        return connection_registry

    def _current_connection_default_user(self) -> str:
        registry = self._get_connection_registry()
        if registry is None:
            return ""
        fingerprint = cloud_session.active_connection_fingerprint()
        if not fingerprint:
            return ""
        for conn in registry.saved_connections():
            if conn.get("fingerprint") == fingerprint:
                return conn.get("cloud_default_user", "") or ""
        return ""

    def _prefill_user_from_connection(self):
        """Carrega o login padrão salvo para a conexão ativa e preenche o campo."""
        default_user = self._current_connection_default_user()
        if default_user:
            self.user_edit.setText(default_user)

    def _persist_cloud_user_from_login(self, email: str):
        """Atualiza a conexão ativa com o login usado no último acesso Cloud."""
        fingerprint = cloud_session.active_connection_fingerprint()
        if not fingerprint or not email:
            return
        registry = self._get_connection_registry()
        if registry is None:
            return
        saved = registry.saved_connections()
        updated = False
        for conn in saved:
            if conn.get("fingerprint") == fingerprint:
                if conn.get("cloud_default_user") == email:
                    updated = False
                    break
                conn["cloud_default_user"] = email
                updated = True
                break
        if updated:
            # Persistimos o login padrão no mesmo storage de conexões usados pelo QSettings.
            registry.replace_saved_connections(saved, persist=True)

    def _is_admin_user(self) -> bool:
        return cloud_session.is_admin()

    def _update_admin_tab_visibility(self):
        # Abas Admin/Upload so ficam visiveis quando um admin estiver autenticado.
        if not hasattr(self, "admin_tab_index"):
            return
        is_admin = self._is_admin_user()
        target_tabs = [self.admin_tab_index, getattr(self, "upload_tab_index", -1)]
        for tab_index in target_tabs:
            if tab_index is None or tab_index < 0:
                continue
            if hasattr(self.tabs, "setTabVisible"):
                self.tabs.setTabVisible(tab_index, is_admin)
            else:
                self.tabs.setTabEnabled(tab_index, is_admin)
                tab_widget = self.tabs.widget(tab_index)
                if tab_widget is not None:
                    tab_widget.setVisible(is_admin)
        if hasattr(self, "upload_button"):
            self.upload_button.setEnabled(is_admin)
        if not is_admin and self.tabs.currentIndex() in target_tabs:
            self.tabs.setCurrentIndex(self.session_tab_index if hasattr(self, "session_tab_index") else 0)

    def _select_initial_tab(self, initial_tab: Optional[str]):
        if not initial_tab:
            return
        key = initial_tab.strip().lower()
        tab_map = {
            "sessao": self.session_tab_index,
            "session": self.session_tab_index,
            "config": self.config_tab_index,
            "configuracoes": self.config_tab_index,
            "admin": self.admin_tab_index,
            "upload": getattr(self, "upload_tab_index", -1),
        }
        target = tab_map.get(key, -1)
        if target is not None and target >= 0:
            admin_tabs = {self.admin_tab_index, getattr(self, "upload_tab_index", -1)}
            if target in admin_tabs and not self._is_admin_user():
                return
            try:
                if hasattr(self.tabs, "isTabEnabled") and not self.tabs.isTabEnabled(target):
                    return
            except Exception:
                pass
            self.tabs.setCurrentIndex(target)


def open_cloud_dialog(parent: Optional[QWidget] = None, initial_tab: Optional[str] = None) -> PowerBICloudDialog:
    """Helper used by different entry points."""
    dialog = PowerBICloudDialog(parent, initial_tab=initial_tab)
    dialog.exec_()
    return dialog


__all__ = ["PowerBICloudDialog", "open_cloud_dialog"]
