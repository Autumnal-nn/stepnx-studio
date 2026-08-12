from __future__ import annotations

import unittest

from stepnx.authoring.metadata import (
    MetadataDraft,
    ReplaceMetadataCollection,
    metadata_drafts,
)
from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.commands import CommandStack
from stepnx.core.errors import ModelInvariantError
from tests.fixture_factory import make_normal_nx20


class MetadataAuthoringTests(unittest.TestCase):
    def test_collection_edit_is_atomic_ordered_and_preserves_unknown_duplicates(
        self,
    ) -> None:
        document = parse_bytes(make_normal_nx20())
        original = document.header_metadata
        drafts = (
            MetadataDraft(900, 9, original[1].stable_id),
            MetadataDraft(65, 400),
            MetadataDraft(900, 7, original[0].stable_id),
        )
        stack = CommandStack(document)
        edited = stack.execute(ReplaceMetadataCollection(document.stable_id, drafts))
        self.assertEqual(
            [
                (entry.meta_id.value, entry.value.value)
                for entry in edited.header_metadata
            ],
            [(900, 9), (65, 400), (900, 7)],
        )
        self.assertEqual(edited.header_metadata[0], original[1])
        self.assertEqual(edited.header_metadata[2], original[0])
        self.assertGreater(
            edited.header_metadata[1].stable_id,
            max(item.stable_id for item in original),
        )
        self.assertEqual(stack.undo(), document)
        self.assertEqual(stack.redo(), edited)
        self.assertEqual(serialize(parse_bytes(serialize(edited))), serialize(edited))

    def test_unchanged_drafts_keep_exact_scalar_bytes_and_spans(self) -> None:
        document = parse_bytes(make_normal_nx20())
        edited = ReplaceMetadataCollection(
            document.stable_id, metadata_drafts(document.header_metadata)
        ).apply(document)
        self.assertIs(edited.header_metadata[0], document.header_metadata[0])

    def test_foreign_or_duplicate_stable_ids_are_rejected(self) -> None:
        document = parse_bytes(make_normal_nx20())
        stable_id = document.header_metadata[0].stable_id
        with self.assertRaisesRegex(ModelInvariantError, "duplicate stable ID"):
            ReplaceMetadataCollection(
                document.stable_id,
                (MetadataDraft(1, 2, stable_id), MetadataDraft(3, 4, stable_id)),
            ).apply(document)
        with self.assertRaisesRegex(ModelInvariantError, "outside its owner"):
            ReplaceMetadataCollection(
                document.stable_id,
                (MetadataDraft(1, 2, document.splits[0].metadata[0].stable_id),),
            ).apply(document)


if __name__ == "__main__":
    unittest.main()
