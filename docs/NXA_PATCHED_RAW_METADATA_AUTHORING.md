# NXA-patched metadata input policy

Applies only to profile `nxa-step5-patched`, scopes **Header** and **Division**.

- Every 32-bit metadata ID and 32-bit value is allowed in these scopes, regardless of registry recognition or typed semantic validity. Unknown or odd combinations are intentional and must not be rejected or silently changed by the editor.
- The Add dialog exposes `Custom raw ID...` exclusively in these patched scopes. It allows IDs `0..0xFFFFFFFF`.
- Unknown **Header** IDs use exact unsigned 32-bit raw value input by default.
- Unknown **Division** IDs use packed unsigned min/max (low 16 / high 16) by default. Raw uint32 override remains available.
- Known fields expose typed editing and a raw uint32 option so out-of-range or otherwise unsupported values can still be authored.
- This permission is an *authoring policy*, not proof that the executable interprets all possible IDs or values. Runtime validity is outside this UI gate.
- Native NXA, Fiesta and Prime+ retain their existing profile-specific typed edit restrictions and lossless preservation of unknown fields.

The common byte-exact model and ordered duplicate metadata semantics are unchanged.
