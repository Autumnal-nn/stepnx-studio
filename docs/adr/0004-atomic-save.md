# ADR 0004 — Atomic publication

Status: accepted, 2026-08-10.

## Decision

The writer first creates a temporary file in the target directory, flushes and
`fsync`s it, then publishes with `os.replace`. Overwrite and backup behavior
are opt-in in both the API and CLI.

This cannot make every storage failure recoverable. It does eliminate the most
avoidable failure mode: truncating the original chart before serialization has
successfully completed.
