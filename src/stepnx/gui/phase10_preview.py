from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPen

from stepnx.gui.preview_widget import GameplayPreviewWidget as _BaseGameplayPreviewWidget
from stepnx.preview.geometry import PlayfieldGeometry
from stepnx.preview.holds import pair_nx20_holds


class Phase10GameplayPreviewWidget(_BaseGameplayPreviewWidget):
    """Phase-10 rendering fixes and NXA-Patched SPECIAL.PNG support."""

    def __init__(self, *args, columns: int, start_column: int, **kwargs):
        super().__init__(
            *args,
            columns=columns,
            start_column=start_column,
            **kwargs,
        )
        # NX10/NX20 Half Double is six logical lanes with StartColumn=2.  The
        # runtime does not stretch those six lanes into their own playfield:
        # they occupy global Double lanes 2..7.  Keep commands/session local to
        # six lanes while rendering them on the normal ten-lane Double backing.
        self._half_double_backing = self.columns == 6 and self.start_column == 2
        if self._half_double_backing:
            self.field_mode = "DOUBLE"
            self._refresh_tooltip()

    @staticmethod
    def _pair_holds(events):
        # NXA and Prime 2 agree on the NX20-era rule: completely empty rows are
        # transparent to hold carry, but every globally non-empty row must
        # contain BODY/TAIL in an already-open lane or that shaft is cancelled.
        return pair_nx20_holds(events)

    def _geometry(self) -> PlayfieldGeometry:
        if getattr(self, "_half_double_backing", False):
            return PlayfieldGeometry(max(1.0, float(self.width())), 10)
        return super()._geometry()

    def lane_center(self, source_lane: int) -> float:
        if getattr(self, "_half_double_backing", False):
            visual_lane = self._visual_lane(source_lane)
            return self._geometry().lane_center(self.start_column + visual_lane)
        return super().lane_center(source_lane)

    def _draw_sequence_zone(self, painter, geometry, receptor_y: float) -> None:
        if not getattr(self, "_half_double_backing", False):
            return super()._draw_sequence_zone(painter, geometry, receptor_y)

        # With a real noteskin, the base implementation already draws two BASE
        # panels because our geometry reports ten backing lanes.
        if self.command.freedom:
            return
        pack = getattr(self, "_noteskin_pack", None)
        bank = None if pack is None else pack.bank(0)
        if bank is not None and bank.base is not None:
            return super()._draw_sequence_zone(painter, geometry, receptor_y)

        # Fallback receptors must also show a ten-lane Double field.  Only the
        # six middle lanes map to playable Half-Double source lanes.
        lane_map = self._lane_map()
        for global_lane in range(10):
            centre = geometry.lane_center(global_lane)
            rect = QRectF(
                centre - geometry.note_size / 2,
                receptor_y - geometry.note_size / 2,
                geometry.note_size,
                geometry.note_size,
            )
            local_visual = global_lane - self.start_column
            source_lane = (
                lane_map[local_visual]
                if 0 <= local_visual < len(lane_map)
                else None
            )
            painter.setPen(QPen(QColor("#b7c7e8"), 2.0))
            painter.setBrush(
                QColor("#5676a8")
                if source_lane is not None
                and source_lane in self.session.pressed_lanes
                else QColor(35, 46, 68, 210)
            )
            painter.drawRoundedRect(rect, 8, 8)

    @staticmethod
    def _phase10_special_tile(atlas, cell: int):
        if cell < 0:
            return None
        capacity = atlas.columns * atlas.rows
        if cell >= capacity:
            return None
        return cell % atlas.columns, cell // atlas.columns

    def _phase10_draw_special_cell(self, painter, atlas, cell: int, rect) -> bool:
        tile = self._phase10_special_tile(atlas, cell)
        if tile is None:
            return False
        column, row = tile
        return self._draw_atlas(painter, atlas, column, row, rect)

    def _draw_asset(self, painter, event, rect):
        pack = getattr(self, "_noteskin_pack", None)
        profile = getattr(getattr(self, "stream", None), "profile", "")
        if (
            profile == "nxa-step5-patched"
            and pack is not None
            and pack.special_items is not None
        ):
            atlas = pack.special_items
            raw = event.raw
            if (
                raw[0] == 0x01
                and raw[1] == 0x03
                and 64 <= raw[2] <= 160
                and (raw[3] & 0x3F) == 0
            ):
                return self._phase10_draw_special_cell(
                    painter, atlas, raw[2] - 64, rect
                )

            if (
                raw[0] == 0x02
                and raw[1] == 0x03
                and 100 <= raw[2] <= 199
                and (raw[3] & 0x3F) == 0x01
            ):
                number = raw[2] - 100
                tens_cell = 10 + number // 10
                units_cell = number % 10
                units = self._phase10_draw_special_cell(
                    painter, atlas, units_cell, rect
                )
                tens = self._phase10_draw_special_cell(
                    painter, atlas, tens_cell, rect
                )
                return units or tens

        return super()._draw_asset(painter, event, rect)
