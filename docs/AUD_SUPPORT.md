# ENC2 AUD support

StepNX Studio recognizes Andamiro `.AUD` files as encrypted audio candidates.
It never rewrites the source. A compatible stream is decoded to an MP3 inside a
temporary application directory and that temporary file is passed to Qt.

## Confirmed profile

Static inspection of the supplied console `ENCDecrypt.exe` established this
layout and transform:

- `ENC2` signature;
- payload size at header offset `0x84`;
- relative table skip at `0x88`;
- 16-byte per-file key at `0x8C`;
- 32-bit table start index, a 1024-byte XOR table, then encrypted payload;
- bit reversal of each payload byte followed by indexed XOR;
- the executable's 16-byte profile combined with the per-file key.

The supplied `732.AUD` decodes under that profile to a valid ID3/MP3 stream:
48 kHz, stereo, 100.416 seconds. The decoder validates the MP3 header before
making the temporary stream available.

## Unsupported profiles

The supplied `D91.AUD` and `508.AUD` use the same outer ENC2 structure but a
different key derivation. The NXA executable routes that derivation through an
obfuscated/machine-key path. Applying the self-contained `ENCDecrypt.exe`
profile produces invalid MP3 data for both files.

The editor therefore rejects those streams with `unsupported key profile`.
Writing or playing the decoded noise would hide the incompatibility and make
later timing work untrustworthy. Additional profiles can be added only after a
deterministic derivation and multi-file decode gate are available.

`zlib1.dll` is not involved in this audio path: the supplied decoder imports
only the Windows runtime and C standard-library file/memory functions.
