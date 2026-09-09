# Metronome latency, Qt state callbacks, and profile isolation

Follow-up to `4dfd52a` on `fix/nxa-canonical-pcm`.

## Metronome activation

The previous mixer performed per-sample Python loops synchronously in the GUI
thread. The native mixer now accumulates clicks in 8,192-frame chunks, saturates
once after all overlapping clicks, and emits explicit stereo S16LE. Scratch
accumulation memory is fixed at 128 KiB; the music output remains a full PCM
buffer. Coincident events are deduplicated, and negative/tail overlaps retain
their previous placement. Music PCM used for analysis remains immutable.

The last enabled mix is cached separately from the original music. Disabling
and re-enabling the same schedule reuses implicitly shared QByteArray storage.
Changing the click or event positions replaces that single cached mix.

Measured on Linux x86-64, Python 3.12, GCC, PySide6 6.11.2, using 180 seconds of
zero-valued stereo music, the repository BEAT.wav converted to 48 kHz stereo
(7,076 frames), and 720 clicks spaced 12,000 frames apart:

| Operation | Elapsed |
| --- | ---: |
| Previous Python mixer | 3,515.506 ms |
| Native mixer | 42.014 ms |
| Full PcmPlayback.set_clicks enable | 56.067 ms |
| Disable | 0.043 ms |
| Re-enable unchanged configuration | 0.011 ms |

Old and new mixed bytes were identical. SHA-256:
`9d942a40fe9212a4d74e5d27752f6c50f348d1aa16c14a9ba047780d20e49d2d`.
These are local measurements, not a Windows performance guarantee. An
independent sum-then-clip reference additionally checks randomized PCM, mixed
signs, overlapping events, negative/tail positions and native chunk boundaries.

Rebuild the native extension after updating, using the same interpreter that
launches Studio. For the Windows virtual environment used in this investigation:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[gui]"
```

## Qt callback conversion

The supplied log repeatedly reports an inability to convert `QAudio::State`
when invoking `_state_changed`. Merely changing comparisons to QtAudio enums
did not change the signal metadata in the binding. The connection now targets
an explicit zero-argument Qt slot, which reads `QAudioSink.state()` directly.
The regression test invokes that slot through Qt's meta-object system rather
than only calling the Python state handler directly.

## Prime+/Fiesta isolation

The full GUI smoke now triggers real profile menu actions, without overriding
the profile getter. A generated MP3 with a nonzero NXA startup correction is
loaded, and profiles are switched through Prime+, Fiesta, NXA and Prime+ again.
The checks require:

- NXA uses canonical PCM and manual offset plus its startup correction.
- Prime+/Fiesta use the original compressed file through QMediaPlayer, with
  only the manual offset; no NXA startup analysis or PCM waveform is retained.
- Manual calibration is preserved independently of the automatic correction.
- Play, follow and pause continue working for normal and underrun starts.

The supplied Prime 2/Rise log entries show Qt/FFmpeg reading compressed music,
but contain no selected-profile, calibration, or measured residual information.
No Prime+/Rise timing correction has been introduced. Reproducing the reported
per-chart mismatch still requires an affected chart/audio pair and the selected
profile and calibration used in that comparison.

Validation: 670 unit tests passed, plus the full GUI smoke. Physical Windows
playback and the reported Prime+/Rise residual remain external validation.
