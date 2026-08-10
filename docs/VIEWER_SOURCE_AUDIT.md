# Viewer implementation source audit

Date: 2026-08-10

## Decision summary

The two audited projects solve different view problems and may be useful bases
for the appropriate module. Neither may replace the StepNX canonical model.

| Source | Approved role | Rejected role |
| --- | --- | --- |
| STEPEdit-pixi | layout and interaction reference, or conditional code base, for the vertical authoring viewport | canonical parser/writer, document model, or mandatory web runtime |
| WebPrime | possible code base for a separate gameplay-preview module | authoritative NX loader, editable model, or normative engine emulator |
| StepNX core | sole authority for open, preserve, mutate, validate, diff, and save | view-specific rendering logic |

“Base” means a base for one module, not the foundation of the entire
application.

## Audited material

- STEPEdit-pixi commit
  `d2fc56d519068c8bccc8b07c943647049426c0a5` (2026-05-05);
- WebPrime commit
  `2d145b7917701afa200aa244956eb2616b934fef` (2026-06-02);
- unpacked StepEdit 5.63;
- `nx_editor-v60.py`;
- StepNX Studio core `0.1.0.dev0` and its 12,909-file corpus gate.

Both JavaScript projects installed dependencies and produced production builds
in the audit environment. A successful build proves that the trees are
buildable; it does not validate timing, branch selection, or interactive
rendering behavior.

## STEPEdit-pixi

### Useful design

The viewport makes several sensible authoring choices also seen in StepEdit
5.63:

- vertical row/beat timeline;
- visible split boundaries;
- measure ruler, grid, and block data;
- active-block switching within a split;
- taps, holds, items, and Division visualization;
- contextual metadata/flag inspection.

As a layout study it is substantially more useful than the monolithic Canvas in
`nx_editor-v60.py`, which recreates broad visual state after each action.

### Components that must be replaced

The parser/model violates the Studio contract:

- metadata and Divisions are stored in `Map`, collapsing duplicate IDs;
- known fields are normalized and unknown values may become defaults;
- Lightmap is rejected;
- trailers and opaque tails are ignored;
- raw floats and source spans disappear;
- unknown note subtypes are not preserved as first-class data;
- no lossless writer or authoring command system exists.

The renderer should not be copied literally either:

- it creates objects/components for the entire chart;
- it lacks viewport culling;
- it uses fixed geometry and has no shared audio/timing transport;
- it is coupled to React and PixiJS while the desktop baseline is Qt Widgets.

The approved use is its interaction/layout design. A StepNX Qt widget will draw
only visible rows, use mathematical hit testing, and consume read-only snapshots
from the core.

### License

The audited repository has no `LICENSE`, copyright notice, or `package.json`
license field. `private: true` grants no reuse right. Licenses of dependencies
do not license the application itself.

Therefore:

- behavior may be studied and compared;
- copying, translating, or porting code requires permission from its copyright
  holders under a compatible license;
- sprites under `public/noteskin` have no demonstrated reusable license and are
  excluded.

The clean resolution is for all relevant copyright holders to publish the code
under Apache-2.0 or another compatible permissive license, with third-party
assets explicitly excluded. A private permission letter is harder for future
contributors to audit and should be avoided if a public license can be added.
Until then, the project is a behavioral and layout reference only.

## WebPrime

### Useful design

WebPrime targets gameplay preview rather than chart authoring:

- audio transport and update loop;
- beat/time projection to screen coordinates;
- BPM changes, stops, warps, and scrolling;
- Canvas/WebGL batching;
- holds, effects, noteskins, and gameplay-like presentation.

A gameplay session must choose one block per executed split. Rendering one route
is correct. The present implementation chooses too early: its parser maps
`systemselected == 0` to block zero and any other value to an immediate random
choice, then discards all alternatives.

### Required refactor

The derived module must not parse NX directly:

```text
Canonical Document
    -> PreviewSnapshot (read-only)
    -> RouteResolver(profile, policy, seed, simulated state)
    -> RuntimeEventStream
    -> WebPrime-derived renderer
```

`RouteResolver` will evolve through:

1. manual route choice;
2. deterministic random choice with a recorded seed;
3. engine-profile autoplay, initially all-perfect;
4. explicit manual fallback for unsupported gameplay-dependent conditions.

