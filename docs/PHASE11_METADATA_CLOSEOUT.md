# Phase 11 metadata closeout

Date: 2026-08-26

Status: semantic registry frozen for the Phase 11 merge candidate. Unknown/raw fields listed below are deliberate preservation cases, not missing implementation.

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
- later-generation Header 1000/1001/1002 fields are not native NXA fields and are therefore not advertised by the NXA profile.

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
- Header1000 = Section; Header1001 = Difficulty; Header1002 = Co-op players. These are later-generation fields, not NXA-native fields.
- Header1004 = reset gameplay options.
- Header1005 is strongly inferred as the Fiesta-era Auto Velocity enable flag. Official values are 1, use is almost mutually exclusive with explicit Header0 speed, and the executable exposes `speed_auto_velocity`. Typed creation remains disabled because a direct Header1005 dispatcher xref was not recovered.
- Header1006 remains unidentified/raw-only.

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
- Header1005 = Auto Velocity using an **absolute final scroll-velocity target**, rather than the Fiesta-era value-1 enable-flag interpretation.
- Header1007 = Card-only / AM.PASS.
- Header1008 = **Step Artist (XX and beyond)**. This field is absent from Prime/Prime 2 because the player-visible Step Artist credit was introduced later. In the supplied R!SE dump, the executable names it `mpStepArtist`; all observed Header1008 payloads are trailer-relative offsets and resolve to NUL-terminated UTF-8 Step Artist strings. It is therefore registered in Prime+ as a typed trailer field rather than creating a R!SE-specific profile.
- mission difficulty `1101/1201/1301/1401` uses Arcade-comparable chart levels rather than Fiesta's 1..8 mission scale.
- Fiesta Division11/12 O/X conditions are not demonstrated in supplied Prime 2 Brain charts and Prime 2 mission results omit the O/X result counter. Preserve if encountered but do not offer them for Prime+ authoring.
- discarded `EF2166_D18_MINAMI` contains placeholder Split IDs 0..4 and Division IDs 1005..1007. These are raw-only discarded-mission fields and must not inherit same-number gameplay semantics.

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
- Fiesta 2 Header1006;
- Prime 2 discarded placeholder Split/Division fields.

They do not require invented labels or further reverse engineering for the current editor release. The final merge gate remains the strict Windows test gate plus manual closed-alpha smoke testing of the packaged build.
