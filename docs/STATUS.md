# Implementation status

Date: 2026-09-02

Version: 0.9.5 pre-alpha

## Current state

StepNX Studio is in a polish and hardening cycle. The canonical NX20/NFO model,
practical authoring workflow, legacy import layer, folder publication workflow,
and native gameplay preview are implemented. The documentation truth pass,
selection-performance regression gate, and save/recovery durability torture pass
are complete.

The keyboard workflow audit has passed its automated 597-test Windows/Linux gate.
Manual Windows smoke testing found and drove fixes for repeated Shift selection,
cross-Block selection semantics, Enter/Toggle dispatch, redundant chart-tab
shortcuts, and previously missing `LM.NX` cell authoring. Item 4 is therefore
**awaiting manual re-smoke**, not yet closed. High-DPI/scaling validation and
editor UX cleanup follow after that manual gate.

## Delivered

### Lossless NX20/NFO core

- one bounded NX20 parser/writer shared by NX and NFO;
- raw scalar/source-span preservation, including untouched float payload bits;
- ordered metadata with duplicates and stable IDs;
- compact/lazy source-backed rows with sparse editable overlays;
- immutable command stack, undo/redo, structural validation and structural diff;
- atomic single-file and staged multi-file saves with stale-target detection;
- exact preservation of NXA, Fiesta-family and Prime-family NX20 envelopes;
- byte-exact no-edit gate over the supplied NX20/NFO corpus.

### Legacy import

- isolated one-way NX10 importer with structured diagnostics;
- complete supplied NX2 source-domain audit over 2,125 NX10 charts;
- 2,111 same-path official NXA NX20 successors used as semantic conversion
  evidence;
- all 110 observed nonzero NX10 note codes backed by official successor
  evidence;
- exact Division projection across 18,769 aligned successor Blocks;
- corpus-backed Half Double addressing, noteskin-bank bits, no-register long
  handling, and BPM-zero conversion behavior;
- one-way STF/ST2, NOT/NOT5, STX, SEE, KSF and UCS authoring import.

### Folder/workspace and recovery

- immediate-folder workspace discovery with isolated per-file failures;
- individual Save and guarded `Save All` planning;
- exact-case valid `LM.NX` publication gate and explicit blank Lightmap creation;
- NX file create/duplicate/delete tools with Lightmap and unsaved-state guards;
- NX/NFO mirror comparison/export without automatic synchronization;
- versioned recovery snapshots outside chart folders with SHA-256 verification;
- explicit NX10 materialization rather than implicit source overwrite;
- sibling/in-folder audio discovery with manual fallback.

### Authoring UI

- Qt timeline with stable row geometry, zoom, culling and branch projection;
- Tap, Hold, Roll, Item, Division and eraser tools;
- StepEdit-style Toggle interaction and drag painting;
- Split/Block insertion, removal, reordering and Split-boundary resize;
- typed editing of all native Block timing fields and chart-wide Start Time
  shifting;
- rectangular stable-ID selection with copy, cut, paste, erase, filtered
  replace, horizontal/vertical flip, StepEdit-compatible mirror and typed bulk
  placement;
- cross-Block/Split rectangular selection and ordinary clipboard/transform
  operations over the active visible Timeline route, with encoded-row count as
  the row axis rather than Beat Split/tick density;
- sparse bulk-note execution so selection transforms no longer materialize the
  whole chart or hang on ordinary selections;
- source-backed selection reuses compact row IDs rather than decoding complete
  Blocks merely to collect stable IDs;
- typed Split selection-byte editing with decoded mode/bank display;
- source-preserving Hidden, Invisible, Appear, Vanish, VanishLow and AppearLow
  authoring visualization;
- persistent local visual/noteskin preferences outside chart folders;
- compressed/staged waveform decoding and multiresolution stereo min/max
  rendering;
- shared monotonic audio transport and metronome voice pool.

### Lightmap authoring

`LM.NX` now has a deliberately narrow native authoring path rather than being
publication-only:

- exactly three editable lanes, aligned one-to-one with raw Lightmap bytes 0..2;
- Toggle turns the targeted light channel on/off for that encoded row;
- Select supports ordinary Ctrl/Shift multi-selection, including across visible
  Block/Split boundaries;
- selected Lightmap cells support Cut, Copy, Paste and Delete;
- Lightmap clipboard cells are one-byte values and cannot be pasted into
  playable-note documents or vice versa;
- Bank/ID, Function, Visibility, Brain Code, Source Slot and other note controls
  are ignored for Lightmap Toggle/Select;
- other placement tools remain rejected as non-chart operations;
- note transforms such as horizontal/vertical flip and StepEdit Mirror are not
  Lightmap operations;
- edits remain sparse on source-backed Lightmaps and preserve the fourth raw row
  byte verbatim.

Corpus audit for the row contract covered **2,896,556 Lightmap rows** across NXA,
Fiesta 2 and Prime 2, including the six remaining NXA NX10 Lightmaps. Bytes 0..2
are exclusively `00`/`01`; byte 3 is always `00`. That is sufficient to author
three binary light channels, but not to assign an unproven meaning to byte 3.

