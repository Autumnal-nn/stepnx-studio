from __future__ import annotations

from array import array
import sys


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
    output = array("h")
    output.frombytes(samples)
    if sys.byteorder != "little":
        output.byteswap()
    length = len(output) // 2
    click_length = len(click) // 2
    # Accumulate each overlapping group before saturation, using bounded
    # numeric arrays rather than a Python object for every touched sample.
    events = sorted({frame for frame in frames if -click_length < frame < length})
    index = 0
    while index < len(events):
        first = index
        begin = max(0, events[index])
        end = min(length, events[index] + click_length)
        index += 1
        while index < len(events) and events[index] <= end:
            end = min(length, events[index] + click_length)
            index += 1
        mixed = array("i", output[begin * 2:end * 2])
        for frame in events[first:index]:
            for position in range(max(begin, frame) * 2, min(end, frame + click_length) * 2):
                mixed[position - begin * 2] += click[position - frame * 2]
        output[begin * 2:end * 2] = array("h", (max(-32768, min(32767, value)) for value in mixed))
    if sys.byteorder != "little":
        output.byteswap()
    return output.tobytes()
