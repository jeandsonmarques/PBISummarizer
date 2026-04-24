import json
import uuid
from collections import deque
from typing import Dict, List, Optional, Tuple

import pandas as pd  # type: ignore
from qgis.PyQt.QtCore import QPointF, QSettings, Qt, QTimer, QRectF, QVariant
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsMessageLog,
    QgsProject,
    QgsRelation,
    QgsWkbTypes,
    QgsVectorLayer,
    Qgis,
)

from .model_canvas_scene import ModelCanvasScene
from .model_canvas_view import ModelCanvasView
from .relationship_item import RelationshipItem
from .table_card_item import TableCardItem
from ..utils.plugin_logging import log_info


class ModelManager:
    """Converte dados do plugin em itens graficos e gerencia layout/persistencia."""

    def __init__(
        self,
        scene: ModelCanvasScene,
        view: ModelCanvasView,
        host=None,
    ):
        self.scene = scene
        self.view = view
        self.host = host
        self.scene.manager = self

        self.tables: Dict[str, TableCardItem] = {}
        self.relationships: Dict[str, RelationshipItem] = {}
        self.available_tables: Dict[str, Dict] = {}
        self.available_relationships: List[Dict] = []
        self._state_key = "PowerBISummarizer/model/layout"
        self._connection_style = "curved"
        self._layout_spacing_x = 120.0
        self._layout_spacing_y = 60.0
        self._legend_visible = True
        self._saved_state = self._load_state()
        self._needs_initial_layout = not self._has_any_saved_positions(self._saved_state)
        if isinstance(self._saved_state, dict):
            style = str(self._saved_state.get("connection_style") or self._connection_style).lower()
            if style in ("curved", "orthogonal", "straight"):
                self._connection_style = style
            if "legend_visible" in self._saved_state:
                self._legend_visible = bool(self._saved_state.get("legend_visible"))
        self._current_preview_rel_id: Optional[str] = None
        self._last_final_join_count: int = 0
        self._virtual_fields_cache: Dict[str, List[str]] = {}

        try:
            self.view.zoomChanged.connect(self._on_zoom_changed)
        except Exception:
            pass
        try:
            self.scene.selectionChanged.connect(self._handle_selection_changed)
        except Exception:
            pass

    # ------------------------------------------------------------------ Data load
    def refresh_model(self, restore_visible: bool = True):
        self._log("refresh_model() chamado")
        self._current_preview_rel_id = None
        self._virtual_fields_cache = {}
        self._saved_state = self._load_state()
        self._needs_initial_layout = False
        if isinstance(self._saved_state, dict):
            style = str(self._saved_state.get("connection_style") or self._connection_style).lower()
            if style in ("curved", "orthogonal", "straight"):
                self._connection_style = style
            if "legend_visible" in self._saved_state:
                self._legend_visible = bool(self._saved_state.get("legend_visible"))
        self.scene.clear()
        self.tables.clear()
        self.relationships.clear()
        self.available_tables.clear()
        self.available_relationships.clear()

        for table in self._collect_tables():
            self.available_tables[table["name"]] = table

        relationships_data = self._collect_relationships()
        relationships_data.extend(self._saved_state.get("relationships", []))
        self.available_relationships = relationships_data

        visible_tables = self._saved_state.get("visible_tables", []) if restore_visible else []

        self.restore_layout_state(visible_tables)
        try:
            self.recompute_all_virtual_fields()
        except Exception:
            pass

    def restore_layout_state(self, visible_tables: Optional[List[str]] = None):
        self._log("restore_layout_state() chamado")
        state = self._saved_state if isinstance(self._saved_state, dict) else {}
        style = str(state.get("connection_style") or self._connection_style).lower() if isinstance(state, dict) else ""
        if style in ("curved", "orthogonal", "straight"):
            self._connection_style = style
        if isinstance(state, dict) and "legend_visible" in state:
            self._legend_visible = bool(state.get("legend_visible"))
        tables_to_restore = visible_tables if visible_tables is not None else list(state.get("visible_tables", []) or [])
        seen = set()
        for name in tables_to_restore:
            if not name or name in seen:
                continue
            seen.add(name)
            try:
                self.add_table_to_canvas(name, use_saved_position=True, persist=False)
            except Exception:
                pass

        saved_zoom = state.get("zoom") if isinstance(state, dict) else None
        if isinstance(saved_zoom, (int, float)) and saved_zoom > 0:
            try:
                self.view.resetTransform()
                self.view._zoom = 1.0  # sync internal zoom state
                self.view.set_zoom(float(saved_zoom))
            except Exception:
                pass

    def _place_only_new_tables(self, new_items: Optional[List[TableCardItem]] = None):
        """Posiciona apenas itens explicitamente informados; não altera cartões existentes."""
        if not new_items:
            return
        state = self._saved_state if isinstance(self._saved_state, dict) else {}
        saved_positions = state.get("tables", {}) if isinstance(state, dict) else {}
        anchored_items: List[TableCardItem] = [item for item in self.tables.values() if item not in new_items]

        placed_any = False
        for item in new_items:
            name = getattr(item, "table_name", "")
            pos_info = saved_positions.get(name) if isinstance(saved_positions, dict) else None
            if isinstance(pos_info, dict) and "x" in pos_info and "y" in pos_info:
                continue  # já tem posição salva; não mover
            pos = self._suggest_position_for_new_table(item, existing_items=anchored_items)
            item.setPos(pos)
            self._log(f"_place_only_new_tables posicionou '{name}' em ({pos.x():.1f}, {pos.y():.1f})")
            anchored_items.append(item)
            placed_any = True

        if placed_any:
            self._update_all_relationship_paths()
            self.save_layout_state()

    # -------------------------------------------------------------- Availability
    def get_available_tables(self) -> List[Dict]:
        return list(self.available_tables.values())

    def iter_tables_for_reports(self):
        """Expose tables/fields for the reports pane."""
        tables = self.get_available_tables()
        if tables:
            QgsMessageLog.logMessage(
                f"[PBI Summarizer] iter_tables_for_reports -> {len(tables)} tabelas (available_tables)",
                "PowerBI Summarizer",
                level=Qgis.Info,
            )
        else:
            # Fallback: use tables currently on the canvas (with their field items)
            fallback_tables = []
            for item in self.tables.values():
                fields_data = list(item.fields_data or [])
                if not fields_data and item.field_items:
                    for f in item.field_items:
                        fields_data.append(
                            {
                                "name": getattr(f, "field_name", ""),
                                "type": getattr(f, "data_type", ""),
                                "is_primary": getattr(f, "is_primary_key", False),
                                "is_foreign": getattr(f, "is_foreign_key", False),
                            }
                        )
                fallback_tables.append({"name": item.table_name, "display_name": item.table_name, "fields": fields_data})
            tables = fallback_tables
            QgsMessageLog.logMessage(
                f"[PBI Summarizer] iter_tables_for_reports (fallback canvas) -> {len(tables)} tabelas",
                "PowerBI Summarizer",
                level=Qgis.Info,
            )

        canvas_order = None
        try:
            canvas_order = list(self.tables_on_canvas())
        except Exception:
            canvas_order = None
        for table in tables:
            name = table.get("name")
            display = table.get("display_name") or name
            fields = table.get("fields") or []
            yield {"name": name, "display_name": display, "fields": fields}

    def is_table_on_canvas(self, name: str) -> bool:
        return name in self.tables

    @property
    def connection_style(self) -> str:
        return self._connection_style

    def set_connection_style(self, style: str):
        style_normalized = str(style or "").lower()
        if style_normalized not in ("curved", "orthogonal", "straight"):
            style_normalized = "curved"
        if style_normalized == self._connection_style:
            return
        self._connection_style = style_normalized
        self._update_all_relationship_paths()
        self._save_state()

    @property
    def legend_visible(self) -> bool:
        return bool(self._legend_visible)

    def set_legend_visible(self, visible: bool):
        visible = bool(visible)
        if visible == self._legend_visible:
            return
        self._legend_visible = visible
        self._save_state()

    # ----------------------------------------------------------- Table management
    def add_table_to_canvas(self, name: str, use_saved_position: bool = True, persist: bool = True) -> Optional[TableCardItem]:
        if not name or name not in self.available_tables:
            return None
        if name in self.tables:
            return self.tables[name]

        table = self.available_tables[name]
        existing_items = list(self.tables.values())
        item = TableCardItem(table["name"], table["fields"])
        self.scene.addItem(item)
        self.tables[name] = item

        saved_positions = self._saved_state.get("tables", {}) if isinstance(self._saved_state, dict) else {}
        pos_info = saved_positions.get(name) if use_saved_position else None
        if pos_info and isinstance(pos_info, dict):
            x, y = pos_info.get("x"), pos_info.get("y")
            if x is not None and y is not None:
                item.setPos(QPointF(float(x), float(y)))
        else:
            item.setPos(self._suggest_position_for_new_table(item, existing_items))

        self._rebuild_relationships_for_canvas()
        if persist:
            self._save_state()
        return item

    def remove_table_from_canvas(self, name: str):
        item = self.tables.pop(name, None)
        if item is None:
            return
        try:
            self.scene.removeItem(item)
        except Exception:
            pass
        self._rebuild_relationships_for_canvas()
        self._save_state()

    def tables_on_canvas(self) -> List[str]:
        return list(self.tables.keys())

    def ensure_tables_on_canvas(self, table_names: List[str]):
        """Garantir que as tabelas informadas estejam no canvas (sem duplicar)."""
        for name in table_names or []:
            try:
                self.add_table_to_canvas(name, use_saved_position=True, persist=False)
            except Exception:
                pass
        self._save_state()

    def relationship_item_by_id(self, rel_id: Optional[str]) -> Optional[RelationshipItem]:
        if not rel_id:
            return None
        return self.relationships.get(rel_id)

    def create_relationship_from_metadata(self, metadata: Dict) -> Optional[RelationshipItem]:
        """Cria relacionamento a partir de metadados e o adiciona ao estado."""
        if not metadata:
            return None
        source = metadata.get("source_table")
        target = metadata.get("target_table")
        if not source or not target:
            return None
        try:
            self.ensure_tables_on_canvas([source, target])
        except Exception:
            pass

        rel_id = metadata.get("id")
        self._create_relationship(metadata)
        if rel_id is None and metadata.get("id"):
            rel_id = metadata.get("id")
        if metadata not in self.available_relationships:
            self.available_relationships.append(dict(metadata))
        if rel_id:
            item = self.relationships.get(rel_id)
            if item is not None:
                self._save_state()
                try:
                    self.recompute_all_virtual_fields()
                except Exception:
                    pass
                return item
        # fallback: return any recent relationship matching tables
        for item in self.relationships.values():
            data = item.metadata or {}
            if (
                data.get("source_table") == source
                and data.get("target_table") == target
                and data.get("source_field") == metadata.get("source_field")
                and data.get("target_field") == metadata.get("target_field")
            ):
                self._save_state()
                try:
                    self.recompute_all_virtual_fields()
                except Exception:
                    pass
                return item
        return None

    # ----------------------------------------------------------- Selection helpers
    def _find_relationship_item_between(self, left: str, right: str) -> Optional[RelationshipItem]:
        for rel in self.relationships.values():
            src = rel.metadata.get("source_table")
            dst = rel.metadata.get("target_table")
            if {src, dst} == {left, right}:
                return rel
        return None

    def selected_relationship(self) -> Optional[RelationshipItem]:
        scene_items = self.scene.selectedItems()
        for item in scene_items:
            if isinstance(item, RelationshipItem):
                return item
        return None

    # ----------------------------------------------------------- Preview helpers
    def _fields_for_table(self, table_name: str) -> List[str]:
        if not table_name:
            return []
        data = self.available_tables.get(table_name) or {}
        names = []
        for field in data.get("fields", []):
            name = field.get("name") or field.get("field")
            if name:
                names.append(str(name))
        if not names:
            table_item = self.tables.get(table_name)
            if table_item is not None:
                names = [item.field_name for item in table_item.field_items]
        return names

    def _normalize_direction(self, direction: Optional[str]) -> str:
        direction = str(direction or "both").lower()
        if direction in ("forward", "origem", "source", "single", "source_to_target"):
            return "forward"
        if direction in ("backward", "destino", "target", "target_to_source", "reverse"):
            return "backward"
        return "both"

    def _default_selected_fields(self, table_name: Optional[str], exclude_field: Optional[str]) -> List[str]:
        names = self._fields_for_table(table_name or "")
        exclude = str(exclude_field or "").lower()
        return [n for n in names if str(n).lower() != exclude]

    def _ensure_field_selections(self, metadata: Dict, persist: bool = False):
        direction = self._normalize_direction(metadata.get("direction") or metadata.get("flow_direction"))
        if "selected_fields_origin_to_dest" not in metadata:
            metadata["selected_fields_origin_to_dest"] = self._default_selected_fields(
                metadata.get("source_table"), metadata.get("source_field")
            )
        if "selected_fields_dest_to_origin" not in metadata:
            metadata["selected_fields_dest_to_origin"] = self._default_selected_fields(
                metadata.get("target_table"), metadata.get("target_field")
            )
        metadata["direction"] = direction
        if persist:
            self._update_available_relationship_metadata(metadata.get("id"), metadata)

    def _update_available_relationship_metadata(self, rel_id: Optional[str], metadata: Dict):
        if not rel_id:
            return
        for rel in self.available_relationships:
            if rel.get("id") == rel_id:
                rel.update(metadata)
                break

    def get_virtual_fields_preview(self, relationship: RelationshipItem) -> Tuple[List[str], List[str]]:
        if relationship is None:
            return [], []
        data = relationship.metadata or {}
        table_a = data.get("source_table")
        table_b = data.get("target_table")
        field_a = data.get("source_field")
        field_b = data.get("target_field")
        if not table_a or not table_b:
            return [], []

        fields_a = self._fields_for_table(table_a)
        fields_b = self._fields_for_table(table_b)
        preview_a = [f"{table_b}.{name}" for name in fields_b if name and str(name).lower() != str(field_b).lower()]
        preview_b = [f"{table_a}.{name}" for name in fields_a if name and str(name).lower() != str(field_a).lower()]
        return preview_a, preview_b

    def _build_relation_flows(self) -> List[Dict]:
        flows: List[Dict] = []
        for rel in self.relationships.values():
            meta = rel.metadata or {}
            meta.setdefault("id", meta.get("id") or uuid.uuid4().hex)
            direction = self._normalize_direction(meta.get("direction") or meta.get("flow_direction"))
            meta["direction"] = direction
            self._ensure_field_selections(meta, persist=True)
            rel.metadata = meta

            src_table = meta.get("source_table")
            dst_table = meta.get("target_table")
            src_field = meta.get("source_field")
            dst_field = meta.get("target_field")
            if not src_table or not dst_table or not src_field or not dst_field:
                self._log("Relacionamento ignorado no preview: informacao de tabela/campo ausente.")
                continue

            if direction in ("forward", "both"):
                flows.append(
                    {
                        "rel": rel,
                        "origin_table": src_table,
                        "dest_table": dst_table,
                        "origin_field": src_field,
                        "dest_field": dst_field,
                        "selected_fields": list(meta.get("selected_fields_origin_to_dest") or []),
                    }
                )
            if direction in ("backward", "both"):
                flows.append(
                    {
                        "rel": rel,
                        "origin_table": dst_table,
                        "dest_table": src_table,
                        "origin_field": dst_field,
                        "dest_field": src_field,
                        "selected_fields": list(meta.get("selected_fields_dest_to_origin") or []),
                    }
                )
        return flows

    # ----------------------------------------------------------- Layer helpers
    def _layer_for_table(self, table_name: str) -> Optional[QgsVectorLayer]:
        if not table_name:
            return None
        data = self.available_tables.get(table_name, {})
        layer_id = data.get("layer_id")
        project = QgsProject.instance()
        if layer_id:
            layer = project.mapLayer(layer_id)
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                return layer
        for layer in project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.name() == table_name and layer.isValid():
                return layer
        return None

    def relationship_context(self, rel_item: RelationshipItem) -> Optional[Tuple[QgsVectorLayer, QgsVectorLayer, str, str]]:
        if rel_item is None:
            return None
        data = rel_item.metadata or {}
        src_layer = self._layer_for_table(data.get("source_table"))
        dst_layer = self._layer_for_table(data.get("target_table"))
        if src_layer is None or dst_layer is None:
            return None
        return src_layer, dst_layer, data.get("source_field"), data.get("target_field")

    def _tables_for_relationship(self, relationship: RelationshipItem) -> Tuple[Optional[TableCardItem], Optional[TableCardItem]]:
        if relationship is None:
            return None, None
        data = relationship.metadata or {}
        table_a = self.tables.get(data.get("source_table"))
        table_b = self.tables.get(data.get("target_table"))
        if table_a is None:
            parent_a = relationship.source_field.parentItem()
            if isinstance(parent_a, TableCardItem):
                table_a = parent_a
        if table_b is None:
            parent_b = relationship.target_field.parentItem()
            if isinstance(parent_b, TableCardItem):
                table_b = parent_b
        return table_a, table_b

    def _clear_all_virtual_fields(self):
        for table in self.tables.values():
            try:
                table.clear_virtual_fields()
            except Exception:
                pass
        self._virtual_fields_cache = {}

    def recompute_all_virtual_fields(self):
        """
        Calcula os campos virtuais de todas as tabelas com base em TODAS as
        relacoes existentes, respeitando a direcao e os campos selecionados.
        """
        try:
            self._clear_all_virtual_fields()
            flows = self._build_relation_flows()
            if not flows:
                return

            virtual_fields: Dict[str, List[str]] = {name: [] for name in self.tables.keys()}
            max_iter = max(1, len(self.tables) * 3)

            for _ in range(max_iter):
                changed = False
                for flow in flows:
                    origin = flow["origin_table"]
                    dest = flow["dest_table"]
                    if origin not in self.tables or dest not in self.tables:
                        self._log(f"Preview ignorado para {origin}->{dest}: tabela fora do canvas.")
                        continue

                    origin_virtual = virtual_fields.get(origin, [])
                    direct = [f"{origin}.{name}" for name in flow.get("selected_fields", []) if name]
                    propagated = direct + origin_virtual

                    dest_virtual = virtual_fields.get(dest, [])
                    for name in propagated:
                        if name not in dest_virtual:
                            dest_virtual.append(name)
                            changed = True
                    virtual_fields[dest] = dest_virtual

                if not changed:
                    break

            self._virtual_fields_cache = virtual_fields
            for table_name, table_item in self.tables.items():
                try:
                    table_item.set_virtual_fields(virtual_fields.get(table_name, []))
                except Exception:
                    pass
        except Exception as exc:
            self._log(f"Erro ao recalcular campos virtuais: {exc}")

    def refresh_relationship_paths(self, table_item: TableCardItem):
        for rel in self.relationships.values():
            if rel.source_field.parentItem() is table_item or rel.target_field.parentItem() is table_item:
                rel.update_path()

    def _apply_preview_for_relationship(self, relationship: RelationshipItem):
        self._clear_all_virtual_fields()
        table_a, table_b = self._tables_for_relationship(relationship)
        if table_a is None or table_b is None:
            return
        preview_a, preview_b = self.get_virtual_fields_preview(relationship)
        try:
            table_a.set_virtual_fields(preview_a)
        except Exception:
            pass
        try:
            table_b.set_virtual_fields(preview_b)
        except Exception:
            pass
        try:
            self.refresh_relationship_paths(table_a)
            self.refresh_relationship_paths(table_b)
        except Exception:
            pass

    def _handle_selection_changed(self):
        try:
            self.recompute_all_virtual_fields()
        except Exception:
            pass

    # ----------------------------------------------------------- Simple join (nivel 2)
    def _log(self, message: str):
        try:
            log_info(message)
        except Exception:
            pass

    def _warn_user(self, title: str, message: str):
        try:
            QMessageBox.warning(self.view, title, message)
        except Exception:
            pass

    def _add_layer_to_project_async(self, layer: QgsVectorLayer):
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            self._log("Camada resultante invalida; nao sera adicionada ao projeto.")
            return

        def _do_add():
            try:
                QgsProject.instance().addMapLayer(layer)
            except Exception as exc:
                self._log(f"Falha ao adicionar camada ao projeto: {exc}")

        try:
            QTimer.singleShot(0, _do_add)
        except Exception as exc:
            self._log(f"QTimer indisponivel, adicionando imediatamente: {exc}")
            _do_add()

    def _parse_cardinality(self, metadata: Optional[Dict]) -> Tuple[str, str]:
        card = str((metadata or {}).get("cardinality") or "1:*")
        if ":" in card:
            left, right = card.split(":", 1)
        elif "/" in card:
            left, right = card.split("/", 1)
        else:
            left = right = card
        return left.strip() or "1", right.strip() or "*"

    def _layer_has_geometry(self, layer: QgsVectorLayer) -> bool:
        try:
            return layer.wkbType() != QgsWkbTypes.NoGeometry
        except Exception:
            return False

    def _valid_provider(self, layer: QgsVectorLayer) -> bool:
        try:
            provider = layer.dataProvider()
        except Exception:
            return False
        if provider is None:
            return False
        try:
            return provider.isValid()
        except Exception:
            return True

    def _choose_base_layer(
        self,
        src_layer: QgsVectorLayer,
        dst_layer: QgsVectorLayer,
        src_field: str,
        dst_field: str,
        metadata: Optional[Dict],
    ) -> Tuple[QgsVectorLayer, QgsVectorLayer, str, str]:
        left, right = self._parse_cardinality(metadata)
        star_src = left.startswith("*")
        star_dst = right.startswith("*")
        src_geom = self._layer_has_geometry(src_layer)
        dst_geom = self._layer_has_geometry(dst_layer)

        base_layer = src_layer
        origin_layer = dst_layer
        base_field = src_field
        origin_field = dst_field

        if src_geom and not dst_geom:
            base_layer, origin_layer = src_layer, dst_layer
            base_field, origin_field = src_field, dst_field
        elif dst_geom and not src_geom:
            base_layer, origin_layer = dst_layer, src_layer
            base_field, origin_field = dst_field, src_field
        elif src_geom and dst_geom:
            if star_src and not star_dst:
                base_layer, origin_layer = src_layer, dst_layer
                base_field, origin_field = src_field, dst_field
            elif star_dst and not star_src:
                base_layer, origin_layer = dst_layer, src_layer
                base_field, origin_field = dst_field, src_field
        else:
            if star_dst and not star_src:
                base_layer, origin_layer = dst_layer, src_layer
                base_field, origin_field = dst_field, src_field

        return base_layer, origin_layer, base_field, origin_field

    def _fields_to_copy_for_flow(
        self, flow: Dict, origin_layer: QgsVectorLayer, base_fields_map: Dict[str, set]
    ) -> List[str]:
        selected = [str(name) for name in flow.get("selected_fields", []) if name]
        origin_lookup = {f.name().lower(): f.name() for f in origin_layer.fields()}
        origin_name = flow.get("origin_table")
        origin_field = str(flow.get("origin_field") or "").lower()

        fields: List[str] = []
        for name in selected:
            real = origin_lookup.get(name.lower())
            if real is None:
                self._log(f"Campo '{name}' nao encontrado em {origin_name}; ignorado no join.")
                continue
            if real.lower() == origin_field:
                continue
            if real not in fields:
                fields.append(real)

        base_fields = base_fields_map.get(origin_name, set())
        for field in origin_layer.fields():
            fname = field.name()
            lower = fname.lower()
            if lower in base_fields:
                continue
            if lower == origin_field:
                continue
            if fname not in fields:
                fields.append(fname)
        return fields

    def _run_simple_left_join(
        self,
        base_layer: QgsVectorLayer,
        origin_layer: QgsVectorLayer,
        base_field: str,
        origin_field: str,
        fields_to_copy: Optional[List[str]] = None,
        layer_name: Optional[str] = None,
        warn_user: bool = True,
    ) -> Optional[QgsVectorLayer]:
        if base_layer is None or origin_layer is None:
            msg = "Camadas de entrada invalidas."
            if warn_user:
                self._warn_user("Gerar camada unificada", msg)
            else:
                self._log(f"Join abortado: {msg}")
            return None

        if not base_field or not origin_field:
            msg = "Campos de relacionamento nao informados."
            if warn_user:
                self._warn_user("Gerar camada unificada", msg)
            else:
                self._log(f"Join abortado: {msg}")
            return None

        if not self._valid_provider(base_layer) or not self._valid_provider(origin_layer):
            msg = "Uma das camadas nao possui provider valido."
            if warn_user:
                self._warn_user("Gerar camada unificada", msg)
            else:
                self._log(f"Join abortado: {msg}")
            return None

        base_idx = base_layer.fields().indexFromName(base_field)
        origin_idx = origin_layer.fields().indexFromName(origin_field)
        if base_idx < 0 or origin_idx < 0:
            msg = "Campos de relacionamento nao encontrados nas camadas selecionadas."
            if warn_user:
                self._warn_user("Gerar camada unificada", msg)
            else:
                self._log(f"Join abortado: {msg} ({base_field}, {origin_field})")
            return None

        if fields_to_copy is None:
            fields_to_copy = [f.name() for f in origin_layer.fields()]
        else:
            fields_to_copy = [f for f in fields_to_copy if f]
        if not fields_to_copy:
            msg = "Nenhum campo selecionado para copia."
            if warn_user:
                self._warn_user("Gerar camada unificada", msg)
            else:
                self._log(f"Join ignorado: {msg}")
            return None
        result_layer: Optional[QgsVectorLayer] = None
        try:
            import processing  # type: ignore

            params = {
                "INPUT": base_layer,
                "FIELD": base_field,
                "INPUT_2": origin_layer,
                "FIELD_2": origin_field,
                "FIELDS_TO_COPY": fields_to_copy,
                "METHOD": 1,
                "DISCARD_NONMATCHING": False,
                "PREFIX": "",
                "OUTPUT": "memory:",
            }
            output = processing.run("native:joinattributestable", params).get("OUTPUT")
            if isinstance(output, QgsVectorLayer) and output.isValid():
                result_layer = output
            else:
                result_layer = QgsVectorLayer(output, layer_name or "joined_layer", "ogr")
        except Exception as exc:
            self._log(f"Fallback para join manual: {exc}")
            result_layer = self._manual_join(
                origin_layer, base_layer, origin_field, base_field, fields_to_copy, layer_name or "joined_layer"
            )

        if result_layer is None or not result_layer.isValid():
            msg = "Nao foi possivel criar a camada temporaria."
            if warn_user:
                self._warn_user("Gerar camada unificada", msg)
            else:
                self._log(f"Join falhou: {msg}")
            return None

        if layer_name:
            try:
                result_layer.setName(layer_name)
            except Exception:
                pass
        return result_layer

    def simple_join_from_relationship(
        self, relationship: RelationshipItem, warn_user: bool = True, add_to_project: bool = False
    ) -> Optional[QgsVectorLayer]:
        ctx = self.relationship_context(relationship)
        if ctx is None:
            if warn_user:
                self._warn_user("Gerar camada unificada", "Selecione um relacionamento valido com camadas do QGIS.")
            return None

        src_layer, dst_layer, src_field, dst_field = ctx
        if not src_field or not dst_field:
            if warn_user:
                self._warn_user("Gerar camada unificada", "Campos do relacionamento nao encontrados.")
            return None

        meta = relationship.metadata or {}
        self._ensure_field_selections(meta, persist=True)
        direction = self._normalize_direction(meta.get("direction") or meta.get("flow_direction"))
        relationship.metadata = meta
        self._update_available_relationship_metadata(meta.get("id"), meta)

        if direction == "forward":
            base_layer, origin_layer, base_field, origin_field = dst_layer, src_layer, dst_field, src_field
            fields_to_copy = list(meta.get("selected_fields_origin_to_dest") or [])
        elif direction == "backward":
            base_layer, origin_layer, base_field, origin_field = src_layer, dst_layer, src_field, dst_field
            fields_to_copy = list(meta.get("selected_fields_dest_to_origin") or [])
        else:
            base_layer, origin_layer, base_field, origin_field = self._choose_base_layer(
                src_layer, dst_layer, src_field, dst_field, relationship.metadata
            )
            if base_layer is src_layer:
                fields_to_copy = list(meta.get("selected_fields_dest_to_origin") or [])
            else:
                fields_to_copy = list(meta.get("selected_fields_origin_to_dest") or [])
            self._log("Direcao 'ambos' detectada: heuristica aplicada para join simples.")

        layer_name = f"{base_layer.name()}_join_{origin_layer.name()}"
        layer = self._run_simple_left_join(
            base_layer=base_layer,
            origin_layer=origin_layer,
            base_field=base_field,
            origin_field=origin_field,
            fields_to_copy=fields_to_copy,
            layer_name=layer_name,
            warn_user=warn_user,
        )
        if layer is None or not layer.isValid():
            return None

        if add_to_project:
            self._add_layer_to_project_async(layer)
        return layer

    def build_final_layer_from_main_table(
        self, main_table: TableCardItem, layer_name: Optional[str] = None, warn_user: bool = True
    ) -> Optional[QgsVectorLayer]:
        """
        Usa main_table como base e aplica LEFT JOIN em cadeia seguindo a direcao
        e os campos selecionados de cada relacao.
        """
        self._last_final_join_count = 0
        if main_table is None:
            if warn_user:
                self._warn_user("Gerar camada unificada", "Selecione uma tabela valida.")
            return None

        main_layer = self._layer_for_table(main_table.table_name)
        if main_layer is None or not self._valid_provider(main_layer):
            msg = "A tabela selecionada nao possui camada QGIS valida."
            if warn_user:
                self._warn_user("Gerar camada unificada", msg)
            else:
                self._log(msg)
            return None

        flows = self._build_relation_flows()
        if not flows:
            if warn_user:
                self._warn_user("Gerar camada unificada", "Nao ha relacoes disponiveis para gerar a camada final.")
            return None

        target_tables = {main_table.table_name}
        for _ in range(len(flows) + 1):
            changed = False
            for flow in flows:
                if flow["dest_table"] in target_tables and flow["origin_table"] not in target_tables:
                    target_tables.add(flow["origin_table"])
                    changed = True
            if not changed:
                break
        flows = [f for f in flows if f["dest_table"] in target_tables]

        base_fields_map: Dict[str, set] = {}
        for table_name in target_tables:
            base_fields = {str(n).lower() for n in self._fields_for_table(table_name)}
            if not base_fields:
                layer = self._layer_for_table(table_name)
                if layer is not None:
                    base_fields = {field.name().lower() for field in layer.fields()}
            base_fields_map[table_name] = base_fields

        layer_cache: Dict[str, Optional[QgsVectorLayer]] = {}
        building: set = set()

        def build_layer(table_name: str) -> Optional[QgsVectorLayer]:
            if table_name in layer_cache:
                return layer_cache[table_name]
            if table_name in building:
                self._log(f"Ciclo de relacoes detectado envolvendo '{table_name}'.")
                return layer_cache.get(table_name)

            layer = self._layer_for_table(table_name)
            if layer is None or not self._valid_provider(layer):
                self._log(f"Camada '{table_name}' invalida; relacoes dependentes ignoradas.")
                layer_cache[table_name] = None
                return None

            layer_cache[table_name] = layer
            building.add(table_name)
            current_layer = layer
            inbound_flows = [f for f in flows if f["dest_table"] == table_name]
            for flow in inbound_flows:
                origin_layer = build_layer(flow["origin_table"])
                if origin_layer is None:
                    self._log(
                        f"Join ignorado: camada '{flow['origin_table']}' ausente para {table_name}.{flow['dest_field']}."
                    )
                    continue
                if flow["origin_table"] not in base_fields_map:
                    origin_base = {str(n).lower() for n in self._fields_for_table(flow["origin_table"])}
                    if not origin_base:
                        origin_base = {field.name().lower() for field in origin_layer.fields()}
                    base_fields_map[flow["origin_table"]] = origin_base
                fields_to_copy = self._fields_to_copy_for_flow(flow, origin_layer, base_fields_map)
                if not fields_to_copy:
                    self._log(
                        f"Join ignorado: nenhum campo selecionado/virtual de {flow['origin_table']} para {table_name}."
                    )
                    continue

                result = self._run_simple_left_join(
                    base_layer=current_layer,
                    origin_layer=origin_layer,
                    base_field=flow["dest_field"],
                    origin_field=flow["origin_field"],
                    fields_to_copy=fields_to_copy,
                    layer_name=None,
                    warn_user=False,
                )
                if result is None:
                    self._log(
                        f"Join falhou: {table_name}.{flow['dest_field']} <- {flow['origin_table']}."
                    )
                    continue

                current_layer = result
                layer_cache[table_name] = current_layer
                self._last_final_join_count += 1

            building.remove(table_name)
            layer_cache[table_name] = current_layer
            return current_layer

        result_layer = build_layer(main_table.table_name)
        if result_layer is None or not result_layer.isValid():
            if warn_user:
                self._warn_user(
                    "Gerar camada unificada",
                    "Nao foi possivel gerar a camada final a partir das relacoes disponiveis.",
                )
            return None

        if self._last_final_join_count == 0:
            msg = "Nenhum join aplicado para gerar a camada final."
            if warn_user:
                self._warn_user("Gerar camada unificada", msg)
            else:
                self._log(msg)
            return None

        output_name = layer_name or f"{main_layer.name()}_final_modelo"
        try:
            result_layer.setName(output_name)
        except Exception:
            pass
        return result_layer

    def export_table_layer_with_inheritance(self, table_item: TableCardItem) -> Optional[QgsVectorLayer]:
        if table_item is None:
            return None
        layer_name = f"{table_item.table_name}_export_preview"
        layer = self.build_final_layer_from_main_table(table_item, layer_name=layer_name, warn_user=True)
        if layer is None or not layer.isValid():
            self._log(f"Exportacao abortada para '{table_item.table_name}'.")
            return None
        self._add_layer_to_project_async(layer)
        self._log(f"Camada exportada: {layer.name()}")
        return layer

    # -------------------------------------------------------------- Unified layer
    def generate_unified_layer(
        self,
        rel_item: RelationshipItem,
        selected_fields: List[str],
        output_mode: str = "memory",
        output_path: Optional[str] = None,
        layer_name: Optional[str] = None,
        add_to_project: bool = True,
    ):
        ctx = self.relationship_context(rel_item)
        if ctx is None:
            raise ValueError("Relacao nao corresponde a camadas QGIS validas.")
        src_layer, dst_layer, src_field, dst_field = ctx
        if not src_field or not dst_field:
            raise ValueError("Campos de join ausentes.")

        layer_name = layer_name or f"{dst_layer.name()}_join_{src_layer.name()}"
        if output_mode == "gpkg":
            if not output_path:
                raise ValueError("Informe o caminho do arquivo GPKG.")
            if not output_path.lower().endswith(".gpkg"):
                output_path = f"{output_path}.gpkg"
            output_uri = f"{output_path}|layername={layer_name}"
        else:
            output_uri = "memory:"

        # Try processing-based join
        try:
            import processing  # type: ignore

            params = {
                "INPUT": dst_layer,
                "FIELD": dst_field,
                "INPUT_2": src_layer,
                "FIELD_2": src_field,
                "FIELDS_TO_COPY": selected_fields or [],
                "METHOD": 1,
                "DISCARD_NONMATCHING": False,
                "PREFIX": "",
                "OUTPUT": output_uri,
            }
            result = processing.run("native:joinattributestable", params)
            output = result.get("OUTPUT")
            if isinstance(output, QgsVectorLayer) and output.isValid():
                layer = output
            else:
                layer = QgsVectorLayer(output, layer_name, "ogr")
        except Exception:
            if output_mode == "gpkg":
                raise
            layer = self._manual_join(src_layer, dst_layer, src_field, dst_field, selected_fields, layer_name)

        if layer is None or not layer.isValid():
            raise ValueError("Nao foi possivel criar a camada resultante.")

        if add_to_project:
            self._add_layer_to_project_async(layer)
        return layer

    def _manual_join(
        self,
        origin_layer: QgsVectorLayer,
        base_layer: QgsVectorLayer,
        origin_field: str,
        base_field: str,
        selected_fields: List[str],
        layer_name: str,
    ) -> Optional[QgsVectorLayer]:
        base_fields = QgsFields(base_layer.fields())
        origin_fields = origin_layer.fields()

        selected_fields = list(selected_fields) if selected_fields is not None else [f.name() for f in origin_fields]
        existing = {f.name().lower() for f in base_fields}
        origin_indexes = []
        for name in selected_fields:
            idx = origin_fields.indexFromName(name)
            if idx < 0:
                continue
            safe_name = name
            if safe_name.lower() in existing:
                safe_name = f"{origin_layer.name()}_{name}"
            base_fields.append(QgsField(safe_name, origin_fields[idx].type()))
            existing.add(safe_name.lower())
            origin_indexes.append((idx, safe_name))

        geom_str = QgsWkbTypes.displayString(base_layer.wkbType()) or "Point"
        crs_authid = base_layer.crs().authid()
        mem_uri = f"{geom_str}?crs={crs_authid}"
        mem_layer = QgsVectorLayer(mem_uri, layer_name, "memory")
        provider = mem_layer.dataProvider()
        provider.addAttributes(list(base_fields))
        mem_layer.updateFields()

        origin_join_index = origin_fields.indexFromName(origin_field)
        base_join_index = base_layer.fields().indexFromName(base_field)
        if origin_join_index < 0 or base_join_index < 0:
            return None

        join_map = {}
        for feat in origin_layer.getFeatures():
            join_map[feat[origin_join_index]] = feat

        new_features = []
        for feat in base_layer.getFeatures():
            new_feat = QgsFeature(mem_layer.fields())
            new_feat.setGeometry(QgsGeometry(feat.geometry()))
            attrs = list(feat.attributes())
            src_feat = join_map.get(feat[base_join_index])
            for idx, safe_name in origin_indexes:
                value = src_feat[idx] if src_feat is not None else None
                attrs.append(value)
            new_feat.setAttributes(attrs)
            new_features.append(new_feat)

        if new_features:
            provider.addFeatures(new_features)
            mem_layer.updateExtents()
        return mem_layer

    def _collect_tables(self) -> List[Dict]:
        tables = []
        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not layer.isValid():
                continue
            fields = []
            pk_indexes = set(layer.primaryKeyAttributes() or [])
            pk_names = set()
            try:
                pk_names = {layer.fields()[i].name().lower() for i in pk_indexes}
            except Exception:
                pk_names = set()
            for idx, field in enumerate(layer.fields()):
                name_lower = field.name().lower()
                is_primary = idx in pk_indexes or name_lower in pk_names or name_lower == "id" or name_lower.endswith("_id")
                fields.append(
                    {
                        "name": field.name(),
                        "type": field.typeName(),
                        "is_primary": is_primary,
                        "is_foreign": False,
                    }
                )
            tables.append({"name": layer.name(), "layer_id": layer.id(), "fields": fields})

        host = self.host
        if host is not None:
            try:
                for key, df in (host.integration_datasets or {}).items():
                    tables.append(self._build_table_from_dataframe(key, df))
            except Exception:
                pass
        return tables

    def _build_table_from_dataframe(self, name: str, df: pd.DataFrame) -> Dict:
        fields = []
        for col in df.columns:
            name_lower = str(col).lower()
            dtype = str(df[col].dtype)
            if dtype.startswith("int"):
                dtype = "int"
            elif dtype.startswith("float"):
                dtype = "float"
            elif "datetime" in dtype:
                dtype = "datetime"
            fields.append(
                {
                    "name": str(col),
                    "type": dtype,
                    "is_primary": name_lower == "id" or name_lower.endswith("_id"),
                    "is_foreign": False,
                }
            )
        return {"name": str(name), "layer_id": str(name), "fields": fields}

    def _create_memory_layer_from_schema(self, table: Dict) -> Optional[QgsVectorLayer]:
        """Cria camada de memória vazia com campos do preset."""
        name = table.get("name") or "Tabela"
        fields_def = table.get("fields") or []
        layer = QgsVectorLayer("None", name, "memory")
        provider = layer.dataProvider()
        qfields = QgsFields()
        for field in fields_def:
            fname = str(field.get("name") or "campo")
            ftype = str(field.get("type") or "").lower()
            if ftype in ("int", "integer", "int64"):
                variant = QVariant.LongLong
            elif ftype in ("float", "double", "real"):
                variant = QVariant.Double
            elif ftype in ("datetime", "date"):
                variant = QVariant.DateTime
            elif ftype in ("bool", "boolean"):
                variant = QVariant.Bool
            else:
                variant = QVariant.String
            qfields.append(QgsField(fname[:254], variant))
        provider.addAttributes(qfields)
        layer.updateFields()
        try:
            QgsProject.instance().addMapLayer(layer, addToLegend=False)
        except Exception:
            pass
        return layer

    def _collect_relationships(self) -> List[Dict]:
        relationships = []
        project = QgsProject.instance()
        rel_manager = getattr(project, "relationManager", None)
        if callable(rel_manager):
            try:
                relations = rel_manager().relations().values()
            except Exception:
                relations = []
        else:
            try:
                relations = project.relations().values()
            except Exception:
                relations = []

        for rel in relations:
            if not isinstance(rel, QgsRelation):
                continue
            parent = rel.referencedLayer()
            child = rel.referencingLayer()
            if parent is None or child is None:
                continue
            try:
                pairs = rel.fieldPairs()
            except Exception:
                pairs = {}
            for child_field, parent_field in pairs.items():
                relationships.append(
                    {
                        "id": rel.id() + f":{child_field}",
                        "source_table": child.name(),
                        "source_field": child_field,
                        "target_table": parent.name(),
                        "target_field": parent_field,
                        "cardinality": "*:1",
                        "direction": "both",
                        "selected_fields_origin_to_dest": [],
                        "selected_fields_dest_to_origin": [],
                        "origin": "project",
                    }
                )
        return relationships

    # --------------------------------------------------------------- Relationships
    def _clear_relation_flags(self):
        for table in self.tables.values():
            for field in table.field_items:
                field.setHasRelations(False)

    def _create_relationship(self, data: Dict):
        source_table = self.tables.get(data.get("source_table"))
        target_table = self.tables.get(data.get("target_table"))
        if source_table is None or target_table is None:
            return

        source_field = self._find_field(source_table, data.get("source_field"))
        target_field = self._find_field(target_table, data.get("target_field"))
        if source_field is None or target_field is None:
            return

        # Heuristica de cardinalidade/direcao
        metadata = dict(data)
        rel_id = metadata.get("id") or uuid.uuid4().hex
        metadata["id"] = rel_id
        card = metadata.get("cardinality")
        if not card:
            src_layer = self._layer_for_table(metadata.get("source_table"))
            dst_layer = self._layer_for_table(metadata.get("target_table"))
            try:
                src_count = src_layer.featureCount() if src_layer else 0
                dst_count = dst_layer.featureCount() if dst_layer else 0
                if src_count <= dst_count:
                    card = "1:*"
                else:
                    card = "*:1"
            except Exception:
                card = "1:*"
            metadata["cardinality"] = card
        metadata["direction"] = self._normalize_direction(metadata.get("direction") or metadata.get("flow_direction"))
        self._ensure_field_selections(metadata, persist=False)

        item = RelationshipItem(source_field, target_field, metadata=metadata)
        item.manager = self
        item.tableA = source_table
        item.tableB = target_table
        self.scene.addItem(item)
        item.metadata["id"] = rel_id
        self.relationships[rel_id] = item
        data.update(item.metadata)
        source_field.setHasRelations(True)
        target_field.setHasRelations(True)
        item.update_path()

    def _rebuild_relationships_for_canvas(self):
        for rel_item in list(self.relationships.values()):
            try:
                self.scene.removeItem(rel_item)
            except Exception:
                pass
        self.relationships.clear()
        self._clear_relation_flags()

        for rel in self.available_relationships:
            self._create_relationship(rel)
        try:
            self.recompute_all_virtual_fields()
        except Exception:
            pass

    def _find_field(self, table_item: TableCardItem, field_name: str):
        if field_name is None:
            return None
        for item in table_item.field_items:
            if item.field_name.lower() == str(field_name).lower():
                return item
        return None

    def handle_connection(self, start_field, end_field):
        text = (
            f"Criar relacionamento entre:\n"
            f"{start_field.table_name}.{start_field.field_name} -> "
            f"{end_field.table_name}.{end_field.field_name}?"
        )
        reply = QMessageBox.question(
            self.view,
            "Criar relacionamento",
            text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        metadata = {
            "id": uuid.uuid4().hex,
            "source_table": start_field.table_name,
            "source_field": start_field.field_name,
            "target_table": end_field.table_name,
            "target_field": end_field.field_name,
            "cardinality": "1:*",
            "direction": "both",
            "origin": "custom",
        }
        self._create_relationship(metadata)
        self.available_relationships.append(dict(metadata))
        self._save_state()
        self.recompute_all_virtual_fields()

    def open_relationship_dialog(self, rel_item: RelationshipItem):
        data = rel_item.metadata or {}
        self._ensure_field_selections(data, persist=True)
        dialog = QDialog(self.view)
        dialog.setWindowTitle("Relacionamento")
        dialog.resize(900, 600)
        settings = QSettings()
        geom_key = f"{self._state_key}/relationship_dialog_geometry"
        try:
            geom = settings.value(geom_key)
            if geom:
                dialog.restoreGeometry(geom)
        except Exception:
            pass

        grid = QGridLayout(dialog)
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(8)
        grid.setContentsMargins(10, 10, 10, 10)

        source_combo = QComboBox(dialog)
        target_combo = QComboBox(dialog)
        for combo, table_name in ((source_combo, data.get("source_table")), (target_combo, data.get("target_table"))):
            combo.addItem(str(table_name or "-"))
            combo.setCurrentIndex(0)
            combo.setToolTip(str(table_name or "-"))
            combo.setEnabled(False)

        grid.addWidget(QLabel("Tabela origem:"), 0, 0)
        grid.addWidget(source_combo, 0, 1, 1, 3)
        grid.addWidget(QLabel("Tabela destino:"), 1, 0)
        grid.addWidget(target_combo, 1, 1, 1, 3)

        card_combo = QComboBox(dialog)
        card_combo.addItems(["1:*", "*:1", "1:1", "*:*"])
        current_card = str(data.get("cardinality") or "1:*")
        idx = card_combo.findText(current_card)
        card_combo.setCurrentIndex(idx if idx >= 0 else 0)

        direction_combo = QComboBox(dialog)
        direction_combo.addItem("Ambos os sentidos", "both")
        direction_combo.addItem("Origem -> Destino", "forward")
        direction_combo.addItem("Destino -> Origem", "backward")
        current_dir = str(data.get("direction") or "both")
        dir_index = max(0, direction_combo.findData(current_dir))
        direction_combo.setCurrentIndex(dir_index)

        grid.addWidget(QLabel("Cardinalidade:"), 2, 0)
        grid.addWidget(card_combo, 2, 1)
        grid.addWidget(QLabel("Direcao do filtro:"), 2, 2)
        grid.addWidget(direction_combo, 2, 3)

        filter_edit = QLineEdit(dialog)
        filter_edit.setPlaceholderText("Filtrar campos...")
        grid.addWidget(filter_edit, 3, 0, 1, 4)

        def configure_table(table_widget: QTableWidget):
            table_widget.setColumnCount(2)
            table_widget.setHorizontalHeaderLabels(["Campo", "Incluir"])
            table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            table_widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            table_widget.verticalHeader().setVisible(False)
            table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table_widget.setSelectionMode(QAbstractItemView.NoSelection)
            small_font = table_widget.font()
            small_font.setPointSize(9)
            table_widget.setFont(small_font)
            table_widget.horizontalHeader().setFont(small_font)

        forward_table = QTableWidget(dialog)
        backward_table = QTableWidget(dialog)
        configure_table(forward_table)
        configure_table(backward_table)

        forward_label = QLabel("Campos origem -> destino:", dialog)
        backward_label = QLabel("Campos destino -> origem:", dialog)
        grid.addWidget(forward_label, 4, 0, 1, 2)
        grid.addWidget(backward_label, 4, 2, 1, 2)
        grid.addWidget(forward_table, 5, 0, 1, 2)
        grid.addWidget(backward_table, 5, 2, 1, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        grid.addWidget(buttons, 6, 2, 1, 2, alignment=Qt.AlignRight)
        delete_btn = QPushButton("Excluir", dialog)
        delete_btn.setStyleSheet("color: #B00020;")
        if data.get("origin") != "custom":
            delete_btn.setToolTip("Remove apenas do canvas; nao altera camadas.")
        grid.addWidget(delete_btn, 6, 0, 1, 1, alignment=Qt.AlignLeft)

        def populate_table(table_widget: QTableWidget, table_name: str, exclude_field: Optional[str], selected_fields: List[str]):
            fields = [name for name in self._fields_for_table(table_name) if not exclude_field or str(name).lower() != str(exclude_field).lower()]
            selected_set = {str(n).lower() for n in selected_fields}
            table_widget.setRowCount(len(fields))
            for row, name in enumerate(fields):
                name_item = QTableWidgetItem(str(name))
                name_item.setFlags(Qt.ItemIsEnabled)
                check_item = QTableWidgetItem()
                check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                check_item.setCheckState(Qt.Checked if str(name).lower() in selected_set else Qt.Unchecked)
                table_widget.setItem(row, 0, name_item)
                table_widget.setItem(row, 1, check_item)

        populate_table(
            forward_table,
            data.get("source_table") or "",
            data.get("source_field"),
            list(data.get("selected_fields_origin_to_dest") or []),
        )
        populate_table(
            backward_table,
            data.get("target_table") or "",
            data.get("target_field"),
            list(data.get("selected_fields_dest_to_origin") or []),
        )

        def apply_filter(text: str):
            term = str(text or "").lower()
            for table_widget in (forward_table, backward_table):
                for row in range(table_widget.rowCount()):
                    name_item = table_widget.item(row, 0)
                    hide = term not in str(name_item.text()).lower()
                    table_widget.setRowHidden(row, hide)

        filter_edit.textChanged.connect(apply_filter)

        def update_visibility():
            mode = direction_combo.currentData()
            forward_visible = mode in ("forward", "both")
            backward_visible = mode in ("backward", "both")
            forward_table.setVisible(forward_visible)
            backward_table.setVisible(backward_visible)
            forward_label.setVisible(forward_visible)
            backward_label.setVisible(backward_visible)

        update_visibility()
        direction_combo.currentIndexChanged.connect(update_visibility)

        def handle_delete():
            self.delete_relationship(rel_item)
            dialog.accept()

        delete_btn.clicked.connect(handle_delete)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        if not dialog.exec_():
            try:
                settings.setValue(geom_key, dialog.saveGeometry())
            except Exception:
                pass
            return

        data["cardinality"] = card_combo.currentText()
        data["direction"] = direction_combo.currentData()
        data["flow_direction"] = data["direction"]

        def collect_checked(table_widget: QTableWidget, fallback: List[str]) -> List[str]:
            results: List[str] = []
            if table_widget.rowCount() == 0:
                return list(fallback)
            for row in range(table_widget.rowCount()):
                name_item = table_widget.item(row, 0)
                check_item = table_widget.item(row, 1)
                if check_item is not None and check_item.checkState() == Qt.Checked:
                    results.append(name_item.text())
            return results

        data["selected_fields_origin_to_dest"] = collect_checked(
            forward_table, list(data.get("selected_fields_origin_to_dest") or [])
        )
        data["selected_fields_dest_to_origin"] = collect_checked(
            backward_table, list(data.get("selected_fields_dest_to_origin") or [])
        )
        rel_item.metadata = data
        rel_item._update_label_text()
        rel_item.update_path()
        self._update_available_relationship_metadata(data.get("id"), data)
        self._save_state()
        self.recompute_all_virtual_fields()
        try:
            settings.setValue(geom_key, dialog.saveGeometry())
        except Exception:
            pass

    def delete_relationship(self, rel_item: RelationshipItem):
        rel_to_remove = None
        for rel_id, item in self.relationships.items():
            if item is rel_item:
                rel_to_remove = rel_id
                break

        if rel_to_remove is not None:
            self.scene.removeItem(rel_item)
            self.relationships.pop(rel_to_remove, None)
            self.available_relationships = [
                rel for rel in self.available_relationships if rel.get("id") != rel_to_remove
            ]
            self._rebuild_relationships_for_canvas()
            self._save_state()

    # ---------------------------------------------------------------------- Layout
    def _update_all_relationship_paths(self):
        for rel in self.relationships.values():
            rel.update_path()

    def _suggest_position_for_new_table(
        self, item: TableCardItem, existing_items: Optional[List[TableCardItem]] = None
    ) -> QPointF:
        items = existing_items if existing_items is not None else [t for t in self.tables.values() if t is not item]
        if not items:
            return QPointF(0, 0)

        rects: List[QRectF] = []
        for table in items:
            try:
                rects.append(table.sceneBoundingRect())
            except Exception:
                rects.append(QRectF(table.pos(), table.rect().size()))

        spacing_x = self._layout_spacing_x
        spacing_y = self._layout_spacing_y
        card_width = item.rect().width()
        card_height = item.rect().height()
        min_x = min(r.left() for r in rects)
        min_y = min(r.top() for r in rects)

        for col in range(len(rects) + 6):
            x = min_x + col * (card_width + spacing_x)
            y = min_y
            for row in range(len(rects) + 6):
                candidate = QRectF(x, y, card_width, card_height)
                padded = candidate.adjusted(-spacing_x / 2, -spacing_y / 2, spacing_x / 2, spacing_y / 2)
                if all(not padded.intersects(r) for r in rects):
                    return QPointF(candidate.x(), candidate.y())
                y += card_height + spacing_y

        max_right = max(r.right() for r in rects)
        return QPointF(max_right + spacing_x, min_y)

    def _build_layout_graph(self) -> Dict[str, set]:
        graph: Dict[str, set] = {name: set() for name in self.tables.keys()}
        for rel in self.relationships.values():
            src = rel.metadata.get("source_table")
            dst = rel.metadata.get("target_table")
            if src in graph and dst in graph:
                graph[src].add(dst)
                graph[dst].add(src)
        return graph

    def _component_levels(self, graph: Dict[str, set], component: List[str], root: str) -> Dict[str, int]:
        levels = {root: 0}
        queue = deque([root])
        while queue:
            node = queue.popleft()
            for neighbor in sorted(graph.get(node, [])):
                if neighbor in component and neighbor not in levels:
                    levels[neighbor] = levels[node] + 1
                    queue.append(neighbor)

        for name in component:
            if name not in levels:
                levels[name] = 0
        return levels

    def _auto_layout_positions(self) -> Dict[str, QPointF]:
        positions: Dict[str, QPointF] = {}
        graph = self._build_layout_graph()

        components: List[List[str]] = []
        unvisited = set(graph.keys())
        while unvisited:
            start = sorted(unvisited)[0]
            unvisited.remove(start)
            queue = deque([start])
            component = [start]
            while queue:
                node = queue.popleft()
                for neighbor in sorted(graph.get(node, [])):
                    if neighbor in unvisited:
                        unvisited.remove(neighbor)
                        component.append(neighbor)
                        queue.append(neighbor)
            components.append(component)

        spacing_x = self._layout_spacing_x
        spacing_y = self._layout_spacing_y
        component_offset_x = 0.0
        component_gap = 200.0

        for component in components:
            if not component:
                continue
            root = max(component, key=lambda name: len(graph.get(name, [])))
            levels = self._component_levels(graph, component, root)

            level_nodes: Dict[int, List[str]] = {}
            for name, lvl in levels.items():
                level_nodes.setdefault(lvl, []).append(name)
            for names in level_nodes.values():
                names.sort(key=lambda n: (-len(graph.get(n, [])), n))

            level_x: Dict[int, float] = {}
            current_x = component_offset_x
            for lvl in sorted(level_nodes.keys()):
                max_width = max(self.tables[name].rect().width() for name in level_nodes[lvl])
                level_x[lvl] = current_x
                current_x += max_width + spacing_x

            for lvl in sorted(level_nodes.keys()):
                y = 0.0
                for name in level_nodes[lvl]:
                    item = self.tables[name]
                    positions[name] = QPointF(level_x[lvl], y)
                    y += item.rect().height() + spacing_y

            component_width = current_x - component_offset_x
            component_offset_x += component_width + max(component_gap, spacing_x * 2)

        for name, item in self.tables.items():
            if name not in positions:
                positions[name] = QPointF(component_offset_x, 0.0)
                component_offset_x += item.rect().width() + spacing_x

        return positions

    def auto_layout_model(self, ignore_saved: bool = False, reason: str = ""):
        if not self.tables:
            return
        if not ignore_saved:
            return
        self._log(f"auto_layout_model(ignore_saved={ignore_saved}, reason={reason}) chamado")
        positions = self._auto_layout_positions()
        for name, pos in positions.items():
            item = self.tables.get(name)
            if item is not None:
                item.setPos(pos)

        self._update_all_relationship_paths()
        self._needs_initial_layout = False
        self.save_layout_state()

    def auto_layout(self, force: bool = True):
        # Mantido por compatibilidade; sempre força novo layout.
        self.auto_layout_model(ignore_saved=True, reason="auto_button")

    def handle_table_moved(self, table_item: TableCardItem):
        self.on_table_position_changed(table_item, table_item.pos())

    def on_table_position_changed(self, table_item: TableCardItem, new_pos: Optional[QPointF]):
        if table_item is None:
            return
        pos = new_pos if isinstance(new_pos, QPointF) else table_item.pos()
        if isinstance(pos, QPointF):
            try:
                table_item.setPos(pos)
            except Exception:
                pass
        for rel in self.relationships.values():
            if rel.source_field.parentItem() is table_item or rel.target_field.parentItem() is table_item:
                rel.update_path()
        self._needs_initial_layout = False
        self.save_layout_state()

    # -------------------------------------------------------------------- Persist
    def _has_any_saved_positions(self, state: Optional[Dict] = None) -> bool:
        data = state if state is not None else self._saved_state
        if not isinstance(data, dict):
            return False
        tables_state = data.get("tables", {})
        if not isinstance(tables_state, dict):
            return False
        for pos in tables_state.values():
            if isinstance(pos, dict) and "x" in pos and "y" in pos:
                return True
        return False

    def _load_state(self) -> Dict:
        settings = QSettings()
        raw = settings.value(self._state_key, "", type=str)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _save_state(self):
        tables_state = {
            name: {"x": item.pos().x(), "y": item.pos().y()} for name, item in self.tables.items()
        }
        if tables_state:
            self._needs_initial_layout = False
        custom_relationships = []
        for item in self.relationships.values():
            if item.metadata.get("origin") == "custom":
                custom_relationships.append(dict(item.metadata))

        state = {
            "tables": tables_state,
            "relationships": custom_relationships,
            "zoom": self.view.zoom_level,
            "order": list(self.tables.keys()),
            "visible_tables": list(self.tables.keys()),
            "connection_style": self._connection_style,
            "legend_visible": self._legend_visible,
        }
        try:
            QSettings().setValue(self._state_key, json.dumps(state))
        except Exception:
            pass
        self._saved_state = state

    def save_layout_state(self):
        self._save_state()

    # ------------------------------------------------------------ Presets / snapshots
    def export_preset(self) -> Dict:
        """Exporta tabelas, relacoes e layout para um payload serializavel."""
        return {
            "tables": list(self.available_tables.values()),
            "relationships": list(self.available_relationships),
            "layout_state": self._saved_state if isinstance(self._saved_state, dict) else {},
        }

    def import_preset(self, payload: Dict, create_empty_layers: bool = True):
        """Importa preset JSON, recriando tabelas vazias, relacoes e layout."""
        if not isinstance(payload, dict):
            return
        tables_data = payload.get("tables") or []
        relationships = payload.get("relationships") or []
        layout_state = payload.get("layout_state") or {}
        if create_empty_layers:
            for table in tables_data:
                name = table.get("name")
                # evita duplicar se já existir camada com mesmo nome
                exists = any(
                    isinstance(layer, QgsVectorLayer) and layer.name() == name
                    for layer in QgsProject.instance().mapLayers().values()
                )
                if not exists:
                    try:
                        self._create_memory_layer_from_schema(table)
                    except Exception:
                        pass

        # Reconstruir colecoes internas
        self.scene.clear()
        self.tables.clear()
        self.relationships.clear()
        self.available_tables.clear()
        self.available_relationships.clear()
        self.available_tables = {table["name"]: table for table in self._collect_tables()}

        # Layout/estilo
        state_copy = dict(layout_state) if isinstance(layout_state, dict) else {}
        state_copy["relationships"] = relationships
        self._saved_state = state_copy
        self.available_relationships = list(relationships)

        visible = state_copy.get("visible_tables", [])
        if not isinstance(visible, list) or not visible:
            visible = list(self.available_tables.keys())
        self.restore_layout_state(visible_tables=visible)
        self._rebuild_relationships_for_canvas()
        try:
            self.recompute_all_virtual_fields()
        except Exception:
            pass
        self._save_state()

    def _on_zoom_changed(self, value: float):
        self._save_state()
