from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlayfieldGeometry:
    """Project PIU's constant-pitch lane geometry into a viewport.

    Double is one continuous ten-lane playfield. Every lane centre uses the
    same pitch; treating the two five-lane source banks as independent panels
    produces Versus geometry.
    """

    viewport_width: float
    columns: int
    maximum_panel_width: float = 480.0

    def __post_init__(self) -> None:
        if self.viewport_width <= 0:
            raise ValueError("playfield viewport width must be positive")
        if self.columns <= 0:
            raise ValueError("playfield requires at least one column")

    @property
    def panel_count(self) -> int:
        return max(1, (self.columns + 4) // 5)

    @property
    def lane_spacing(self) -> float:
        return min(
            self.maximum_panel_width / 6.0,
            self.viewport_width / (self.columns + 1),
        )

    @property
    def panel_width(self) -> float:
        # BASE is one five-lane strip.  Its apparent half-cell margins place
        # the first and last receptor centres half a pitch inside the image;
        # they are not extra playfield columns.
        return self.lane_spacing * 5.0

    @property
    def field_width(self) -> float:
        return self.lane_spacing * (self.columns + 1)

    @property
    def left(self) -> float:
        return (self.viewport_width - self.field_width) / 2.0

    @property
    def note_size(self) -> float:
        return self.lane_spacing

    def panel_left(self, panel: int) -> float:
        if not 0 <= panel < self.panel_count:
            raise IndexError(panel)
        first_lane = panel * 5
        return self.lane_center(first_lane) - self.lane_spacing / 2.0

    def lane_center(self, visual_lane: int) -> float:
        if not 0 <= visual_lane < self.columns:
            raise IndexError(visual_lane)
        return self.left + (visual_lane + 1) * self.lane_spacing
