# Contributing

Every contribution is received and distributed under Apache-2.0. Each
author retains copyright in their contribution. The project uses no CLA and
grants the maintainer no private relicensing right.

## Sign-off

Commits must carry a Developer Certificate of Origin 1.1 sign-off:

```bash
git commit --signoff
```

The sign-off states that the author may legally submit the contribution under
the project's license.

## Intellectual-property boundaries

Do not copy code, artwork, text, or audio from StepEdit, Pump It Up releases, or
decompiled executables. Proprietary material may be used locally as a behavioral
oracle, but it must never become repository content or a release artifact.

STEPEdit-pixi currently has no reusable license. WebPrime and other
copyleft-licensed sources may be studied, but their code must not be copied,
translated, linked, vendored, or included in releases. Game assets remain
proprietary. See
[`docs/VIEWER_SOURCE_AUDIT.md`](docs/VIEWER_SOURCE_AUDIT.md).

All third-party code and dependencies require documented provenance and an
Apache-2.0-compatible permissive license. GPL, AGPL, and copyleft-only code or
dependencies are not accepted in the distributed product. A dependency's
license must be reviewed before each addition or upgrade; later upstream
relicensing does not change the terms of an already selected release.

## Checks

Run before submitting a change:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

If the external research corpus is available, also run:

```bash
PYTHONPATH=src python -m stepnx verify ROOT --row-storage compact
```

Repository documentation, public docstrings, and CLI messages must be written
in English.

## Architecture decisions

Changes to the canonical model, lossless contract, license, default engine
profile, telemetry, or data policy require an ADR. Keep changes focused and do
not mix format behavior with GUI state.
