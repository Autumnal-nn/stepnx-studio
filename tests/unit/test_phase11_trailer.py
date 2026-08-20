from __future__ import annotations

import unittest
from dataclasses import replace

from stepnx.authoring.trailer import SetTrailerString, project_trailer_strings
from stepnx.authoring.trailer_registry import (
    TrailerEvidence,
    trailer_field_definition,
)
from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.errors import ModelInvariantError
from stepnx.core.scalars import RawU32
from tests.fixture_factory import make_normal_nx20


class Phase11TrailerTests(unittest.TestCase):
    def _fiesta2_pool(self):
        document = parse_bytes(make_normal_nx20(), profile="fiesta2")
        entries = document.header_metadata
        metadata = (
            replace(entries[0], meta_id=RawU32.from_value(20), value=RawU32.from_value(0), span=None),
            replace(entries[1], meta_id=RawU32.from_value(1003), value=RawU32.from_value(8), span=None),
            replace(entries[2], meta_id=RawU32.from_value(0x00011103), value=RawU32.from_value(16), span=None),
        )
        payload = b"alpha\x00\x00\x00beta\x00\x00\x00\x00gamma\x00\x00\x00"
        marker = RawU32.from_value(len(payload) + 4).raw
        return replace(
            document,
            header_metadata=metadata,
            envelope=replace(document.envelope, raw=payload + marker, span=None),
        )

    def test_fiesta2_registry_types_runtime_confirmed_gm20_and_1003(self) -> None:
        gm20 = trailer_field_definition("fiesta2", 20)
        gm1003 = trailer_field_definition("fiesta2", 1003)
        self.assertIsNotNone(gm20)
        self.assertIsNotNone(gm1003)
        self.assertEqual(gm20.label, "V resource override")
        self.assertEqual(gm20.evidence, TrailerEvidence.RUNTIME_CONFIRMED)
        self.assertEqual(gm1003.evidence, TrailerEvidence.RUNTIME_CONFIRMED)
        self.assertIsNone(trailer_field_definition("nxa-native", 20))

    def test_profile_specific_fields_project_without_changing_nxa_gm20(self) -> None:
        document = self._fiesta2_pool()
        projection = project_trailer_strings(document)
        self.assertEqual(
            [(item.base_field_id, item.variant_index, item.offset, item.text) for item in projection.strings],
            [(20, 0, 0, "alpha"), (1003, 0, 8, "beta"), (1103, 1, 16, "gamma")],
        )

    def test_length_change_relocates_later_offsets_and_size_marker(self) -> None:
        document = self._fiesta2_pool()
        target = project_trailer_strings(document).strings[0]
        edited = SetTrailerString(target.metadata_stable_id, "alphabet").apply(document)

        projection = project_trailer_strings(edited)
        self.assertEqual([item.text for item in projection.strings], ["alphabet", "beta", "gamma"])
        self.assertEqual([item.offset for item in projection.strings], [0, 12, 20])
        self.assertEqual(
            [int(entry.value.value) for entry in edited.header_metadata],
            [0, 12, 20],
        )
        self.assertEqual(len(edited.envelope.payload), len(document.envelope.payload) + 4)
        self.assertEqual(edited.envelope.marker_size, len(edited.envelope.raw))
        self.assertEqual(serialize(parse_bytes(serialize(edited), profile="fiesta2")), serialize(edited))

    def test_alias_to_edited_string_keeps_shared_offset(self) -> None:
        document = self._fiesta2_pool()
        entries = document.header_metadata
        aliased = replace(
            document,
            header_metadata=(entries[0], replace(entries[1], value=RawU32.from_value(0), span=None), entries[2]),
        )
        target = project_trailer_strings(aliased).strings[0]
        edited = SetTrailerString(target.metadata_stable_id, "alphabet").apply(aliased)
        self.assertEqual(
            [int(entry.value.value) for entry in edited.header_metadata],
            [0, 0, 20],
        )

    def test_untyped_plausible_downstream_pointer_blocks_relocation(self) -> None:
        document = self._fiesta2_pool()
        entries = document.header_metadata
        guarded = replace(
            document,
            header_metadata=(
                entries[0],
                entries[1],
                replace(entries[2], meta_id=RawU32.from_value(7777), span=None),
            ),
        )
        target = project_trailer_strings(guarded).strings[0]
        with self.assertRaisesRegex(ModelInvariantError, "may point to trailer offset"):
            SetTrailerString(target.metadata_stable_id, "alphabet").apply(guarded)

    def test_unaligned_synthetic_string_remains_same_size_only(self) -> None:
        document = parse_bytes(make_normal_nx20(), profile="fiesta2")
        target = project_trailer_strings(document).strings[0]
        with self.assertRaisesRegex(ModelInvariantError, "four-byte-aligned"):
            SetTrailerString(target.metadata_stable_id, "a much longer value").apply(document)


if __name__ == "__main__":
    unittest.main()
