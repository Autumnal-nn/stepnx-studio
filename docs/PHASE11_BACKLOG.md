# Phase 11 closeout record

Phase 11 is complete. This document is retained as a historical summary of the
work delivered before the 0.9.x hardening cycle; it is not an active backlog.
Current work is tracked in `ROADMAP.md` and `STATUS.md`.

## Delivered during Phase 11

- interactive note toggles were moved onto sparse/indexed paths so ordinary
  edits do not rebuild full route/diagnostic state synchronously;
- StepEdit-style Split boundary drag resizes the upper Split and shifts the
  immediately lower Split's Block Start Times by the corresponding time delta;
- Division metadata editing became directly discoverable from the Edit menu;
- toolbar layout was stabilized into two rows;
- public engine-family labels were consolidated to NXA, Fiesta and Prime+;
- Header1008 Step Artist support was added for the modern family from R!SE
  evidence;
- workspace NX file create/duplicate/delete tools were added;
- imported NX10 sources gained explicit in-place NX20 materialization through
  guarded Save All rather than implicit overwrite;
- standard and custom field geometry editing was added;
- sparse NX20 long-note rendering behavior was aligned with NXA/Prime evidence;
- compressed/staged waveform decoding gained multiresolution stereo min/max
  summaries;
- all-Block Start Time shifting and direct Inspector timing edits were added;
- audio transport/metronome handling was made monotonic and resistant to delayed
  backend rewinds;
- local rendering/noteskin choices became persistent application preferences;
- guarded length-changing trailer relocation was exposed in the GUI;
- public NXA/Fiesta/Prime+ profile coverage was completed for supplied official
  corpora without assigning guessed semantics to unresolved fields;
- the official NX2 -> NXA importer audit closed the supplied 2,125-chart source
  domain against 2,111 same-path successors.

## Importer audit closeout

The supplied NX2 domain is frozen as supported evidence:

- 2,125 / 2,125 NX10 charts supported;
- 2,111 same-path official NXA NX20 successors inspected;
- all 110 observed nonzero source note codes backed by successor evidence;
- Division projection exact across 18,769 aligned Blocks;
- corrections captured for Half Double row addressing, NX20 noteskin-bank high
  bits, no-register long-note components, and leading zero-BPM fallback.

See `NX2_NXA_CONVERSION_ANALYSIS.md` for the evidence record.

## Deferred research, not implementation blockers

- **NXA Brain Div43..49**: direct native consumers exist, but supplied official
  NXA charts do not exercise these IDs. They remain unknown/raw.
- **Fiesta 2 Brain Split11/12**: presence and scope are established, but safe
  semantics are not. They remain raw-only.
- **Matched independent KSF ↔ NOT originals**: the current conservative importers
  are implemented; genuinely independent matched originals may refine historical
  cuts, BUNKI boundaries, STARTTIME re-anchoring or rounding later.
- **Physical Lightmap output**: actual cabinet-lamp actuation requires suitable
  hardware and is separate from editor publication support.
- **World Max `mission.txt`**: useful as condition-syntax evidence but outside the
  NX/NFO document model.

## Closeout decision

No Phase 11 implementation dependency remains. References in older documents to
Phase 11 as an active branch or pending merge gate are obsolete as of the 0.9.5
documentation truth pass.
