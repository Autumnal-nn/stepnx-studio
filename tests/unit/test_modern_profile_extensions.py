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
from tests.fixture_factory import make_normal_nx20


class ModernProfileExtensionTests(unittest.TestCase):
    def test_three_public_profile_families_have_compact_labels(self) -> None:
        self.assertEqual(get_profile("nxa-native").label, "NXA")
        self.assertEqual(get_profile("fiesta2").label, "Fiesta")
        self.assertEqual(get_profile("prime2").label, "Prime+")

    def test_step_artist_is_modern_only_trailer_metadata(self) -> None:
        definition = metadata_definition("prime2", MetadataScope.HEADER, 1008)
        self.assertIsNotNone(definition)
        self.assertEqual(definition.label, "Step Artist (XX and beyond)")
        self.assertEqual(definition.kind, ValueKind.TRAILER_OFFSET)
        self.assertFalse(definition.authorable)
        self.assertIsNone(metadata_definition("fiesta2", MetadataScope.HEADER, 1008))
        self.assertIn("step-artist-trailer", profile_capabilities("prime2"))

    def test_step_artist_projects_and_edits_through_trailer_editor(self) -> None:
        document = parse_bytes(make_normal_nx20(), profile="prime2")
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
