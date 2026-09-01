# Phase 11 metadata closeout

Date: 2026-08-26

Status: semantic registry frozen for the Phase 11 merge candidate. Unknown/raw fields listed below are deliberate preservation cases, not missing implementation.

> **2026-09-01 correction:** later executable/LIST/corpus work finalized the Fiesta+ Header 1000..1008 family and supersedes the provisional Header1004/1005/1006 interpretations recorded during Phase 11. The canonical reference is `docs/NX20_HEADER_1000_1008.md`. In that reference, “all” means Fiesta and later; NXA does not use Header IDs 1000+.

## Evidence policy

StepNX Studio uses three compact public engine-family profiles while keeping stable internal keys for compatibility:

- `NXA` (`nxa-native`): NX Absolute native semantics;
- `Fiesta` (`fiesta2`): Fiesta / Fiesta EX / Fiesta 2;
- `Prime+` (`prime2`): Prime / Prime 2 / XX / Phoenix / R!SE and compatible modern successors.

The hidden `NXA-patched` profile remains an overlay for the Step5 engine patch. A separate R!SE profile is intentionally unnecessary: the supplied R!SE dump retains the modern NX20 semantics represented by Prime+, with Header1008 as the only newly observed Header field versus the previous NXA/Fiesta2/Prime2 baseline.

A same-number field may have different meaning or encoding across engine families or the NXA Step5 patch. Ordered metadata, duplicates, unknown IDs, unknown values, and the full 32-bit metadata ID remain lossless even when no typed editor is offered.

Evidence labels used by the registry:

- `runtime-confirmed`: a concrete runtime consumer/decoder is demonstrated;
- `executable`: executable behavior is demonstrated but the full semantic range is not closed;
- `official-corpus`: corpus behavior is sufficient to type the field structurally;
- `strongly-inferred`: corpus + runtime context support the meaning, but one direct discriminator is still missing;
- `unidentified`: preserve raw; do not offer typed authoring.

## NXA native

### Global/Header metadata

Native NXA semantics are based on the direct consumer audit in `NXA_METADATA_CONSUMERS_Step5v6_v6.txt`.

Important profile-specific rules:

- GM0 is a signed integer scalar; native NXA computes `value / 4.0`. It is not an IEEE-754 float field.
- GM35/Zigzag is deliberately absent from the NXA registry. No direct Global consumer was demonstrated and the official NXA corpus contains no GM35.
- GM65 uses the native simplified judgment-window decoder: `A = (750 - value) / 100.0`. This is distinct from the Fiesta-style decoder used by the patched profile.
- GM900..905 are raw external noteskin references in NXA and are not clamped to the slot number.
- The later-generation Header 1000..1008 family is not native NXA metadata and is therefore not advertised by the NXA profile.

### Division metadata

- Div0..9: native player judgment/count ranges.
- Div10: range condition over the native Cheer Level/performance state.
- Div16: direct Cheer Level/performance-state override; state starts at 3 and canonical authored values are 1..5.
- Div21..34: documented native Brain Shower fields.
- Div43..49: native Brain runtime parameters with unresolved individual semantics. Keep visible as unknown/raw and non-authorable until a concrete need justifies deeper executable work.
- Div221/222: native Snake Path fields.
- Div999: native 1-based Auto Judgment target; typed authoring rejects zero.

The following are intentionally **not** native Division semantics:

- Div11/12: Step5 patch-only O/X counters, copied from the later Fiesta 2 Brain condition family;
- Div101..109: Step5 patch-only condition ranges;
- Div110/111: Step5 patch-only Cheer2 / End Song events;
- Div200: Step5 patch-only style override copied from Fiesta 2;
- Div1001: no demonstrated native consumer or official-corpus occurrence; preserve raw only if encountered;
- Div10000..10014: historical converter artifacts; never advertise as authorable metadata.

## NXA Step5 patched profile

The patched profile inherits proven native behavior and overrides/adds only patch consumers.

### GM65

The patch deliberately replaces native GM65 decoding with the Fiesta-style decimal decoder:

