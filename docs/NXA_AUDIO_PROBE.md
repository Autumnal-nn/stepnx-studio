# NXA audio runtime probe

For the current deterministic Studio decoder and offline reference gates, see
[NXA PCM contract](NXA_PCM_CONTRACT.md). This runtime probe remains necessary
to measure chart-clock and physical-output residuals; offline PCM agreement
does not replace those observations.

This experiment observes the actual 32-bit NXA audio path instead of inferring
runtime timing from MP3/libmad startup errors alone.

The probe is passive. Every intercepted function is forwarded unchanged through
`RTLD_NEXT`.

## Captured calls

- `mad_stream_init`
- `mad_stream_buffer`
- `mad_frame_decode` plus `mad_stream_errorstr` on failure
- `mad_synth_frame`
- `snd_pcm_open`
- `snd_pcm_prepare`
- `snd_pcm_drop`
- `snd_pcm_writei`
- `snd_pcm_delay`
- `snd_pcm_close`

The exact byte buffers passed to `snd_pcm_writei` are also dumped. Byte counts
come from ALSA's `snd_pcm_frames_to_bytes`, so the probe does not hard-code a
sample format.

## Build

NXA is 32-bit. Build the probe as i386:

```sh
make -f tools/Makefile.nxa-audio-probe -C tools
```

If `gcc -m32` is unavailable, install the distribution's 32-bit multilib
toolchain first.

No libmad or ALSA development headers are required.

## Run

Use a fresh directory for each test:

```sh
rm -rf /tmp/nxa-audio-probe
mkdir -p /tmp/nxa-audio-probe
export NXA_AUDIO_PROBE_DIR=/tmp/nxa-audio-probe
export NXA_AUDIO_PROBE_MAX_MB=64
```

Preload `nxa_audio_probe.so` before the game's existing hook:

```sh
export LD_PRELOAD="/absolute/path/to/nxa_audio_probe.so:${LD_PRELOAD}"
./piueb
```

If `piueb` overwrites `LD_PRELOAD`, prepend the probe to the assignment inside
`piueb`, before the existing `hook.so`. Do not remove the existing hook.

## First validation set

Capture one song per launch for the first pass:

- F08
- F17
- F40
- F24
- F25

Start the song, let at least 15-20 seconds play, then exit normally.

## Output

`events.tsv` contains ordered events with monotonic timestamp, Linux TID,
libmad-stream generation, sequence number, object pointer, arguments, and
libmad error text.

`pcm-genNNN-handle-0x....raw` contains the exact bytes handed to that ALSA PCM
handle during the corresponding generation.

These captures are intended to answer, directly:

1. Which `mad_frame_decode` failures are followed by `mad_synth_frame`?
2. Which synthesized buffers actually reach `snd_pcm_writei`?
3. Why F17 and F40 differ in observed Studio correction despite sharing the
   same aggregate startup class in the earlier analyzer?
4. What is the exact NXA-versus-FFmpeg offset in samples?
5. Whether `snd_pcm_delay` / startup queue state adds another transient or
   constant term.

## Current Windows-side baseline

The StepNX Studio test run reports Qt Multimedia using FFmpeg 7.1.5 and the
`mp3float` decoder. The MP3 demuxer reports `start: 0.000000` and
`Estimating duration from bitrate` for the tested NXA masters. Thus the present
comparison is specifically NXA/libmad/ALSA versus FFmpeg/mp3float rather than an
unknown Media Foundation path.
