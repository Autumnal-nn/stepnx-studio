from __future__ import annotations

import random
import unittest

from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.commands import (
    CommandStack,
    InsertMetadata,
    MoveMetadata,
    RemoveMetadata,
    SetMetadataValue,
)
from stepnx.core.validation import validate
from tests.fixture_factory import make_normal_nx20


class CommandSequenceProperties(unittest.TestCase):
    def test_generated_metadata_sequences_survive_validation_roundtrip_undo_and_redo(self) -> None:
        randomizer = random.Random(0x535445504E58)

        for case in range(40):
            source = make_normal_nx20(sized_trailer=bool(case % 2))
            original = parse_bytes(source, row_storage="compact")
            stack = CommandStack(original)
            command_count = 0

            for _ in range(50):
                entries = stack.current.header_metadata
                action = randomizer.choice(("insert", "remove", "move", "set"))
                if not entries:
                    action = "insert"

                if action == "insert":
                    anchor = randomizer.choice((*entries, None))
                    command = InsertMetadata.from_ints(
                        stack.current.stable_id,
                        randomizer.randrange(0, 1 << 32),
                        randomizer.randrange(0, 1 << 32),
                        before_entry_id=None if anchor is None else anchor.stable_id,
                    )
                elif action == "remove":
                    command = RemoveMetadata(randomizer.choice(entries).stable_id)
                elif action == "move":
                    entry = randomizer.choice(entries)
                    anchors = [candidate for candidate in entries if candidate is not entry]
                    anchor = randomizer.choice((*anchors, None))
                    command = MoveMetadata(
                        entry.stable_id,
                        None if anchor is None else anchor.stable_id,
                    )
                else:
                    command = SetMetadataValue.from_int(
                        randomizer.choice(entries).stable_id,
                        randomizer.randrange(0, 1 << 32),
                    )

                current = stack.execute(command)
                command_count += 1
                self.assertTrue(validate(current).is_valid)
                reparsed = parse_bytes(serialize(current), row_storage="compact")
                self.assertTrue(validate(reparsed).is_valid)
                self.assertEqual(serialize(reparsed), serialize(current))

            final_bytes = serialize(stack.current)
            for _ in range(command_count):
                stack.undo()
            self.assertEqual(serialize(stack.current), source)
            for _ in range(command_count):
                stack.redo()
            self.assertEqual(serialize(stack.current), final_bytes)


if __name__ == "__main__":
    unittest.main()