```text
x = value + 5
q = x // 10
r = x % 10
A = (75 - q) / 10.0
B = (10 - r) * 0.5
```

This is the extended VJ/XJ/UJ-capable behavior and must not leak back into `nxa-native`.

### Patch-only Divisions

- 11: Brain Shower Correct/O range;
- 12: Brain Shower Wrong/Timeout/X range;
- 101: Current Combo;
- 102: Aggregate MaxCombo;
- 103: MissCombo;
- 104: Life/Gauge;
- 105: Item count;
- 106: Heart count;
- 107: Mine count;
- 108: Potion count;
- 109: Velocity count;
- 110: Cheer2 event;
- 111: End Song (`0` normal, `1` immediate, `2..255` fade frames);
- 120: judgment effect/multiplier encoding;
- 200: per-block style override (`0` preserve, `1` Versus, `2` Double, `3` Single/collapsed).

## Fiesta family

### Header differences

- Header0 is an IEEE-754 speed multiplier, unlike native NXA Header0.
- Header19 is the Random Skin selector. Runtime behavior fills unspecified GM900..905 slots with `254`/Random when active. The runtime distinguishes values 1..6; supplied Fiesta 2 and Prime 2 corpora use value 6. Per-number naming remains intentionally unspecified.
- Header20 is a trailer-relative BGA `.V` resource reference, not NXA BGA OFF/COSMOS.
- GM48 = Mirror; GM49 = Alternate Random.
- GM65 uses the Fiesta decimal judgment-window decoder.
- GM67 = Judge Hide.
- GM68 = Judge by Note. Executable/corpus evidence takes precedence over the conflicting legacy note that labeled GM68 Judge Hide.
- Header1000 = Section. Value 1 is Arcade; values above 1 are version-dependent.
- Header1001 = Difficulty. Chart levels use 1..50; Fiesta through Fiesta 2 Quest Zone floor difficulty uses the separate 1..8 mission scale.
- Header1002 = Players, the expected player count. Prime through R!SE expose Arcade values above 1 as Co-Op when Header1000 is 1; R!SE names this field `mpPlayers`.
- Header1003 = Paired Chart, the Fiesta-series Player 2 companion-chart reference. Later engines retain parser support.
- Header1004 = New Chart, the `NEW` Select Screen/catalog classification.
- Header1005 = Lock, marking content restricted to special selection paths such as Quest/Music Train.
- Header1006 = Another, the Fiesta through Fiesta 2 `Another` Select Screen classification. It is retired after Fiesta 2.

The previous Phase 11 Header1005 Auto Velocity interpretation was a scope collision. Prime 2 does contain a separate same-number gameplay/event ID 1005 in speed/timing code, but Header1005 itself is a boolean Lock/catalog flag. Same-number Header, Split, and Division IDs must never inherit semantics from one another.

### Per-floor mission parameters

For floors 1..4, IDs `x110` and `x111` form parallel families:

- `x110`: Rush/playback-rate scalar, strongly inferred from the timing consumer and official values matching the Rush family;
- `x111`: scroll-speed multiplier, runtime-confirmed.

Mission difficulty uses `1101/1201/1301/1401` with the Fiesta/Fiesta EX/Fiesta 2 1..8 scale.

### Brain O/X family

Fiesta 2 Division11 is present in official Brain missions and behaves as a packed O/correct-count condition. Division12 is the paired X/wrong/timeout condition copied by the NXA Step5 implementation; no supplied Fiesta 2 chart happens to exercise Div12 directly.

Split metadata 11/12 is a **different scope**. It occurs only in the Fiesta 2 Brain mission set and remains unidentified/raw-only. It must never be conflated with Division11/12.

### Other-player condition family

The co-op condition family is frozen as the strong inference:

```text
Division 1000+n = other player's counterpart of Division n
```

Therefore:

