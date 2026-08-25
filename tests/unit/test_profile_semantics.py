from __future__ import annotations

import unittest
from dataclasses import replace

from stepnx.authoring.semantics import (
    project_brain_shower,
    project_routes,
    semantic_metadata,
    validate_authoring,
)
from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.commands import InsertMetadata
from stepnx.core.model import NoteCell, NoteRow
from stepnx.core.profiles import (
    MetadataScope,
    ValueKind,
    authorable_metadata,
    metadata_definition,
    pack_dm120,
    pack_u16_range,
    profile_capabilities,
    unpack_dm120,
    unpack_u16_range,
)
from tests.fixture_factory import make_implicit_lightmap, make_normal_nx20


class ProfileRegistryTests(unittest.TestCase):
    def test_same_id_resolves_by_scope(self) -> None:
        header = metadata_definition("nxa-native", MetadataScope.HEADER, 0)
        division = metadata_definition("nxa-native", MetadataScope.DIVISION, 0)
        self.assertEqual(header.label, "Speed")
        self.assertEqual(header.kind, ValueKind.FLOAT32_BITS)
        self.assertEqual(division.label, "Perfect count")
        self.assertEqual(division.kind, ValueKind.PACKED_U16_RANGE)

    def test_patched_profile_inherits_native_and_adds_only_extensions(self) -> None:
        self.assertIsNotNone(
            metadata_definition("nxa-step5-patched", MetadataScope.HEADER, 900)
        )
        self.assertEqual(
            metadata_definition("nxa-step5-patched", MetadataScope.HEADER, 65).label,
            "VJ timing-window parameter",
        )
        self.assertIsNone(metadata_definition("nxa-native", MetadataScope.HEADER, 65))
        capabilities = profile_capabilities("nxa-step5-patched")
        self.assertIn("brain-shower", capabilities)
        self.assertIn("condition-minlife", capabilities)
        self.assertEqual(
            metadata_definition("nxa-native", MetadataScope.HEADER, 900).maximum, 5
        )
        self.assertEqual(
            metadata_definition("nxa-step5-patched", MetadataScope.HEADER, 900).maximum,
            31,
        )

    def test_later_profiles_override_direct_noteskins_and_version_flags(self) -> None:
        fiesta_skin = metadata_definition("fiesta2", MetadataScope.HEADER, 900)
        self.assertEqual(fiesta_skin.kind, ValueKind.ENUM)
        self.assertIn(31, {choice.value for choice in fiesta_skin.choices})
        self.assertEqual(
            next(choice.label for choice in fiesta_skin.choices if choice.value == 254),
            "Random",
        )

        prime_skin = metadata_definition("prime2", MetadataScope.HEADER, 900)
        self.assertEqual(prime_skin.kind, ValueKind.ENUM)
        self.assertIn(32, {choice.value for choice in prime_skin.choices})
        self.assertEqual(
            next(choice.label for choice in prime_skin.choices if choice.value == 254),
            "Random",
        )

        reset = metadata_definition("fiesta2", MetadataScope.HEADER, 1004)
        self.assertEqual(reset.label, "Reset gameplay options")
        self.assertTrue(reset.authorable)
        self.assertEqual(reset.minimum, 1)
        self.assertEqual(reset.maximum, 1)
        self.assertEqual(
            metadata_definition("prime2", MetadataScope.HEADER, 1004).label,
            "Reset gameplay options",
        )

        fiesta_1005 = metadata_definition("fiesta2", MetadataScope.HEADER, 1005)
        self.assertFalse(fiesta_1005.authorable)
        self.assertIn("Unidentified", fiesta_1005.label)

        auto_velocity = metadata_definition("prime2", MetadataScope.HEADER, 1005)
        self.assertEqual(auto_velocity.label, "Auto Velocity")
        self.assertTrue(auto_velocity.authorable)
        self.assertEqual(auto_velocity.minimum, 1)
        self.assertEqual(auto_velocity.maximum, 1)

        fiesta_1006 = metadata_definition("fiesta2", MetadataScope.HEADER, 1006)
        self.assertFalse(fiesta_1006.authorable)
        self.assertIn("Unidentified", fiesta_1006.label)

        card_only = metadata_definition("prime2", MetadataScope.HEADER, 1007)
        self.assertEqual(card_only.label, "Card-only (AM.PASS)")
        self.assertTrue(card_only.authorable)
        self.assertIsNone(metadata_definition("fiesta2", MetadataScope.HEADER, 1007))

        for meta_id in (1005, 1006, 1007):
            discarded = metadata_definition(
                "prime2", MetadataScope.DIVISION, meta_id
            )
            self.assertFalse(discarded.authorable)
            self.assertIn("discarded-mission", discarded.label)

        capabilities = profile_capabilities("prime2")
        self.assertIn("direct-noteskin-index", capabilities)
        self.assertIn("auto-velocity", capabilities)
        self.assertIn("ampass-card-only", capabilities)

    def test_unknown_brain_parameters_are_visible_but_not_authorable(self) -> None:
        definition = metadata_definition("nxa-native", MetadataScope.DIVISION, 43)
        self.assertFalse(definition.authorable)
        ids = {
            item.meta_id
            for item in authorable_metadata("nxa-native", MetadataScope.DIVISION)
        }
        self.assertNotIn(43, ids)

    def test_unknown_profile_keeps_metadata_raw_instead_of_crashing_projection(
        self,
    ) -> None:
        document = replace(
            parse_bytes(make_normal_nx20()), profile="future-engine-research"
        )
        items = semantic_metadata(document)
        self.assertTrue(items)
        self.assertTrue(all(item.definition is None for item in items))
        report = validate_authoring(document)
        self.assertEqual(report.warnings[0].code, "profile.unknown")

    def test_packed_range_roundtrip_and_validation(self) -> None:
        value = pack_u16_range(2, 600)
        self.assertEqual(unpack_u16_range(value), (2, 600))
        with self.assertRaises(ValueError):
            pack_u16_range(-1, 2)

    def test_dm120_signed_packing_and_profile_scope(self) -> None:
        self.assertEqual(unpack_dm120(pack_dm120(0, -1)), (0, -1))
        self.assertEqual(unpack_dm120(pack_dm120(1, -2)), (1, -2))
        self.assertEqual(unpack_dm120(pack_dm120(1, 255)), (1, 255))
        with self.assertRaises(ValueError):
            pack_dm120(0, -2)
        with self.assertRaises(ValueError):
            pack_dm120(1, -3)
        with self.assertRaises(ValueError):
            pack_dm120(2, 1)
        self.assertIsNone(
            metadata_definition("nxa-native", MetadataScope.DIVISION, 120)
        )
        definition = metadata_definition(
            "nxa-step5-patched", MetadataScope.DIVISION, 120
        )
        self.assertEqual(definition.kind, ValueKind.PACKED_DM120)
        self.assertEqual(
            definition.display_value(pack_dm120(1, -2)),
            "1/-2 (Same judgment)",
        )
        self.assertIn(
            "division-120-judgment-weight",
            profile_capabilities("nxa-step5-patched"),
        )


