# Selection performance regression gate

Date: 2026-09-02

StepNX Studio 0.9.4 moved ordinary selection transforms and bulk note edits back
to sparse/indexed execution. This gate makes that performance property part of
the test contract instead of relying on one workstation's elapsed time.

## Failure mode being protected

A small selection inside a large source-backed chart must not cause the editor
to materialize or iterate the complete row table. In particular, copying or
transforming roughly 40-50 notes must remain work proportional to the selected
rows/cells, not to every row in the chart.

The canonical compact model is intentionally lazy:

- `CompactRows` materializes one row only when indexed;
- `OverlayRows` stores only edited rows over a `CompactRows` base;
- selection lookup uses indexed/binary-search paths for compact row IDs;
- `SetNotesAt` groups edits by row and keeps the result sparse.

A regression that replaces any of those paths with `tuple(rows)`, `list(rows)`,
a full `for row in rows`, or an equivalent whole-chart scan is a release
blocker.

## Automated fixture

`tests/unit/test_selection_performance.py` constructs one synthetic NX20 chart
with:

- 200,000 rows;
- 10 lanes;
- compact/source-backed row storage;
- a dense source-backed note window in the middle of the chart;
- a separate empty destination region for paste tests.

The fixture is generated locally and contains no proprietary chart data.

Each covered operation runs at three selection sizes:

- 50 cells;
- 500 cells;
- 5,000 cells.

Covered operations are:

- copy;
- cut;
- paste;
- horizontal flip;
- vertical flip;
- StepEdit-compatible mirror;
- erase;
- filtered replace;
- bulk placement.

## Deterministic materialization budget

The primary regression gate is structural rather than wall-clock based.
During each operation:

1. iterating `CompactRows` is forbidden;
2. iterating `OverlayRows` is forbidden;
3. indexed `CompactRows.__getitem__` calls are counted;
4. the allowed count is a generous function of selected cells and selected
   rows, independent of the chart's 200,000-row size.

The current budget is:

```text
selected_cells + 12 * selected_rows + 64
```

This intentionally allows several indexed passes over the selected region while
remaining far below one whole-chart scan. The budget is not intended to encode
an exact implementation. A future optimization may use fewer reads without
changing the test; an implementation that genuinely needs more selected-local
passes may raise the selected-work allowance with an explicit rationale.

Do not raise the budget to a function of total chart rows.

## Wall-clock smoke test

`test_selection_authoring.py` retains the 0.9.4 interactive smoke test: a
50-note set/copy/paste transaction on a 200,000-row compact chart must complete
within one second and leave only the touched rows in an `OverlayRows` layer.

That absolute threshold is useful as a coarse alarm but is deliberately not the
main performance contract because hosted CI speed is variable. The deterministic
materialization gate is what prevents an O(selection) path from silently
becoming O(chart) again.

## Release policy

The selection-performance tests are ordinary `unittest` tests and therefore run
through the existing Windows gate and Linux/full-suite discovery. A failure is
not an optional benchmark warning. It blocks release until either:

- the sparse behavior is restored; or
- a deliberate architectural change is documented with a replacement bounded
  performance contract.