- 1000 other-player Perfect count;
- 1001 other-player Great count;
- 1002 other-player Good count;
- 1003 other-player Bad count;
- 1004 other-player Miss count;
- 1005 other-player Step G count;
- 1006 other-player Step W count;
- 1007 other-player Step A count;
- 1008 other-player Step B count;
- 1009 other-player Step C count.

Evidence anchors:

- Winter `EF1415_S_CO1`: Div1000 thresholds are 40 and 125; those numbers are drawn with ghost notes for P1 while P2 performs rolls. The P2 counterpart uses identical branches, consistent with the P1 chart testing the partner's accumulated Perfect count only to update the displayed target.
- Chimera `EF1447_D`: the sole Div1006 occurrence duplicates Div6 with the exact same `1..30000` range in one block while surrounding blocks contain only Div6. This supports the `+1000` other-player mapping and is likely an accidental authoring duplicate in that chart.

### Division200

Fiesta 2 uses Division200 extensively as the per-block style override. The NXA Step5 implementation is a direct port of this later behavior.

## Prime+ modern family

- Header19 retains the later Random Skin selector family.
- Header1004 retains the Fiesta+ New Chart classification.
- Header1005 = Lock. Prime 2 corpus values are boolean; this is not an absolute Auto Velocity value.
- Header1006 is a legacy Fiesta/Fiesta 2 Another flag. It is absent from the supplied Prime 2 corpus and should not be offered for Prime-era authoring.
- Header1007 = AM.PASS for the Prime through XX AM.PASS-exclusive chart classification.
- Header1008 = **Step Artist** for XX through R!SE. In the supplied R!SE dump, the executable names it `mpStepArtist`; observed Header1008 payloads are trailer-relative offsets resolving to NUL-terminated UTF-8 Step Artist strings.
- mission difficulty `1101/1201/1301/1401` uses Arcade-comparable chart levels rather than Fiesta's 1..8 mission scale.
- Fiesta Division11/12 O/X conditions are not demonstrated in supplied Prime 2 Brain charts and Prime 2 mission results omit the O/X result counter. Preserve if encountered but do not offer them for Prime+ authoring.
- discarded `EF2166_D18_MINAMI` contains placeholder Split IDs 0..4 and Division IDs 1005..1007. These are raw-only discarded-mission fields and must not inherit same-number Header semantics.

The R!SE corpus does not justify a separate profile: no new Split IDs, Division IDs, select modes, Brain values, padding semantics, Block flags, or note-cell families were observed relative to the modern baseline.

## Composite Header IDs and trailer offsets

Later-generation composite Header IDs are structurally closed:

```text
base_id = full_id & 0xFFFF
variant = full_id >> 16
value   = offset relative to trailer_start
```

Rules:

1. `full_id` is the serialized identity and is never normalized to `base_id` on save.
2. `base_id` is used only for semantic lookup.
3. a high word does not automatically mean string/trailer data; composite lookup is allowed only when the profile registers the base field as `TRAILER_OFFSET`.
4. unknown composite IDs remain raw and lossless.

Historical language-slot labels used by the editor are:

| Variant | Label |
| ---: | --- |
| 1 | Korean |
| 2 | Spanish |
| 3 | Portuguese |
| 4 | Chinese |
| 5 | Japanese |

Variant 3 intentionally uses the historical Setup label `Portuguese`, even where a supplied localized payload is not actually Portuguese.

Observed composite bases remain profile-specific. Fiesta 2 uses composite families based on 1102/1103/1203/1303/1403; Prime 2 uses 1100/1103 in the supplied corpus.

## Phase 11 closeout decision

The semantic registry has no research blocker for merge. Remaining unknowns are explicit raw-preservation cases:

- NXA Brain Div43..49;
- Fiesta 2 Split11/12;
- Prime 2 discarded placeholder Split/Division fields.

Header1000..1008 is no longer on the unresolved list; the finalized family is documented in `docs/NX20_HEADER_1000_1008.md`.

They do not require invented labels or further reverse engineering for the current editor release. The final merge gate remains the strict Windows test gate plus manual closed-alpha smoke testing of the packaged build.
