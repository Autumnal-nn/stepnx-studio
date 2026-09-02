# StepNX Studio 0.9.5 editor UX cleanup

Status: active hardening item 6

This pass is deliberately limited to interaction consistency and discoverability. It does not add new NX20 semantics or new authoring subsystems.

## Audit areas

- context-menu consistency;
- selection feedback;
- Inspector empty/selected state;
- redundant actions;
- enabled/disabled action state;
- destructive-action confirmations;
- diagnostics and user-facing error text.

## First concrete finding

The Timeline structure context menu currently creates fresh actions such as `Add Split after`, `Delete Split…`, `Create Block after` and `Delete Block…` instead of presenting the canonical Structure QActions already owned by the main window.

That duplication has two UX costs:

1. labels differ between the context menu and `Edit > Structure`;
2. copied context actions do not automatically inherit the canonical enabled/disabled state used to prevent invalid structural operations.

Item 6 will make context entry points reuse the same canonical actions wherever practical, so labels, availability, keyboard behavior and destructive confirmations cannot drift independently.

## Guardrails

- destructive structural operations keep their existing confirmations;
- disabled canonical actions remain disabled in context menus;
- no action is silently removed merely because it is unavailable for the current selection;
- raw/unknown metadata remains lossless and this UX pass does not invent typed semantics;
- keyboard workflow and sparse-selection performance guarantees remain unchanged.
