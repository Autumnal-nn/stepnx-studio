# Andamiro AUD support

StepNX Studio recognizes Andamiro `.AUD` / `.A` files as encrypted audio
candidates. It never rewrites the source. A supported wrapper is decoded to an
MP3 inside a temporary application directory and that temporary file is passed
to Qt for playback and waveform decoding.

## ENC1

Static inspection of the supplied official `ENCDecrypt.exe` and
`ENCEncrypt.exe` established the ENC1 layout and transform directly. Both tools
contain the same 1024-byte static table.

The relevant layout is:

- `ENC1` signature at offset `0x00`;
- encoded payload size at `0x7E`, with `payload_size = encoded_size ^ 0xCCBB`;
- relative skip at `0x82`;
- `skip` bytes beginning at `0x86`;
- 32-bit table start index immediately after those bytes;
- encrypted MP3 payload immediately after the start index.

For payload byte `i`, the official transform is equivalent to:

```text
plain[i] = bit_reverse(cipher[i])
           XOR static_table[(start_index + i) & 0x3ff]
```

No per-song profile is needed for ENC1 payload decryption. Three supplied
Windows-source samples from substantially different corpus groups (`103.AUD`,
`F09.AUD`, and `NXA.AUD`) decode with this same routine to valid MP3 streams.

## ENC2

Static inspection of `ENCDecrypt.exe` established the self-contained ENC2
layout and transform:

- `ENC2` signature;
- payload size at header offset `0x84`;
- relative table skip at `0x88`;
- 16-byte per-file key at `0x8C`;
- 32-bit table start index, a 1024-byte XOR table, then encrypted payload;
- bit reversal of each payload byte followed by indexed XOR;
- the executable's 16-byte base profile combined with the per-file key.

That official profile remains the first decode path.

### NXA per-file ENC2 profiles

A paired 39-song Windows/Linux corpus demonstrated that original Linux NXA
wrappers can use a different profile for every file even when the decrypted MP3
is byte-identical to the Windows counterpart. The 39 Linux wrappers produced 39
distinct profiles, so storing one profile per song is deliberately not used.

StepNX instead has two deterministic recovery paths:

1. strongly validated MP3 mastering prefixes observed in the paired corpus can
   recover all 16 repeating profile lanes from known plaintext;
2. a 32-byte zero run in the MP3 can recover the same lanes without knowing the
   mastering prefix, because the unknown ENC2 component repeats every 16 bytes.
   Candidate recovery is accepted only when the resulting stream has a valid
   MP3 header.

On the current 843-file working corpus, 388 files are ENC2. Before zero-run
recovery 187 decoded; a further 98 were recoverable through the zero-run path,
for 285/388 supported ENC2 files. 103 ENC2 files remain unresolved and are
rejected rather than emitted as plausible-looking noise.

The same corpus contains 455 ENC1 files. Their payload format is handled by the
official ENC1 algorithm above rather than by any ENC2 profile heuristic.

## Safety and staging

Decoded bytes are validated as MP3 before being staged. Unsupported or malformed
wrappers raise `AudDecodeError`; the encrypted source is never modified.

`zlib1.dll` is not involved in the AUD decrypt path inspected here:
`ENCDecrypt.exe` imports only the Windows runtime / C standard-library functions
used by its file and memory operations.
