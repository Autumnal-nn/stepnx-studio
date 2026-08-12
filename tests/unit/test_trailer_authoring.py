from __future__ import annotations

import unittest
from dataclasses import replace

from stepnx.authoring.trailer import (
    SetTrailerStringSameSize,
    project_trailer_strings,
)
from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.errors import ModelInvariantError
from stepnx.core.scalars import RawU32
from tests.fixture_factory import make_normal_nx20


class TrailerAuthoringTests(unittest.TestCase):
    def test_known_composite_offset_projects_utf8_without_guessing_other_metadata(
        self,
    ) -> None:
        document = parse_bytes(make_normal_nx20())
        projection = project_trailer_strings(document)
        self.assertEqual(len(projection.strings), 1)
        string = projection.strings[0]
        self.assertEqual(string.base_field_id, 1103)
        self.assertEqual(string.variant_index, 1)
        self.assertEqual(string.offset, 12)
        self.assertEqual(string.text, "calized text")
        self.assertEqual(projection.diagnostics, ())

    def test_same_size_utf8_edit_preserves_offsets_marker_and_roundtrip(self) -> None:
        document = parse_bytes(make_normal_nx20())
        target = project_trailer_strings(document).strings[0]
        edited = SetTrailerStringSameSize(
            target.metadata_stable_id, "CALIZED TEXT"
        ).apply(document)
        self.assertEqual(len(edited.envelope.raw), len(document.envelope.raw))
        self.assertEqual(edited.envelope.marker_size, document.envelope.marker_size)
        self.assertEqual(
            project_trailer_strings(edited).strings[0].text, "CALIZED TEXT"
        )
        self.assertEqual(serialize(parse_bytes(serialize(edited))), serialize(edited))

    def test_length_change_and_invalid_pointer_are_blocked_or_diagnosed(self) -> None:
        document = parse_bytes(make_normal_nx20())
        target = project_trailer_strings(document).strings[0]
        with self.assertRaisesRegex(
            ModelInvariantError, "preserve encoded byte length"
        ):
            SetTrailerStringSameSize(target.metadata_stable_id, "short").apply(document)

        entry = document.header_metadata[-1]
        invalid = replace(entry, value=RawU32.from_value(0xFFFFFFFF))
        document = replace(
            document, header_metadata=(*document.header_metadata[:-1], invalid)
        )
        projection = project_trailer_strings(document)
        self.assertEqual(projection.strings, ())
        self.assertEqual(projection.diagnostics[0].code, "trailer.offset-outside")

    def test_non_utf8_target_remains_visible_but_not_authorable(self) -> None:
        document = parse_bytes(make_normal_nx20())
        payload = bytearray(document.envelope.payload)
        payload[12] = 0xFF
        document = replace(
            document,
            envelope=replace(
                document.envelope,
                raw=bytes(payload) + document.envelope.raw[-4:],
            ),
        )
        projection = project_trailer_strings(document)
        self.assertIsNone(projection.strings[0].text)
        with self.assertRaisesRegex(ModelInvariantError, "encoding is unknown"):
            SetTrailerStringSameSize(
                projection.strings[0].metadata_stable_id, "CALIZED TEXT"
            ).apply(document)


if __name__ == "__main__":
    unittest.main()