The route belongs to preview session state. Re-running the preview is how the
user inspects another branch; overlaying every branch would simulate a gameplay
execution that cannot exist.

Known WebPrime issues to cut away or correct:

- declared but unimplemented NX10 support;
- ignored split metadata;
- Division conditions parsed but not correctly attached/evaluated;
- undeclared `p1`/`p2` assignments in strict code paths;
- all non-zero `smooth_speed` values treated as one behavior;
- incomplete Lightmap, Half Double, trailer, native-NXA, and patched-engine
  semantics;
- parsing mixed with interpretation, route choice, and event generation.

These defects do not disqualify its renderer. They define the isolation seam.

### Integration options

| Option | Benefit | Cost |
| --- | --- | --- |
| Independent web renderer | faster browser-side iteration | QtWebEngine/Chromium greatly increases package size and creates a second UI stack |
| Native Qt renderer | one UI stack and cleaner desktop integration | more implementation work |

Recommended sequence: first build an independent web preview that consumes a
CLI/core snapshot. Use it to validate route and timing behavior. Only then
compare QtWebEngine against an independent native implementation before
freezing distribution.

### License

The audited WebPrime tree is copyleft-licensed under inconsistent version
notices. Those terms are not accepted by StepNX Studio's Apache-only dependency
policy. No WebPrime code may be copied, translated, linked, vendored, or shipped
with the Studio.

Informal approval from one author does not relicense other contributors' work.
Reuse can be reconsidered only after every relevant copyright holder has made a
compatible license grant. Until then, WebPrime is a behavioral oracle used to
inform an independent implementation.

### Assets

WebPrime's `datapack/LICENSE` states that its Pump It Up Prime assets belong to
Andamiro. Those JPAKs, notes, combo graphics, and sample charts are proprietary
and may not enter the Studio repository or release archive.

The preview will use either original redistributable StepNX glyphs or a visual
pack selected locally by the user. The same restriction applies to unlicensed
STEPEdit-pixi sprites. Public availability is not a copyright license.

## Frozen architectural boundary

```text
Lossless codec -> Canonical Document -> Commands / Validators
                         |                       |
                         +-> AuthoringSnapshot --+-> Qt viewport
                         |
                         +-> PreviewSnapshot -> RouteResolver -> gameplay view
```

Rules:

1. only the core opens and saves NX/NFO;
2. snapshots include stable IDs but no mutable byte references;
3. the authoring view issues commands; gameplay preview is read-only;
4. branch policy and RNG are reproducible and displayed in the preview;
5. unknown semantics produce diagnostics, never normalization;
6. no proprietary asset ships in an official build.

## Acceptance gates

Authoring viewport:

- resolve STEPEdit-pixi licensing before any code port;
- cull a Qt prototype over the 267,264-row stress chart;
- target 60 fps and require 30 fps during scroll/zoom;
- switch/compare branches without changing the document;
- preserve compact-core memory improvements.

Gameplay preview:

- export `PreviewSnapshot` from synthetic fixtures;
- execute manual and deterministic seeded routes;
- compare BPM/stop/warp/speed projection against the NXA profile;
- flag unsupported conditions;
- replay at least two routes from one chart;
- build without official JPAK/sprite assets.

## Primary sources

- [STEPEdit-pixi](https://github.com/StepMania-AMX/STEPEdit-pixi)
- [STEPEdit-pixi NX20 parser at the audited commit](https://github.com/StepMania-AMX/STEPEdit-pixi/blob/d2fc56d519068c8bccc8b07c943647049426c0a5/src/parser/nx20.js)
- [STEPEdit-pixi vertical renderer at the audited commit](https://github.com/StepMania-AMX/STEPEdit-pixi/blob/d2fc56d519068c8bccc8b07c943647049426c0a5/src/components/step.js)
- [WebPrime](https://github.com/racerxdl/webprime)
- [WebPrime NX20 parser at the audited commit](https://github.com/racerxdl/webprime/blob/2d145b7917701afa200aa244956eb2616b934fef/lib/nxparser.js)
- [WebPrime asset notice](https://github.com/racerxdl/webprime/blob/2d145b7917701afa200aa244956eb2616b934fef/datapack/LICENSE)
- [GitHub guidance for unlicensed repositories](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
