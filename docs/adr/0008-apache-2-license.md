# ADR 0008 — Adopt Apache License 2.0

Status: accepted, 2026-08-10.

## Decision

StepNX Studio is distributed under Apache License 2.0. Contributions use the
same inbound and outbound license, with DCO 1.1 sign-off and no CLA.

Distributed code and dependencies must have documented provenance and an
Apache-2.0-compatible permissive license. GPL, AGPL, copyleft-only, unlicensed,
or provenance-unclear code is excluded. Proprietary game assets and extracted
content remain excluded regardless of the code license.

WebPrime and STEPEdit-pixi may be used only as behavioral or layout references
unless every relevant copyright holder supplies a compatible public license.
Independent implementation from documented behavior remains permitted.

## Consequences

- downstream users may redistribute modified versions under different terms
  while preserving the Apache license, notices, and attribution requirements;
- distributed forks are not required to publish their modifications;
- accepted contributors provide Apache's express patent grant for their work;
- dependency additions and upgrades require license and provenance review;
- historical license grants for already published snapshots remain valid;
- a history rewrite may simplify the visible documentation history, but does
  not erase previously distributed commits, clones, forks, or grants.
