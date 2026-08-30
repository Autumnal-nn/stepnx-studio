from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from math import floor


LEGACY_LOGICAL_WIDTH = 640.0
LEGACY_LANE_PITCH = 50.0
LEGACY_PATH_UNIT = 60.0
LEGACY_NOTE_QUAD = 64.0

# Prime/NXA judge-line centres recovered from the native renderer.  Single and
# Versus share the side-bank centres; the distinction is whether one bank or
# two independent player banks are presented.  Double brings both banks toward
# the centre while Centered collapses them onto the common centre line.
LEGACY_SINGLE_P1_CENTER = 160.0
LEGACY_SINGLE_P2_CENTER = 480.0
LEGACY_DOUBLE_P1_CENTER = 194.0
LEGACY_DOUBLE_P2_CENTER = 446.0
LEGACY_CENTERED_CENTER = 320.0


class PlayfieldStyle(IntEnum):
    SINGLE = 0
    DOUBLE = 1
    VERSUS = 2
    CENTERED = 3


def default_playfield_style(columns: int) -> PlayfieldStyle:
    """Return StepNX's launch default when Division 200 is absent.

    The preview deliberately keeps the editor-friendly defaults: ordinary
    five-column charts are centered, while Half-Double and Double use the
    native Double presentation. Division Metadata 200 may override this per
    active block without changing authored lanes or judgment semantics.
    """

    return PlayfieldStyle.CENTERED if int(columns) <= 5 else PlayfieldStyle.DOUBLE


@dataclass(frozen=True, slots=True)
class PlayfieldGeometry:
    """Project Prime/NXA's logical playfield into a StepNX viewport.

    The historical renderer does not derive every measure from one cell size.
    At native SD geometry lane pitch is 50, legacy path distance uses 60-unit
    coordinates, and note/item quads are 64x64.  Wider StepNX windows keep those
    logical dimensions and merely center the 640-wide playfield; narrower
    windows scale the complete logical system uniformly so it remains usable.

    ``start_column`` is the NX absolute-lane origin. It matters for Half-Double
    (2..7), P2 Single (5..9), and any style override that collapses or separates
    the two native five-lane banks.
    """

    viewport_width: float
    columns: int
    render_style: PlayfieldStyle | None = None
    start_column: int = 0

    def __post_init__(self) -> None:
        if self.viewport_width <= 0:
            raise ValueError("playfield viewport width must be positive")
        if self.columns <= 0:
            raise ValueError("playfield requires at least one column")
        if self.render_style is not None:
            PlayfieldStyle(self.render_style)

    @property
    def style(self) -> PlayfieldStyle:
        return (
            default_playfield_style(self.columns)
            if self.render_style is None
            else PlayfieldStyle(self.render_style)
        )

    @property
    def logical_scale(self) -> float:
        return min(1.0, self.viewport_width / LEGACY_LOGICAL_WIDTH)

    @property
    def logical_left(self) -> float:
        return (self.viewport_width - LEGACY_LOGICAL_WIDTH * self.logical_scale) / 2.0

    def _logical_x(self, x: float) -> float:
        return self.logical_left + float(x) * self.logical_scale

    @property
    def lane_spacing(self) -> float:
        return LEGACY_LANE_PITCH * self.logical_scale

    @property
    def path_unit(self) -> float:
        """Rendered size of one native 60-unit legacy path measure."""

        return LEGACY_PATH_UNIT * self.logical_scale

    @property
    def note_size(self) -> float:
        """Rendered size of Prime/NXA's native 64x64 note/item quad."""

        return LEGACY_NOTE_QUAD * self.logical_scale

    @property
    def _selected_single_bank(self) -> int:
        return 1 if self.start_column >= 5 else 0

    def _bank_center_logical(self, bank: int) -> float:
        bank = 1 if int(bank) else 0
        style = self.style
        if style is PlayfieldStyle.CENTERED:
            return LEGACY_CENTERED_CENTER
        if style is PlayfieldStyle.SINGLE:
            return (
                LEGACY_SINGLE_P2_CENTER
                if self._selected_single_bank
                else LEGACY_SINGLE_P1_CENTER
            )
        if style is PlayfieldStyle.DOUBLE:
            return LEGACY_DOUBLE_P2_CENTER if bank else LEGACY_DOUBLE_P1_CENTER
        return LEGACY_SINGLE_P2_CENTER if bank else LEGACY_SINGLE_P1_CENTER

    def _absolute_lane(self, visual_lane: int) -> int:
        return int(self.start_column) + int(visual_lane)

    def _lane_components(self, visual_lane: int) -> tuple[int, int]:
        absolute = self._absolute_lane(visual_lane)
        bank = 0 if absolute < 5 else 1
        local_lane = absolute if bank == 0 else absolute - 5
        return bank, local_lane

    def lane_center(self, visual_lane: int) -> float:
        if not 0 <= int(visual_lane) < self.columns:
            raise IndexError(visual_lane)
        bank, local_lane = self._lane_components(int(visual_lane))
        centre = self._bank_center_logical(bank)
        logical_x = centre + (local_lane - 2) * LEGACY_LANE_PITCH
        return self._logical_x(logical_x)

    def lane_position(self, visual_lane_position: float) -> float:
        """Project a fractional lane coordinate through the selected layout.

        Snake Path interpolation is defined in lane-index space.  Interpolating
        between actual lane centres preserves the recovered 2-unit Double bank
        separation instead of silently reverting to a synthetic uniform field.
        """

        position = float(visual_lane_position)
        if self.columns == 1:
            return self.lane_center(0)
        if position <= 0.0:
            first = self.lane_center(0)
            second = self.lane_center(1)
            return first + position * (second - first)
        if position >= self.columns - 1:
            last = self.lane_center(self.columns - 1)
            previous = self.lane_center(self.columns - 2)
            return last + (position - (self.columns - 1)) * (last - previous)
        lower = int(floor(position))
        fraction = position - lower
        left = self.lane_center(lower)
        right = self.lane_center(lower + 1)
        return left + fraction * (right - left)

    @property
    def _visible_banks(self) -> tuple[int, ...]:
        if self.style in (PlayfieldStyle.SINGLE, PlayfieldStyle.CENTERED):
            return (self._selected_single_bank,)
        banks = []
        for lane in range(self.columns):
            bank, _ = self._lane_components(lane)
            if bank not in banks:
                banks.append(bank)
        return tuple(banks) or (self._selected_single_bank,)

    @property
    def panel_count(self) -> int:
        return len(self._visible_banks)

    @property
    def panel_width(self) -> float:
        return 5.0 * self.lane_spacing

    def panel_left(self, panel: int) -> float:
        if not 0 <= int(panel) < self.panel_count:
            raise IndexError(panel)
        bank = self._visible_banks[int(panel)]
        centre = self._logical_x(self._bank_center_logical(bank))
        return centre - self.panel_width / 2.0

    @property
    def left(self) -> float:
        centres = tuple(self.lane_center(lane) for lane in range(self.columns))
        return min(centres) - self.lane_spacing / 2.0

    @property
    def field_width(self) -> float:
        centres = tuple(self.lane_center(lane) for lane in range(self.columns))
        return max(centres) - min(centres) + self.lane_spacing