See `LIGHTMAP_AUTHORING.md`.

### Metadata and profile semantics

Public authoring profiles are:

- `NXA` (`nxa-native`);
- `Fiesta` (`fiesta2`), covering Fiesta / Fiesta EX / Fiesta 2;
- `Prime+` (`prime2`), covering Prime / Prime 2 / XX / Phoenix / R!SE and
  compatible modern successors.

Delivered behavior includes:

- scope-aware Header, Split and Division registries with evidence labels;
- ordered duplicate-preserving metadata editing;
- finalized Fiesta-and-later Header `1000..1008` semantics;
- localized trailer-ID resolution and guarded length-changing UTF-8 trailer
  relocation for proven offset fields;
- Brain Shower projection/editing for supported native fields;
- route projection from Split selection flags and Division conditions;
- mission-condition parsing validated against supplied official NX2/NXA
  condition material;
- unknown values remain raw and lossless rather than being normalized or
  assigned guessed semantics.

### Gameplay preview

- immutable `PreviewSnapshot` and route resolution;
- manual and internally randomized route selection;
- native Qt external gameplay preview synchronized to audio;
- Single/Half Double/Double geometry, noteskins, STEPFX and pad input;
- runtime timing projection for Start Time/BPM/Beat Split/Scroll/Smooth/Skip;
- source-backed judgment timing, score, combo, grade and normal-mode gauge
  behavior for the audited runtime path;
- historical compatibility projections for supported legacy modifiers;
- expanded F6 debug overlay with:
  - Perfect / Great / Good / Bad / Miss by bank and aggregate;
  - current/max Combo and current/max MissCombo by bank;
  - score and local grade by bank;
  - gauge and clear state;
  - Heart, Bomb, Potion, Velocity, Item and Hidden counters;
- deterministic local Random Velocity/route RNG where matching the game's hidden
  global RNG state is not a product requirement.

### Performance regression hardening

- deterministic 200,000-row compact/source-backed selection fixture;
- 50, 500 and 5,000-cell cases for copy, cut, paste, horizontal/vertical flip,
  StepEdit mirror, erase, filtered replace and bulk placement;
- full `CompactRows` and `OverlayRows` iteration is rejected during ordinary
  selection operations;
- indexed source-row reads are bounded by selected work rather than total chart
  size;
- the existing 50-note / 200,000-row one-second smoke test remains as a coarse
  wall-clock alarm;
- source-backed rectangle selection avoids whole-Block row decoding when
  collecting stable row IDs;
- pull-request CI runs both the strict Windows gate and the full Linux glibc-2.31
  suite.

See `PERFORMANCE_REGRESSION_GATE.md`.

### Save/recovery durability hardening

- save stage and original-backup paths are registered before write/copy/fsync
  operations that can fail, preventing untracked transaction debris;
- catchable Python-level interruptions after partial multi-file publication run
  rollback before the interruption propagates;
- rollback of newly created targets removes the partial publication;
- if rollback of an existing target itself fails, its `.stepnx-original` backup
  is deliberately preserved and identified in the raised `WorkspaceError`;
- recovery writes use hidden staging that is never listed as a completed
  snapshot;
- catchable recovery-write failures and interruptions remove staging before
  returning or propagating;
- completed recovery listings require finalized 32-character lowercase-hex
  snapshot directories with a manifest;
- structurally invalid NX20 recovery payloads are rejected as `RecoveryError`
  even when their manifest SHA-256 has been changed to match the corrupt bytes;
- the dedicated torture matrix adds 13 save/recovery fault-injection cases on
  top of the existing stale-target, rollback, hash, path, provenance and normal
  recovery tests.

Item-3 checkpoint:

- Linux/glibc 2.31: 573 tests in 5.064 s, OK;
- Windows: 573 tests in 6.645 s, OK with the one expected case-collision skip.

See `SAVE_RECOVERY_TORTURE.md`.

### Keyboard workflow hardening

Implemented on `hardening-0.9.5-keyboard-workflow`:

- stable-ID Timeline cursor navigation with arrows, Home/End and Block/Split
  boundary jumps;
- repeated Shift-arrow selection tracks a moving edge while retaining the fixed
  original anchor;
- rectangular selection may cross visible Block/Split boundaries and counts
  encoded rows independent of Beat Split/tick density;
- Timeline-only note editing shortcuts, so `X`, `Y`, `M`, Delete, Escape and
  Ctrl+C/X/V no longer leak into unrelated editor controls;
- Timeline-only Space playback, replacing the previous application-wide
  shortcut;
- direct `1..0` tool selection and N/H/G note-function selection;
- keyboard focus access to Tool, Bank/ID, Function and Visibility controls;
- `Alt+1..5` focus navigation for Workspace, Timeline, Inspector, Diagnostics
  and Routes;
- native Qt `Ctrl+Tab` / `Ctrl+Shift+Tab` chart-tab behavior retained, with no
  StepNX `Ctrl+PageUp/PageDown` override;