class SemanticProjectionTests(unittest.TestCase):
    def test_route_projection_ignores_lightmap_documents(self) -> None:
        for row_storage in ("rich", "compact"):
            with self.subTest(row_storage=row_storage):
                document = parse_bytes(
                    make_implicit_lightmap(),
                    source="LM.NX",
                    row_storage=row_storage,
                )
                self.assertEqual(project_routes(document), ())

    def test_metadata_projection_preserves_duplicates_and_context(self) -> None:
        document = parse_bytes(make_normal_nx20())
        items = semantic_metadata(document)
        header_900 = [
            item
            for item in items
            if item.scope is MetadataScope.HEADER and item.meta_id == 900
        ]
        split_21 = [
            item
            for item in items
            if item.scope is MetadataScope.SPLIT and item.meta_id == 21
        ]
        self.assertEqual([item.value for item in header_900], [7, 9])
        self.assertEqual(
            [item.label for item in split_21], ["Unknown ID 21", "Unknown ID 21"]
        )

    def test_brain_projection_reports_fields_duplicates_and_unknowns(self) -> None:
        document = parse_bytes(make_normal_nx20())
        block = document.splits[0].blocks[0]
        owner_id = block.stable_id
        for meta_id, value in (
            (21, 7),
            (21, 8),
            (26, 5),
            (11, pack_u16_range(2, 6)),
            (43, 99),
        ):
            document = InsertMetadata.from_ints(owner_id, meta_id, value).apply(
                document
            )
        brain = project_brain_shower(document)[0]
        self.assertEqual(brain.opcode, 8)
        self.assertEqual(brain.answer_count, 5)
        self.assertEqual(brain.correct_range, (2, 6))
        self.assertEqual(brain.duplicate_ids, (21,))
        self.assertEqual(brain.unknown_ids, (43,))
        self.assertTrue(
            any(
                issue.code == "brain.duplicate-field"
                for issue in validate_authoring(document).warnings
            )
        )

    def test_route_projection_decodes_split_flags_conditions_and_triggers(self) -> None:
        document = parse_bytes(make_normal_nx20(), row_storage="rich")
        split = document.splits[0]
        block = split.blocks[0]
        first_row = block.rows[0]
        cells = list(first_row.cells)
        cells[0] = NoteCell(cells[0].stable_id, bytes((0x22, 0x03, 4, 0)), None)
        edited_row = NoteRow(first_row.stable_id, tuple(cells), None)
        condition = InsertMetadata.from_ints(
            block.stable_id, 0, pack_u16_range(10, 20)
        ).apply(document)
        conditioned_block = condition.splits[0].blocks[0]
        conditioned_block = replace(
            conditioned_block,
            rows=(edited_row, *conditioned_block.rows[1:]),
        )
        conditioned_split = replace(
            condition.splits[0],
            raw_select=condition.splits[0].raw_select.with_value(0xE3),
            blocks=(conditioned_block,),
        )
        route = project_routes(replace(condition, splits=(conditioned_split,)))[0]
        self.assertTrue(route.random_at_start)
        self.assertTrue(route.random_at_trigger)
        self.assertTrue(route.force_select)
        self.assertEqual(route.group, 3)
        self.assertEqual(route.branches[0].conditions[0].metric, "Perfect count")
        self.assertEqual(route.branches[0].conditions[0].minimum, 10)
        self.assertEqual(route.branches[0].triggers[0].division_id, 4)
        self.assertTrue(route.branches[0].triggers[0].triggers)

    def test_authoring_validation_is_profile_aware_without_rejecting_unknown_data(
        self,
    ) -> None:
        native = parse_bytes(make_normal_nx20())
        report = validate_authoring(native)
        self.assertFalse(report.is_valid)
        self.assertTrue(
            any(issue.code == "metadata.value-high" for issue in report.errors)
        )
        self.assertTrue(
            any(issue.code == "metadata.unknown" for issue in report.warnings)
        )

        patched = replace(native, profile="nxa-step5-patched")
        patched = InsertMetadata.from_ints(patched.stable_id, 65, 400).apply(patched)
        report = validate_authoring(patched)
        self.assertTrue(report.is_valid)
        gm65_path = next(
            item.path for item in semantic_metadata(patched) if item.meta_id == 65
        )
        self.assertFalse(
            any(
                issue.path == gm65_path and issue.code == "metadata.unknown"
                for issue in report.issues
            )
        )

    def test_fiesta2_and_prime2_run_full_authoring_validation(self) -> None:
        base = parse_bytes(make_normal_nx20())

        fiesta = replace(base, profile="fiesta2")
        fiesta = InsertMetadata.from_ints(fiesta.stable_id, 1005, 1).apply(fiesta)
        report = validate_authoring(fiesta)
        self.assertFalse(any(issue.code == "profile.unknown" for issue in report.issues))
        self.assertFalse(any(issue.code == "metadata.value-high" for issue in report.errors))
        fiesta_1005_path = next(
            item.path
            for item in semantic_metadata(fiesta)
            if item.scope is MetadataScope.HEADER and item.meta_id == 1005
        )
        self.assertFalse(
            any(
                issue.path == fiesta_1005_path and issue.code == "metadata.unknown"
                for issue in report.issues
            )
        )

        prime = replace(base, profile="prime2")
        prime = InsertMetadata.from_ints(prime.stable_id, 1007, 2).apply(prime)
        report = validate_authoring(prime)
        self.assertFalse(any(issue.code == "profile.unknown" for issue in report.issues))
        self.assertTrue(
            any(
                issue.code == "metadata.value-high" and "Card-only" in issue.message
                for issue in report.errors
            )
        )

    def test_patched_profile_rejects_invalid_dm120_encoding(self) -> None:
        document = replace(
            parse_bytes(make_normal_nx20()), profile="nxa-step5-patched"
        )
        block = document.splits[0].blocks[0]
        for invalid_value in (2 | (1 << 16), 0xFFFE0000):
            document = InsertMetadata.from_ints(
                block.stable_id, 120, invalid_value
            ).apply(document)
        report = validate_authoring(document)
        self.assertEqual(
            sum(
                issue.code == "metadata.dm120-invalid" for issue in report.errors
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
