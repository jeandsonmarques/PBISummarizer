import json
import math
import os
from datetime import datetime

import pandas as pd
from qgis.PyQt.QtCore import QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QPainter, QPageSize, QPdfWriter


class ExportManager:
    def __init__(self):
        self.export_dir = os.path.join(os.path.expanduser("~"), "QGIS_PowerBI_Exports")
        os.makedirs(self.export_dir, exist_ok=True)

    def _ensure_parent_dir(self, file_path):
        directory = os.path.dirname(file_path)
        if not directory:
            directory = self.export_dir
            file_path = os.path.join(directory, file_path)
        os.makedirs(directory, exist_ok=True)
        return file_path

    def export_data(self, summary_data, file_path, file_filter):
        """Exporta dados para vários formatos."""
        if "Excel" in file_filter:
            self.export_to_excel(summary_data, file_path)
        elif "CSV" in file_filter:
            self.export_to_csv(summary_data, file_path)
        elif "JSON" in file_filter:
            self.export_to_json(summary_data, file_path)
        elif "PDF" in file_filter:
            self.export_to_pdf(summary_data, file_path)

    def export_to_excel(self, summary_data, file_path):
        """Exporta para Excel com múltiplas abas."""
        file_path = self._ensure_parent_dir(file_path)
        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            basic_stats = pd.DataFrame([summary_data.get("basic_stats", {})])
            basic_stats.to_excel(writer, sheet_name="Estatísticas_Básicas", index=False)

            grouped = summary_data.get("grouped_data") or {}
            if grouped:
                grouped_df = pd.DataFrame.from_dict(grouped, orient="index")
                grouped_df.to_excel(writer, sheet_name="Dados_Agrupados")

            percentiles = pd.DataFrame([summary_data.get("percentiles", {})])
            percentiles.to_excel(writer, sheet_name="Percentis", index=False)

    def export_to_csv(self, summary_data, file_path):
        """Exporta dados agrupados para CSV."""
        grouped = summary_data.get("grouped_data") or {}
        if not grouped:
            return

        file_path = self._ensure_parent_dir(file_path)
        df = pd.DataFrame.from_dict(grouped, orient="index")
        df.to_csv(file_path)

    def export_to_json(self, summary_data, file_path):
        """Exporta dados completos para JSON."""
        file_path = self._ensure_parent_dir(file_path)
        with open(file_path, "w", encoding="utf-8") as handle:
            json.dump(summary_data, handle, indent=2, ensure_ascii=False)

    def export_to_pdf(self, summary_data, file_path):
        """Gera relatório em PDF com estatísticas e destaques (sem Matplotlib)."""
        file_path = self._ensure_parent_dir(file_path)

        metadata = summary_data.get("metadata", {})
        stats = summary_data.get("basic_stats", {})
        percentiles = summary_data.get("percentiles", {})
        grouped = summary_data.get("grouped_data") or {}

        top_groups = []
        if grouped:
            top_groups = sorted(
                grouped.items(),
                key=lambda item: item[1].get("sum", 0),
                reverse=True,
            )[:10]

        def fmt(value, digits=2):
            if isinstance(value, (int, float)):
                if not math.isfinite(value):
                    return "-"
                return f"{value:,.{digits}f}"
            if value is None:
                return "-"
            return str(value)

        writer = QPdfWriter(file_path)
        writer.setPageSize(QPageSize(QPageSize.A4))
        writer.setResolution(300)
        painter = QPainter(writer)

        page_width = writer.width()
        page_height = writer.height()
        margin = 60
        y = margin

        def ensure_space(block_height: float):
            nonlocal y
            if y + block_height > page_height - margin:
                writer.newPage()
                y = margin

        title_font = QFont("Segoe UI", 16, QFont.Bold)
        header_font = QFont("Segoe UI", 11, QFont.DemiBold)
        text_font = QFont("Segoe UI", 10)

        painter.fillRect(QRectF(0, 0, page_width, margin + 20), QColor("#0078D4"))
        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(title_font)
        painter.drawText(
            QRectF(margin, 20, page_width - 2 * margin, 30),
            Qt.AlignLeft | Qt.AlignVCenter,
            "Relatório Power BI Summarizer",
        )
        painter.setFont(text_font)
        painter.drawText(
            QRectF(margin, 48, page_width - 2 * margin, 20),
            Qt.AlignLeft | Qt.AlignVCenter,
            f"Gerado em {metadata.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}",
        )
        y = margin + 30

        painter.setFont(header_font)
        painter.setPen(QColor("#1F2933"))
        painter.drawText(QRectF(margin, y, page_width - 2 * margin, 24), Qt.AlignLeft | Qt.AlignVCenter, "Resumo")
        y += 26
        painter.setFont(text_font)
        meta_lines = [
            ("Camada", metadata.get("layer_name", "-")),
            ("Campo", metadata.get("field_name", "-")),
            ("Total de feições", fmt(stats.get("count"), 0)),
            ("Filtro aplicado", summary_data.get("filter_description", "Nenhum")),
        ]
        for label, value in meta_lines:
            ensure_space(18)
            painter.drawText(QRectF(margin, y, 180, 18), Qt.AlignLeft | Qt.AlignVCenter, f"{label}:")
            painter.drawText(QRectF(margin + 190, y, page_width - margin * 2 - 190, 18), Qt.AlignLeft | Qt.AlignVCenter, str(value))
            y += 18

        y += 12
        painter.setFont(header_font)
        painter.drawText(QRectF(margin, y, page_width - 2 * margin, 24), Qt.AlignLeft | Qt.AlignVCenter, "Estatísticas básicas")
        y += 26
        painter.setFont(text_font)
        stats_lines = [
            ("Total", stats.get("total"), 2),
            ("Contagem", stats.get("count"), 0),
            ("Média", stats.get("average"), 2),
            ("Mediana", stats.get("median"), 2),
            ("Mínimo", stats.get("min"), 2),
            ("Máximo", stats.get("max"), 2),
            ("Desvio Padrão", stats.get("std_dev"), 2),
        ]
        for label, value, digits in stats_lines:
            ensure_space(18)
            painter.drawText(QRectF(margin, y, 180, 18), Qt.AlignLeft | Qt.AlignVCenter, f"{label}:")
            painter.drawText(QRectF(margin + 190, y, page_width - margin * 2 - 190, 18), Qt.AlignLeft | Qt.AlignVCenter, fmt(value, digits))
            y += 18

        y += 12
        painter.setFont(header_font)
        painter.drawText(QRectF(margin, y, page_width - 2 * margin, 24), Qt.AlignLeft | Qt.AlignVCenter, "Percentis")
        y += 26
        painter.setFont(text_font)
        percent_lines = [
            ("P25", percentiles.get("p25"), 2),
            ("P50", percentiles.get("p50") or stats.get("median"), 2),
            ("P75", percentiles.get("p75"), 2),
            ("P90", percentiles.get("p90"), 2),
            ("P95", percentiles.get("p95"), 2),
        ]
        for label, value, digits in percent_lines:
            ensure_space(18)
            painter.drawText(QRectF(margin, y, 180, 18), Qt.AlignLeft | Qt.AlignVCenter, f"{label}:")
            painter.drawText(QRectF(margin + 190, y, page_width - margin * 2 - 190, 18), Qt.AlignLeft | Qt.AlignVCenter, fmt(value, digits))
            y += 18

        if top_groups:
            y += 14
            painter.setFont(header_font)
            painter.drawText(QRectF(margin, y, page_width - 2 * margin, 24), Qt.AlignLeft | Qt.AlignVCenter, "Top 10 grupos (por soma)")
            y += 26
            painter.setFont(text_font)
            for idx, (group_name, group_stats) in enumerate(top_groups, start=1):
                ensure_space(18)
                clean_name = str(group_name) if group_name not in (None, "") else "Sem valor"
                painter.drawText(QRectF(margin, y, 240, 18), Qt.AlignLeft | Qt.AlignVCenter, f"{idx:02d}. {clean_name}")
                painter.drawText(QRectF(margin + 260, y, 120, 18), Qt.AlignLeft | Qt.AlignVCenter, fmt(group_stats.get("sum"), 2))
                painter.drawText(QRectF(margin + 400, y, 100, 18), Qt.AlignLeft | Qt.AlignVCenter, f"{fmt(group_stats.get('percentage'), 1)}%")
                y += 18

        painter.end()
