# Original audio fixtures

`generated.mp3` contains original synthetic sine waves. It contains no game
audio. It was generated with FFmpeg's lavfi source and libmp3lame:

```sh
ffmpeg -f lavfi -i 'aevalsrc=0.22*sin(2*PI*431*t)+0.09*sin(2*PI*773*t)|0.19*sin(2*PI*619*t):s=48000:d=0.45' -codec:a libmp3lame -b:a 192k -write_xing 0 -id3v2_version 0 generated.mp3
```

The committed bytes, rather than the installed encoder version, are the test
input. `generated.sha256` is the SHA-256 of their canonical, untrimmed stereo
S16LE decode. Decoder/compiler upgrades must preserve that golden result or
receive an explicit contract/version review.

`startup-oracle.json` records the seed, input hash and expected recovery traces
for 1,000 manufactured prefixes. Entries contain status, first accepted byte
offset, and preceding `[byte_offset, synthesized_frames]` pairs. The reference
was produced using `tools/nxa_pcm_oracle.c` with Debian libmad 0.15.1b-10.1+b1.
The `rejected` cases have reference observations but lie outside the supported
clean-room startup model; tests require explicit refusal. No oracle library or
executable is distributed with these fixtures.
