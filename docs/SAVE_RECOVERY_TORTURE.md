# Save and recovery torture gate

Date: 2026-09-02

StepNX Studio 0.9.5 treats save and recovery failure behavior as a release
contract rather than an optimistic filesystem assumption. The fault-injection
suite deliberately fails the transaction at points where ordinary happy-path
tests cannot reach.

## Safety contract

For failures that the running process can observe, StepNX Studio must satisfy
one of these outcomes:

1. the pre-save target remains byte-identical;
2. every target already replaced by a multi-file save is restored; or
3. if restoration itself fails, the original backup is preserved on disk and
   its exact backup filename is surfaced in the raised error.

A failed operation must not silently publish a partial recovery snapshot. A
completed recovery snapshot must have a finalized snapshot directory, a
manifest, matching SHA-256 payloads, safe relative payload paths, and parseable
NX20 payloads.

## Save fault matrix

The dedicated torture suite covers the following cases in addition to the
existing workspace save tests.

| Injected failure | Required result |
| --- | --- |
| temporary stage creation denied | original target unchanged; no transaction artifact |
| stage `fsync` reports `ENOSPC` | original target unchanged; created stage removed |
| original-backup copy fails | original target unchanged; stage and failed backup removed |
| `KeyboardInterrupt` after the first multi-file replacement | already committed target restored; remaining target unchanged; interruption re-raised |
| later replacement fails | prior replacements rolled back |
| rollback replacement itself fails | original `.stepnx-original` backup retained and named in `WorkspaceError` |
| a newly created target must be rolled back | new target removed rather than leaving a partial publication |
| successful save | expected payload published; no `.stepnx-stage`/`.stepnx-original` debris |

Existing tests continue to cover stale-target detection both before execution
and between operations in a multi-file save. The hardened transaction therefore
does not weaken the preflight provenance checks while adding failure cleanup.

### Transaction bookkeeping rule

Temporary paths are registered for cleanup immediately after creation, before
any write, copy, flush, or `fsync` that can fail. This ordering is deliberate.
Registering a delete-on-failure path only after I/O completes creates a blind
spot precisely when disk-full and permission errors occur.

Original backups follow the same rule. If a rollback consumes the backup
successfully it is cleared from transaction state. If rollback cannot consume
it, cleanup deliberately leaves it in place as the last recoverable copy.

## Recovery fault matrix

| Injected/corrupt condition | Required result |
| --- | --- |
| recovery staging creation denied | normalized `RecoveryError`; no published snapshot |
| payload `fsync` reports `ENOSPC` | hidden staging removed; no published snapshot |
| `KeyboardInterrupt` while writing the manifest | hidden staging removed before interruption propagates |
| final staging-to-snapshot rename fails | staging removed; normalized `RecoveryError` |
| orphan hidden staging directory exists after an uncatchable crash | ignored by `RecoveryStore.list()` |
| payload bytes do not match manifest SHA-256 | load rejected |
| manifest payload path escapes snapshot directory | load rejected |
| payload hash matches but NX20 structure is corrupt | parser failure normalized to `RecoveryError` |
| source provenance changed since snapshot creation | restore rejected |

`RecoveryStore.list()` accepts only finalized 32-character lowercase hexadecimal
snapshot directories containing a manifest. The hidden `.<snapshot>.*` staging
namespace is never presented to the user as a completed recovery point.

## What this does not claim

A multi-file `Save All` cannot be made physically atomic with a sequence of
ordinary filesystem renames. If the process or machine is terminated after one
target rename and before the next, there is no opportunity for in-process
rollback. Achieving ACID-like recovery across that boundary would require a
persistent transaction journal and restart-time reconciliation.

0.9.5 therefore makes the narrower, testable guarantee:

- every individual target replacement is staged before publication;
- all catchable execution failures trigger best-effort rollback;
- a rollback failure preserves the original backup rather than deleting it;
- catchable recovery-write failures never publish staging as a snapshot;
- orphan recovery staging from an uncatchable termination is ignored;
- no claim is made that a hard power loss across multiple target renames can be
  automatically reconstructed as one transaction.

Likewise, the suite cannot prove behavior of storage hardware that violates the
operating system's `fsync`/rename guarantees.

## Automated coverage

The dedicated tests live in `tests/unit/test_save_recovery_torture.py` and add
13 fault-injection cases to the 560-test checkpoint established by the 0.9.5
selection-performance work. The strict Windows discovery floor is therefore
573 tests.

The full suite still exercises the pre-existing folder/recovery cases, including
stale-target changes, multi-file rollback, SHA-256 tampering, unsafe manifest
paths, source provenance changes, and normal snapshot reload.