- true Enter/Toggle dispatch for single and multiple selected cells;
- Enter activation for Workspace and Routes trees;
- tree-scoped keyboard access to metadata, Block timing, Split selector,
  insert/remove and reorder operations;
- standard `Ctrl+S` Save All while retaining `Ctrl+Shift+S`;
- `F1` Help > Keyboard shortcuts map;
- Lightmap Toggle/Select keyboard and clipboard workflow;
- 24 dedicated keyboard/selection/Lightmap regressions over the 573-test
  item-3 checkpoint.

Automated corrected-code checkpoint:

- Linux/glibc 2.31: **597 tests in 4.950 s, OK**;
- Windows: **597 tests in 7.161 s, OK**, with the one expected
  case-insensitive-filesystem skip.

The strict Windows discovery floor is therefore **597**. Item 4 remains open only
for manual Windows re-smoke of the corrected behaviors; a green offscreen suite
is not treated as a substitute for real focus/input ergonomics.

See `KEYBOARD_WORKFLOW_AUDIT.md`.

## Corpus metrics

| Corpus metric | Value |
| --- | ---: |
| Exact NX20/NFO | 12,909 / 12,909 |
| Classified NXA NX10 | 12 |
| Clean NX10 imports from NXA | 12 / 12 |
| Supplied NX2 NX10 source domain | 2,125 / 2,125 supported |
| Same-path NX2 -> NXA NX20 successors | 2,111 |
| Distinct NX2 note codes with successor evidence | 110 / 110 |
| Aligned Division Blocks with exact projection | 18,769 / 18,769 |
| Lightmap rows audited for three-channel authoring | 2,896,556 |
| NX20/NFO round-trip differences | 0 |
| Structural errors | 0 |

The largest recorded stress chart is 2,125,684 bytes with 267,264 rows. Rich
mode used 150.7 MiB and 1.48 s for parse plus rebuild; compact mode used 31.3 MiB
and 0.244 s with identical serialized bytes, stable IDs and source spans.

## 0.9.5 hardening scope

1. **Complete:** documentation truth pass;
2. **Complete:** performance regression suite for sparse bulk transforms and
   source-backed selection acquisition;
3. **Complete:** save/recovery fault-injection and interrupted-write hardening;
4. **Automated gate green, manual re-smoke pending:** keyboard workflow audit,
   cross-Block selection corrections and Lightmap authoring;
5. **Next after item 4 manual closure:** high-DPI/scaling validation at 100%,
   125%, 150%, 175%, 200%, 225%, 250%, 275% and 300%;
6. editor UX cleanup covering menus, selection, Inspector state, disabled
   actions, and error messages.

## Current implementation limitations

- structural row insertion/removal/move may still materialize the affected row
  collection; point and ordinary bulk cell edits remain sparse;
- a multi-file `Save All` is not physically atomic against hard process/machine
  termination between target renames. Catchable failures roll back, but true
  restart-time transaction reconciliation would require a persistent journal;
- cross-Block selection follows only the active projected Timeline route; hidden
  alternate branch Blocks are not implicitly selected;
- inputs outside a legacy importer's proven source domain are guarded with
  approximation/unsupported diagnostics rather than generalized from guesses;
- cross-Split Block moves are not exposed by the current structural UI;
- actual cabinet-light actuation from `LM.NX` is not runtime-validated because it
  requires suitable Pump hardware;
- Lightmap raw byte 3 remains opaque/non-authorable because no supplied official
  row uses a nonzero value;
- exact asset-driven Animator/material presentation is not claimed pixel-perfect
  where the required official game assets are unavailable.

## Open research, not implementation blockers

The following are deliberately separated from the 0.9.5 implementation scope:

- NXA Brain Division 43..49 individual semantics;
- Fiesta 2 Brain Split metadata 11/12;
- discarded Prime 2 placeholder Split/Division fields;
- exact modern ZigZag consumer path beyond the validated historical projection;
- exact Animator/asset motion for modern Throw;
- exact Unity RNG stream for Random Velocity;
- exact Animator/material fade curves for Appear/Vanish;
- producer of `CommonModifier.SpeedBoost`;
- challenge-mode `HPBar.Add` branch;
- forced-judgment Division 999 consumer;
- any Split-level modifier dispatcher if one is eventually demonstrated;
- semantic meaning, if any, of a future nonzero fourth Lightmap row byte.

These cases remain raw-preserved, compatibility-projected, or source-gated as
appropriate. They are not reasons to invent semantics in the editor.

## Product-scope notes

- `.NFO` remains in scope because it is a native NX20 chart/deployment document.
- World Max `mission.txt` remains outside the Studio document model; supplied
  mission files are evidence for condition syntax, not a requirement for a
  mission-map editor.
- `LM.NX` remains part of folder publication and now has three-channel cell
  authoring; physical cabinet output simulation remains outside the editor gate.
- independent matched legacy originals may refine importers later, but missing
  historical source pairs are not a 0.9.5 release blocker.
