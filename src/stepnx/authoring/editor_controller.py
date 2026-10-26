"""Qt-independent editor state and command adapter for an opt-in Qt frontend.

No existing GUI path is replaced. Note gestures use scoped leases; the
canonical CommandStack remains the sole owner of persisted edits.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from enum import Enum

from stepnx.authoring.selection import CellSelection, CellTarget
from stepnx.authoring.snapshot import AuthoringSnapshot, create_authoring_snapshot
from stepnx.core.commands import Command, CommandStack, NoteEdit, SetNoteAt, SetNotesAt
from stepnx.core.model import CompactRows, LightmapRow, OverlayRows


class EditorContextError(ValueError):
    """A stale event or an invalid Split/Block/row/lane target."""


class InteractionProfile(str, Enum):
    STUDIO = "studio"
    STEPEDIT_CLASSIC = "stepedit-classic"


class InteractionTool(str, Enum):
    TOGGLE = "toggle"
    ADD = "add"
    ERASE = "erase"
    SELECT = "select"
    SPECIAL = "special"


@dataclass(frozen=True, slots=True, eq=False)
class EditorEventScope:
    """Captured by hit-testing for each user event. Not an NX20 stable ID."""

    owner: object
    generation: int
    split_id: int
    block_id: int


@dataclass(frozen=True, slots=True, eq=False)
class StrokeLease:
    """Opaque identity of one pending pointer gesture."""

    scope: EditorEventScope


@dataclass(slots=True)
class PaintGesture:
    lease: StrokeLease
    raw: bytes
    targets: set[CellTarget] = field(default_factory=set)


@dataclass(slots=True)
class EditorSession:
    """Transient UI state, never serialized into the chart."""

    document_id: int
    active_blocks: dict[int, int]
    profile: InteractionProfile = InteractionProfile.STUDIO
    tool: InteractionTool = InteractionTool.TOGGLE
    hover: CellTarget | None = None
    keyboard_target: CellTarget | None = None
    selection: CellSelection = field(default_factory=CellSelection)
    scroll_y: float = 0.0
    zoom: float = 1.0
    gesture: PaintGesture | None = None


def _row_in_block(rows, row_id: int):
    """Avoid decoding the full CompactRows/OverlayRows table."""
    if isinstance(rows, (CompactRows, OverlayRows)):
        base = rows.base if isinstance(rows, OverlayRows) else rows
        index = bisect_left(base._row_ids, row_id)
        if index < len(base) and int(base._row_ids[index]) == row_id:
            return rows[index]
        return None
    for row in rows:
        if row.stable_id == row_id:
            return row
    return None


class EditorController:
    """A thin adapter for *trusted* NX20 commands and *scoped* UI events."""

    _CACHE_LIMIT = 8

    def __init__(self, stack: CommandStack) -> None:
        self._scope_owner = object()
        self._generation = 0
        self._stack = stack
        self._known_document = stack.current
        self._snapshot = create_authoring_snapshot(stack.current)
        # Strong document references prevent id() reuse; history is bounded.
        self._snapshot_cache: OrderedDict[int, tuple[object, AuthoringSnapshot]] = OrderedDict()
        self.session = EditorSession(
            document_id=stack.current.stable_id,
            active_blocks=dict(self._snapshot.active_blocks),
        )
        self._remember_snapshot()

    @property
    def document(self):
        return self._stack.current

    @property
    def snapshot(self) -> AuthoringSnapshot:
        return self._snapshot

    def _remember_snapshot(self) -> None:
        key = id(self._stack.current)
        self._snapshot_cache[key] = (self._stack.current, self._snapshot)
        self._snapshot_cache.move_to_end(key)
        if len(self._snapshot_cache) > self._CACHE_LIMIT:
            self._snapshot_cache.popitem(last=False)

    def _check_synced(self) -> None:
        if self._stack.current is not self._known_document:
            self.cancel_stroke()
            raise EditorContextError(
                "document changed outside EditorController; call sync_external_change()"
            )

    def _retain_branch_choices(self, snapshot: AuthoringSnapshot) -> AuthoringSnapshot:
        choices = self.session.active_blocks
        for split in snapshot.splits:
            chosen_id = choices.get(split.stable_id)
            if chosen_id is not None and any(
                block.stable_id == chosen_id for block in split.blocks
            ):
                snapshot = snapshot.with_active_block(split.stable_id, chosen_id)
        return snapshot

    def _commit_projection(self, snapshot: AuthoringSnapshot) -> None:
        self._snapshot = snapshot
        self._known_document = self._stack.current
        self.session.document_id = self._stack.current.stable_id
        self.session.active_blocks = dict(snapshot.active_blocks)
        self._generation += 1
        self._remember_snapshot()

    def _reproject(self) -> None:
        key = id(self._stack.current)
        cached = self._snapshot_cache.get(key)
        if cached is not None and cached[0] is self._stack.current:
            snapshot = cached[1]
            self._snapshot_cache.move_to_end(key)
        else:
            # Only structural/arbitrary edits need full validation/projection.
            snapshot = create_authoring_snapshot(self._stack.current)
        self._commit_projection(self._retain_branch_choices(snapshot))

    def _refresh_note_block(self, block_id: int) -> None:
        """Reuse existing immutable projections after a note-only command.

        SetNoteAt/SetNotesAt cannot mutate timing, metadata, diagnostics, or
        branching. The only required projection update is the touched row table.
        """
        block_rows = None
        for split in self._stack.current.splits:
            for block in split.blocks:
                if block.stable_id == block_id:
                    block_rows = block.rows
                    break
            if block_rows is not None:
                break
        if block_rows is None:
            raise EditorContextError("edited Block disappeared")
        snapshot = replace(
            self._snapshot,
            splits=tuple(
                replace(
                    split,
                    blocks=tuple(
                        replace(block, rows=block_rows)
                        if block.stable_id == block_id
                        else block
                        for block in split.blocks
                    ),
                )
                if any(block.stable_id == block_id for block in split.blocks)
                else split
                for split in self._snapshot.splits
            ),
        )
        self._commit_projection(snapshot)

    def bind_document(self, stack: CommandStack) -> None:
        """Retarget one controller and revoke all leases, even for identical IDs."""
        self._stack = stack
        self._scope_owner = object()
        self._generation += 1
        self._snapshot_cache.clear()
        self._known_document = stack.current
        self._snapshot = create_authoring_snapshot(stack.current)
        self.session = EditorSession(
            document_id=stack.current.stable_id,
            active_blocks=dict(self._snapshot.active_blocks),
            profile=self.session.profile,
            tool=self.session.tool,
        )
        self._remember_snapshot()

    def sync_external_change(self) -> None:
        self.cancel_stroke()
        # A structural replace from the old UI may reuse every internal ID.
        # Revoke old hit-test scopes even when this object is still reused.
        self._scope_owner = object()
        self._reproject()

    def select_block(self, split_id: int, block_id: int) -> None:
        self._check_synced()
        self.cancel_stroke()
        self._snapshot = self._snapshot.with_active_block(split_id, block_id)
        self.session.active_blocks = dict(self._snapshot.active_blocks)
        self._generation += 1
        self._remember_snapshot()

    def cycle_block(self, split_id: int, delta: int = 1) -> None:
        self._check_synced()
        self.cancel_stroke()
        self._snapshot = self._snapshot.cycle_block(split_id, delta)
        self.session.active_blocks = dict(self._snapshot.active_blocks)
        self._generation += 1
        self._remember_snapshot()

    def set_profile(self, profile: InteractionProfile) -> None:
        self.cancel_stroke()
        self.session.profile = InteractionProfile(profile)
        self._generation += 1

    def set_tool(self, tool: InteractionTool) -> None:
        self.cancel_stroke()
        self.session.tool = InteractionTool(tool)
        self._generation += 1

    def capture_scope(self, split_id: int, block_id: int) -> EditorEventScope:
        """Call at hit-test time, not just when a widget is first constructed."""
        self._check_synced()
        if self._snapshot.active_block_id(split_id) != block_id:
            raise EditorContextError("cannot capture a hidden Block")
        return EditorEventScope(self._scope_owner, self._generation, split_id, block_id)

    def _validate_scope(self, scope: EditorEventScope) -> None:
        self._check_synced()
        if (
            not isinstance(scope, EditorEventScope)
            or scope.owner is not self._scope_owner
            or scope.generation != self._generation
        ):
            raise EditorContextError("stale editor event or different document")
        try:
            if self._snapshot.active_block_id(scope.split_id) != scope.block_id:
                raise EditorContextError("event targets a hidden Block")
        except KeyError as exc:
            raise EditorContextError("event targets an unknown Split") from exc

    def _validate_target(self, scope: EditorEventScope, target: CellTarget) -> None:
        self._validate_scope(scope)
        try:
            block = self._snapshot.split(scope.split_id).block(scope.block_id)
        except KeyError as exc:
            raise EditorContextError("unknown Block") from exc
        if self._snapshot.effective_lightmap:
            raise EditorContextError("Lightmap requires its own editing path")
        if not 0 <= target.lane < self._snapshot.columns:
            raise EditorContextError("note lane is outside the chart")
        row = _row_in_block(block.rows, target.row_id)
        if row is None:
            raise EditorContextError("row does not belong to the selected Block")
        if isinstance(row, LightmapRow):
            raise EditorContextError("Lightmap rows cannot be edited as notes")

    def execute(self, command: Command):
        """Run an existing domain command, never a GUI-local mutation."""
        self._check_synced()
        if self.session.gesture is not None:
            raise EditorContextError("finish or cancel the gesture before editing")
        result = self._stack.execute(command)
        self._reproject()
        return result

    def set_note(self, scope: EditorEventScope, target: CellTarget, raw: bytes):
        """Place exact NX20 note bytes without guessing Hold semantics."""
        if self.session.gesture is not None:
            raise EditorContextError("cannot edit during a pending gesture")
        self._validate_target(scope, target)
        result = self._stack.execute(SetNoteAt(target.row_id, target.lane, raw))
        self._refresh_note_block(scope.block_id)
        return result

    def apply_note_batch(
        self, scope: EditorEventScope, edits: tuple[NoteEdit, ...]
    ):
        """Atomically apply a validated same-Block gesture, e.g. a Hold span."""
        self._validate_scope(scope)
        if self.session.gesture is not None:
            raise EditorContextError("finish or cancel painting before a Hold edit")
        if not edits:
            raise ValueError("note batch cannot be empty")
        if len({(e.row_id, e.lane) for e in edits}) != len(edits):
            raise ValueError("duplicate note targets in atomic gesture")
        for edit in edits:
            if len(edit.raw) != 4:
                raise ValueError("NX20 notes must be four bytes")
            self._validate_target(scope, CellTarget(edit.row_id, edit.lane))
        result = self._stack.execute(SetNotesAt(tuple(edits)))
        self._refresh_note_block(scope.block_id)
        return result

    def start_stroke(
        self, scope: EditorEventScope, first_target: CellTarget, raw: bytes
    ) -> StrokeLease:
        """Create a pending Add/Erase stroke, with no NX20 mutation."""
        if self.session.gesture is not None:
            raise EditorContextError("a gesture is already in progress")
        if len(raw) != 4:
            raise ValueError("NX20 note data must be exactly four bytes")
        self._validate_target(scope, first_target)
        lease = StrokeLease(scope)
        self.session.gesture = PaintGesture(lease, raw, {first_target})
        return lease

    def _validate_lease(self, lease: StrokeLease) -> PaintGesture:
        gesture = self.session.gesture
        if gesture is None or gesture.lease is not lease:
            raise EditorContextError("gesture was cancelled or replaced")
        self._validate_scope(lease.scope)
        return gesture

    def extend_stroke(self, lease: StrokeLease, target: CellTarget) -> None:
        gesture = self._validate_lease(lease)
        self._validate_target(lease.scope, target)
        gesture.targets.add(target)

    def finish_stroke(self, lease: StrokeLease):
        """One atomic SetNotesAt commit and undo entry."""
        gesture = self._validate_lease(lease)
        for target in gesture.targets:
            self._validate_target(lease.scope, target)
        command = SetNotesAt(
            tuple(
                NoteEdit(target.row_id, target.lane, gesture.raw)
                for target in sorted(gesture.targets)
            )
        )
        result = self._stack.execute(command)
        self.session.gesture = None
        self._refresh_note_block(lease.scope.block_id)
        return result

    def cancel_stroke(self) -> None:
        if self.session.gesture is not None:
            self.session.gesture = None
            self._generation += 1

    def undo(self):
        self.cancel_stroke()
        self._check_synced()
        result = self._stack.undo()
        self._reproject()
        return result

    def redo(self):
        self.cancel_stroke()
        self._check_synced()
        result = self._stack.redo()
        self._reproject()
        return result
