# Viewer implementation source audit

Date: 2026-08-10

> Historical source audit. Version numbers, implementation gaps and proposed
> integration sequences below describe the project as it existed on the audit
> date. In particular, `0.1.0.dev0` is intentionally retained as the audited
> StepNX snapshot, not presented as the current version. The current product uses
> a native Qt authoring viewport and native Qt gameplay preview over the canonical
> StepNX model; see `STATUS.md`, `ROADMAP.md`, and ADR 0015 for current decisions.

## Decision summary

The two audited projects solved different view problems and were evaluated as
references for the appropriate module. Neither may replace the StepNX canonical
model.

| Source | Approved role at audit time | Rejected role |
| --- | --- | --- |
| STEPEdit-pixi | layout and interaction reference for the vertical authoring viewport | canonical parser/writer, document model, or mandatory web runtime |
| WebPrime | behavioral/rendering reference for gameplay preview | authoritative NX loader, editable model, or normative engine emulator |
| StepNX core | sole authority for open, preserve, mutate, validate, diff, and save | view-specific rendering logic |

“Base” in the original evaluation meant a possible module-level reference, not
the foundation of the application. The eventual implementation chose native Qt
for both authoring and gameplay preview rather than integrating either external
renderer.

## Audited material

- STEPEdit-pixi commit
  `d2fc56d519068c8bccc8b07c943647049426c0a5` (2026-05-05);
- WebPrime commit
  `2d145b7917701afa200aa244956eb2616b934fef` (2026-06-02);
- unpacked StepEdit 5.63;
- `nx_editor-v60.py`;
- StepNX Studio core `0.1.0.dev0` and its then-current 12,909-file corpus gate.

Both JavaScript projects installed dependencies and produced production builds
in the audit environment. A successful build proves that the trees were
buildable; it does not validate timing, branch selection, or interactive
rendering behavior.

## STEPEdit-pixi

### Useful design

The viewport makes several authoring choices also seen in StepEdit 5.63:

- vertical row/beat timeline;
- visible split boundaries;
- measure ruler, grid, and block data;
- active-block switching within a split;
- taps, holds, items, and Division visualization;
- contextual metadata/flag inspection.

As a layout study it was substantially more useful than the monolithic Canvas in
`nx_editor-v60.py`, which recreated broad visual state after each action.

### Components that could not become authoritative

The audited parser/model violates the Studio contract:

- metadata and Divisions are stored in `Map`, collapsing duplicate IDs;
- known fields are normalized and unknown values may become defaults;
- Lightmap is rejected;
- trailers and opaque tails are ignored;
- raw floats and source spans disappear;
- unknown note subtypes are not preserved as first-class data;
- no lossless writer or authoring command system exists.

The renderer also was not suitable as a literal port:

- it creates objects/components for the entire chart;
- it lacks the StepNX viewport-culling architecture;
- it uses fixed geometry and has no shared StepNX audio/timing transport;
- it is coupled to React and PixiJS while the desktop implementation is Qt.

The shipped StepNX authoring viewport therefore implements the useful interaction
ideas independently over `AuthoringSnapshot` and the canonical command model.

### License

The audited repository had no `LICENSE`, copyright notice, or `package.json`
license field. `private: true` grants no reuse right. Licenses of dependencies do
not license the application itself.

Therefore behavior may be studied and compared, but copying, translating, or
porting code requires a compatible license grant from the relevant copyright
holders. Unlicensed sprites remain excluded.

## WebPrime

### Useful design

WebPrime targeted gameplay preview rather than chart authoring and provided a
useful historical behavioral comparison for:

- audio/update-loop structure;
- beat/time projection;
- timing changes and scrolling;
- hold/effect/noteskin presentation;
- one-route gameplay rendering.

Its parser selected/discarded branches too early and mixed parsing,
interpretation, route choice and rendering. That architecture conflicts with the
StepNX requirement that all branches remain in the canonical document and that
route choice be preview-session state.

### Frozen StepNX integration boundary

The eventual architecture is:

```text
Canonical Document
    -> PreviewSnapshot (read-only)
    -> RouteResolver / runtime state
    -> RuntimeEventStream
    -> native Qt renderer
```

WebPrime does not parse NX for StepNX and no WebPrime runtime is distributed.
The earlier audit's suggestion to prototype a web preview was superseded by the
native Qt implementation.

### License and assets

The audited WebPrime tree was copyleft-licensed under inconsistent version
notices and its game-data pack contains proprietary Pump It Up assets. Those
terms/assets are incompatible with StepNX Studio's distribution boundary. No
WebPrime code, JPAK data, official noteskins, combo graphics, or sample charts
enter the Studio repository or releases.

## Frozen architectural boundary

```text
Lossless codec -> Canonical Document -> Commands / Validators
                         |                       |
                         +-> AuthoringSnapshot --+-> Qt viewport
                         |
                         +-> PreviewSnapshot -> RouteResolver -> native Qt gameplay view
```

Rules:

1. only the core opens and saves NX/NFO;
2. snapshots include stable IDs but no mutable byte references;
3. the authoring view issues commands; gameplay preview is read-only;
4. route policy/state remains preview-session state;
5. unknown semantics produce diagnostics, never normalization;
6. no proprietary asset ships in an official build.

## Primary sources

- [STEPEdit-pixi](https://github.com/StepMania-AMX/STEPEdit-pixi)
- [STEPEdit-pixi NX20 parser at the audited commit](https://github.com/StepMania-AMX/STEPEdit-pixi/blob/d2fc56d519068c8bccc8b07c943647049426c0a5/src/parser/nx20.js)
- [STEPEdit-pixi vertical renderer at the audited commit](https://github.com/StepMania-AMX/STEPEdit-pixi/blob/d2fc56d519068c8bccc8b07c943647049426c0a5/src/components/step.js)
- [WebPrime](https://github.com/racerxdl/webprime)
- [WebPrime NX20 parser at the audited commit](https://github.com/racerxdl/webprime/blob/2d145b7917701afa200aa244956eb2616b934fef/lib/nxparser.js)
- [WebPrime asset notice](https://github.com/racerxdl/webprime/blob/2d145b7917701afa200aa244956eb2616b934fef/datapack/LICENSE)
- [GitHub guidance for unlicensed repositories](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
