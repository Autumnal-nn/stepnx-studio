from __future__ import annotations

import sys
import unittest
from pathlib import Path


# The 0.9.4 release Windows gate ran 551 tests. The 0.9.5 selection-performance
# suite added nine dedicated tests (560 total), save/recovery added thirteen
# (573), and the initial keyboard-workflow audit added thirteen (586). Manual
# keyboard smoke testing then exposed eleven additional cross-Block/Toggle/
# Lightmap regressions (597), followed by five follower-bank/Lightmap-visual
# regressions (602) and five editor-field zoom regressions (607). Losing any
# hardening regression file must not leave a superficially green release.
MINIMUM_TEST_COUNT = 607
EXPECTED_SKIP_ID = (
    "unit.test_folder_workspace.FolderWorkspaceTests."
    "test_case_collisions_block_publication"
)
EXPECTED_SKIP_REASON = "case-insensitive filesystem"


def main() -> int:
    repository_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repository_root))
    sys.path.insert(0, str(repository_root / "src"))
    suite = unittest.defaultTestLoader.discover("tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)

    unexpected_skips = [
        (test.id(), reason)
        for test, reason in result.skipped
        if test.id() != EXPECTED_SKIP_ID or reason != EXPECTED_SKIP_REASON
    ]
    if result.testsRun < MINIMUM_TEST_COUNT:
        print(
            f"Windows gate rejected: discovered {result.testsRun} tests; "
            f"expected at least {MINIMUM_TEST_COUNT}.",
            file=sys.stderr,
        )
        return 1
    if unexpected_skips:
        print("Windows gate rejected unexpected skipped tests:", file=sys.stderr)
        for test_id, reason in unexpected_skips:
            print(f"- {test_id}: {reason}", file=sys.stderr)
        return 1
    if not result.wasSuccessful():
        return 1

    print(
        f"Windows gate accepted {result.testsRun} tests with "
        f"{len(result.skipped)} expected skip."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
