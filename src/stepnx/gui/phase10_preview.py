from __future__ import annotations

from stepnx.gui.preview_widget import GameplayPreviewWidget as _BaseGameplayPreviewWidget


class Phase10GameplayPreviewWidget(_BaseGameplayPreviewWidget):
    """NXA-Patched SPECIAL.PNG rendering layered over the base preview."""

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
