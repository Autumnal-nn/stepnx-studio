from __future__ import annotations

import unittest
from dataclasses import replace

from stepnx.authoring.trailer import SetTrailerString, project_trailer_strings
from stepnx.authoring.trailer_registry import trailer_field_definition
from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.profiles import (
    MetadataScope,
    ValueKind,
    get_profile,
    metadata_definition,
    profile_capabilities,
)
from stepnx.core.scalars import RawU32
from tests.fixture_factory import make_normal_nx20, u32


class ModernProfileExtensionTests(unittest.TestCase):
    def test_three_public_profile_families_have_compact_labels(self) -> None:
        self.assertEqual(get_profile("nxa-native").label, "NXA")
        self.assertEqual(get_profile("fiesta2").label, "Fiesta")
        self.assertEqual(get_profile("prime2").label, "Prime+")

    def test_prime_trailer_registry_marks_1100_localized_and_keeps_header20(self) -> None:
        field_1100 = trailer_field_definition("prime2", 1100)
        field_1103 = trailer_field_definition("prime2", 1103)
        field_20 = trailer_field_definition("prime2", 20)
        self.assertIsNotNone(field_1100)
        self.assertIsNotNone(field_1103)
        self.assertIsNotNone(field_20)
        self.assertTrue(field_1100.localized)
        self.assertTrue(field_1103.localized)
        self.assertEqual(field_20.label, "V resource override")
        self.assertIsNone(trailer_field_definition("nxa-native", 20))

    def test_step_artist_is_modern_only_trailer_metadata(self) -> None:
        definition = metadata_definition("prime2", MetadataScope.HEADER, 1008)
        self.assertIsNotNone(definition)
        self.assertEqual(definition.label, "Step Artist (XX and beyond)")
        self.assertEqual(definition.kind, ValueKind.TRAILER_OFFSET)
        self.assertFalse(definition.authorable)
        self.assertIsNone(metadata_definition("fiesta2", MetadataScope.HEADER, 1008))
        self.assertIn("step-artist-trailer", profile_capabilities("prime2"))

    def test_step_artist_projects_and_edits_through_trailer_editor(self) -> None:
        # Relocation is intentionally supported only for the aligned string-pool
        # layout observed in the official later-engine corpus.  The generic NX20
        # fixture uses a compact synthetic trailer, so build an aligned trailer
        # explicitly for this relocation test instead of weakening the guard.
        payload = b"condition\x00\x00\x00localized text\x00"
        source = make_normal_nx20(sized_trailer=False) + payload + u32(len(payload) + 4)
        document = parse_bytes(source, profile="prime2")
        first = document.header_metadata[0]
        step_artist = replace(
            first,
            meta_id=RawU32.from_value(1008),
            value=RawU32.from_value(0),
            span=None,
        )
        # Keep this relocation fixture free of unrelated raw values that could
        # legitimately trigger the conservative ambiguous-pointer guard.
        document = replace(document, header_metadata=(step_artist,))

        field = trailer_field_definition("prime2", 1008)
        self.assertIsNotNone(field)
        self.assertEqual(field.label, "Step Artist (XX and beyond)")

        projection = project_trailer_strings(document)
        target = next(item for item in projection.strings if item.base_field_id == 1008)
        self.assertEqual(target.offset, 0)
        self.assertEqual(target.text, "condition")

        edited = SetTrailerString(target.metadata_stable_id, "Step Artist").apply(document)
        edited_target = next(
            item
            for item in project_trailer_strings(edited).strings
            if item.base_field_id == 1008
        )
        self.assertEqual(edited_target.text, "Step Artist")


if __name__ == "__main__":
    unittest.main()
