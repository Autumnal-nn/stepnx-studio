from __future__ import annotations

from dataclasses import dataclass, replace

from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import MetadataEntry, NX20Document
from stepnx.core.scalars import RawU32


@dataclass(frozen=True, slots=True)
class MetadataDraft:
    meta_id: int
    value: int
    stable_id: int | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.meta_id <= 0xFFFFFFFF:
            raise ValueError("metadata ID must fit unsigned 32-bit storage")
        if not 0 <= self.value <= 0xFFFFFFFF:
            raise ValueError("metadata value must fit unsigned 32-bit storage")
        if self.stable_id is not None and self.stable_id <= 0:
            raise ValueError("existing metadata stable ID must be positive")


def metadata_drafts(entries: tuple[MetadataEntry, ...]) -> tuple[MetadataDraft, ...]:
    return tuple(
        MetadataDraft(int(entry.meta_id.value), int(entry.value.value), entry.stable_id)
        for entry in entries
    )


def metadata_owner(document: NX20Document, owner_id: int) -> tuple[MetadataEntry, ...]:
    matches: list[tuple[MetadataEntry, ...]] = []
    if document.stable_id == owner_id:
        matches.append(document.header_metadata)
    for split in document.splits:
        if split.stable_id == owner_id:
            matches.append(split.metadata)
        for block in split.blocks:
            if block.stable_id == owner_id:
                matches.append(block.divisions)
    if len(matches) != 1:
        raise ModelInvariantError(
            f"expected one metadata owner with stable ID {owner_id}, found {len(matches)}"
        )
    return matches[0]


@dataclass(frozen=True, slots=True)
class ReplaceMetadataCollection:
    """Atomically replace one ordered metadata collection.

    Existing draft IDs retain identity and exact raw scalar bytes when their ID
    and value are unchanged. New drafts receive monotonically allocated IDs.
    Omitted entries are removed. Unknown IDs and duplicates remain legal.
    """

    owner_id: int
    drafts: tuple[MetadataDraft, ...]

    def apply(self, document: NX20Document) -> NX20Document:
        original = metadata_owner(document, self.owner_id)
        by_id = {entry.stable_id: entry for entry in original}
        existing_ids = [
            draft.stable_id for draft in self.drafts if draft.stable_id is not None
        ]
        if len(existing_ids) != len(set(existing_ids)):
            raise ModelInvariantError(
                "metadata replacement contains a duplicate stable ID"
            )
        foreign = set(existing_ids) - set(by_id)
        if foreign:
            raise ModelInvariantError(
                "metadata replacement references entries outside its owner: "
                + ", ".join(map(str, sorted(foreign)))
            )

        next_id = document.next_stable_id
        replacements: list[MetadataEntry] = []
        for draft in self.drafts:
            if draft.stable_id is None:
                replacements.append(
                    MetadataEntry(
                        next_id,
                        RawU32.from_value(draft.meta_id),
                        RawU32.from_value(draft.value),
                        None,
                    )
                )
                next_id += 1
                continue
            entry = by_id[draft.stable_id]
            meta_id = (
                entry.meta_id
                if int(entry.meta_id.value) == draft.meta_id
                else RawU32.from_value(draft.meta_id)
            )
            value = (
                entry.value
                if int(entry.value.value) == draft.value
                else RawU32.from_value(draft.value)
            )
            replacements.append(
                entry
                if meta_id is entry.meta_id and value is entry.value
                else replace(entry, meta_id=meta_id, value=value, span=None)
            )

        replacement_tuple = tuple(replacements)
        matches = 0
        if document.stable_id == self.owner_id:
            document = replace(document, header_metadata=replacement_tuple)
            matches += 1
        splits = []
        for split in document.splits:
            changed = False
            if split.stable_id == self.owner_id:
                split = replace(split, metadata=replacement_tuple)
                matches += 1
                changed = True
            blocks = []
            for block in split.blocks:
                if block.stable_id == self.owner_id:
                    block = replace(block, divisions=replacement_tuple)
                    matches += 1
                    changed = True
                blocks.append(block)
            splits.append(replace(split, blocks=tuple(blocks)) if changed else split)
        if matches != 1:
            raise ModelInvariantError(
                f"expected one metadata owner with stable ID {self.owner_id}, found {matches}"
            )
        return replace(document, splits=tuple(splits), next_stable_id=next_id)
