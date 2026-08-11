from __future__ import annotations

import random
import unittest

from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.errors import ParseError
from stepnx.core.validation import validate
from tests.fixture_factory import make_normal_nx20


class ParserFuzzProperties(unittest.TestCase):
    def test_deterministic_byte_mutations_fail_cleanly_or_reparse(self) -> None:
        randomizer = random.Random(0x4E583230)
        source = make_normal_nx20()

        for _ in range(500):
            candidate = bytearray(source)
            for _ in range(randomizer.randint(1, 5)):
                if candidate and randomizer.random() < 0.15:
                    del candidate[randomizer.randrange(len(candidate))]
                elif candidate:
                    candidate[randomizer.randrange(len(candidate))] = randomizer.randrange(256)
            try:
                document = parse_bytes(bytes(candidate), row_storage="compact")
            except ParseError:
                continue

            self.assertTrue(validate(document).is_valid)
            rebuilt = serialize(document)
            self.assertEqual(serialize(parse_bytes(rebuilt, row_storage="compact")), rebuilt)


if __name__ == "__main__":
    unittest.main()
