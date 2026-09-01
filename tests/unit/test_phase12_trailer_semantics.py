from __future__ import annotations

import unittest
from dataclasses import replace

from stepnx.authoring.trailer import SetTrailerString, project_trailer_strings
from stepnx.authoring.trailer_registry import TrailerEvidence, trailer_field_definition
from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.scalars import RawU32
from tests.fixture_factory import make_normal_nx20


class TrailerRelocationPolicyTests(unittest.TestCase):
    def test_unknown_scalar_that_looks_like_pointer_does_not_block_relocation(self) -> None:
        document = parse_bytes(make_normal_nx20(), profile="fiesta2")
        entries = list(document.header_metadata)
        # Use an aligned synthetic trailer pool so this test exercises only the
        # typed-pointer policy rather than the independent alignment guard.
        entries[-1] = replace(
            entries[-1],
            meta_id=RawU32.from_value((1 << 16) | 1103),
            value=RawU32.from_value(0),
            span=None,
        )
        entries[0] = replace(entries[0], value=RawU32.from_value(12), span=None)
        payload = b"condition\x00\x00\x00localized text\x00"
        marker = RawU32.from_value(len(payload) + 4).raw
        document = replace(
            document,
            header_metadata=tuple(entries),
            envelope=replace(document.envelope, raw=payload + marker, span=None),
        )

        target = project_trailer_strings(document).strings[0]
        self.assertEqual(target.text, "condition")
        edited = SetTrailerString(target.metadata_stable_id, "condition expanded").apply(document)

        unknown = next(entry for entry in edited.header_metadata if entry.stable_id == entries[0].stable_id)
        self.assertEqual(unknown.value.value, 12)
        self.assertEqual(project_trailer_strings(edited).strings[0].text, "condition expanded")

    def test_fiesta2_and_prime2_do_not_share_unproven_1100_label(self) -> None:
        fiesta = trailer_field_definition("fiesta2", 1100)
        prime = trailer_field_definition("prime2", 1100)
        self.assertEqual(fiesta.label, "Mission name")
        self.assertEqual(fiesta.evidence, TrailerEvidence.OFFICIAL_CORPUS)
        self.assertEqual(prime.label, "Localized mission/objective text")
        self.assertNotEqual(fiesta.label, prime.label)

    def test_failure_predicate_labels_keep_inference_confidence(self) -> None:
        for field_id in (1199, 1299, 1399):
            definition = trailer_field_definition("fiesta2", field_id)
            self.assertEqual(definition.evidence, TrailerEvidence.STRONGLY_INFERRED)


if __name__ == "__main__":
    unittest.main()
