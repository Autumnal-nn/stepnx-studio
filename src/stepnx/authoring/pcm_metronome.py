from __future__ import annotations


def mix_clicks(samples: bytes, click: tuple[int, ...], frames: tuple[int, ...]) -> bytes:
    """Mix stereo S16 clicks at absolute PCM frame indices.

    Coincident chart events are one click. Negative starts and tail overlaps
    are clipped to the music range. Full mixing before playback makes seek,
    device read chunk size and GUI timer jitter irrelevant to click placement.
    The original music PCM remains immutable for waveform analysis/export.
    """
    if len(samples) % 4 or len(click) % 2:
        raise ValueError("music and click must contain complete stereo frames")
    if not click or not frames:
        return samples
    from stepnx import _mpeg_pcm

    length = len(samples) // 4
    click_length = len(click) // 2
    events = tuple(sorted({frame for frame in frames if -click_length < frame < length}))
    if not events:
        return samples
    mixer = getattr(_mpeg_pcm, "mix_clicks", None)
    if mixer is None:
        raise ValueError("PCM mixer extension is outdated; reinstall Studio with the same Python interpreter to rebuild it.")
    return mixer(samples, click, events)
