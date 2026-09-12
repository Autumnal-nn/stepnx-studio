"""Corpus-proven XSanity item aliases missing from the original SSC table.

The low-level SSC writer inherited PR #27's item alphabet, which stopped at
NX item 21 (Random Speed -> ``i``).  Exact Fiesta 2 NX <-> Sanity mission pairs
close the remaining two official item IDs:

* 21 Random Speed / VELOCITY_RANDOM -> ``i``
* 22 Nuke (older tools call it Bomb/Death) -> ``n``
* 23 Hyper Potion / MegaPotion -> ``t``

Evidence is particularly clean:

* EF1036 contains 608 NX item-21 cells and its official Sanity STEP.SSC contains
  608 ``{i04}`` cells.
* EF1219 contains 2268 item-22 and 2268 item-23 cells; the official SSC contains
  2268 ``{n08}`` and 2268 ``{t08}`` cells respectively (plus the independently
  mapped Drain stream).
* EF1329 contains 418 Potion (16) cells plus exactly one item-23 cell; its
  official SSC contains 418 ``{p04}`` plus exactly one ``{t04}``.

Keep this as an exporter semantic overlay until the low-level writer tables are
next reorganized; importing this module extends the table in place.
"""

from __future__ import annotations

import stepnx.exporters.ssc as ssc


XSANITY_LATE_ITEM_CHARS: dict[int, str] = {
    21: "i",  # Random Speed / VELOCITY_RANDOM
    22: "n",  # Nuke (Bomb/Death in older StepEdit-facing terminology)
    23: "t",  # Hyper Potion / MegaPotion
}


def install_item_semantics() -> None:
    """Install the exact late-item alphabet into the low-level SSC renderer."""

    ssc._ITEM_CHARS.update(XSANITY_LATE_ITEM_CHARS)


__all__ = ["XSANITY_LATE_ITEM_CHARS", "install_item_semantics"]
