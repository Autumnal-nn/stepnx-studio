from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from dataclasses import replace
from pathlib import Path

from stepnx.authoring import (
    AudDecodeError,
    AudioAlignment,
    MetronomeClock,
    NoteMetronomeClock,
    WaveformError,
    create_authoring_snapshot,
    decode_enc2_aud,
    load_pcm_wav_waveform,
)
from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.commands import SetNoteAt
from stepnx.core.scalars import RawU8
from tests.fixture_factory import make_large_lightmap, make_normal_nx20


class WaveformTests(unittest.TestCase):
    def test_pcm_wav_is_reduced_to_normalized_peaks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tone.wav"
            samples = [0, 32767, -32768, 16384] * 100
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(1000)
                output.writeframes(b"".join(struct.pack("<h", value) for value in samples))

            waveform = load_pcm_wav_waveform(path, buckets=20)

            self.assertAlmostEqual(waveform.duration_ms, 400.0)
            self.assertEqual(len(waveform.peaks), 20)
            self.assertTrue(all(0.0 <= peak <= 1.0 for peak in waveform.peaks))
            self.assertGreater(waveform.amplitude_at(100.0), 0.9)

    def test_invalid_wav_is_reported_without_crashing_transport(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.wav"
            path.write_bytes(b"not a wave")
            with self.assertRaises(WaveformError):
                load_pcm_wav_waveform(path)


class AudDecodeTests(unittest.TestCase):
    @staticmethod
    def _enc2_fixture(
        payload: bytes,
        *,
        base_profile: bytes = bytes.fromhex("000000001c1d1e1f3c3e383a585b5e59"),
    ) -> bytes:
        reverse = bytes(int(f"{value:08b}"[::-1], 2) for value in range(256))
        key = bytes(range(16))
        table = bytes((index * 37 + 11) & 0xFF for index in range(1024))
        start = 0x12345678
        stream = bytes(
            value ^ base_profile[index & 15] ^ key[index & 15]
            for index, value in enumerate(table)
        )
        encrypted = bytes(
            reverse[value ^ stream[(start + index) & 1023]]
            for index, value in enumerate(payload)
        )
        skip = 5
        header = bytearray(156)
        header[:4] = b"ENC2"
        struct.pack_into("<II", header, 0x84, len(payload), skip)
        header[0x8C:0x9C] = key
        return bytes(header) + bytes(skip) + struct.pack("<I", start) + table + encrypted

    def test_encdecrypt_profile_decodes_to_mp3_bytes(self) -> None:
        payload = b"ID3\x03\x00\x00\x00\x00\x00\x00" + bytes(range(64))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "song.AUD"
            path.write_bytes(self._enc2_fixture(payload))

            self.assertEqual(decode_enc2_aud(path), payload)

    def test_nxa_profile_is_recovered_from_mastering_signature(self) -> None:
        # One of the four prefixes observed in the paired 39-song corpus.
        # The profile itself is arbitrary: recovery must come from the MP3
        # plaintext signature rather than from a per-song hard-coded key.
        signature = b"\xff\xfb\xb4D" + b"\x00" * 32 + b"Info"
        payload = signature + bytes(range(64))
        nxa_profile = bytes.fromhex("ba81da7ea69ec09db6bfdab8a2d4f8df")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nxa-song.AUD"
            path.write_bytes(
                self._enc2_fixture(payload, base_profile=nxa_profile)
            )

            self.assertEqual(decode_enc2_aud(path), payload)

    def test_wrong_enc2_profile_is_rejected_instead_of_returning_noise(self) -> None:
        payload = b"ID3\x03\x00\x00\x00\x00\x00\x00" + bytes(range(64))
        fixture = bytearray(self._enc2_fixture(payload))
        fixture[-len(payload)] ^= 0x01
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wrong-profile.AUD"
            path.write_bytes(fixture)
            with self.assertRaisesRegex(AudDecodeError, "unsupported key profile"):
                decode_enc2_aud(path)


class AudioTimingTests(unittest.TestCase):
    def test_session_offset_is_bidirectional(self) -> None:
        alignment = AudioAlignment(125.5)
        self.assertEqual(alignment.chart_to_audio(1000), 1125.5)
        self.assertEqual(alignment.audio_to_chart(1125.5), 1000)

    def test_metronome_uses_absolute_time_instead_of_accumulating_ticks(self) -> None:
        document = parse_bytes(make_large_lightmap(rows=100), source="LM.NX")
        block = create_authoring_snapshot(document).splits[0].blocks[0]
        clock = MetronomeClock(create_authoring_snapshot(document))

        first = clock.beat_at(block.start_time + 10)
        second = clock.beat_at(block.start_time + 510)

        self.assertEqual(first.beat_index, 0)
        self.assertEqual(second.beat_index, 1)
        self.assertTrue(first.is_measure)

    def test_non_finite_offset_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AudioAlignment(math.nan)

    def test_note_metronome_ticks_once_for_a_chord_and_ignores_hold_body(self) -> None:
        document = parse_bytes(make_normal_nx20(), source="NM.NX")
        split = document.splits[0]
        document = replace(
            document,
            splits=(
                replace(
                    split,
                    blocks=(
                        replace(split.blocks[0], smooth_speed=RawU8.from_value(1)),
                    ),
                ),
            ),
        )
        first_row, second_row = document.splits[0].blocks[0].rows
        document = SetNoteAt(first_row.stable_id, 4, b"\x43\x03\x00\x00").apply(
            document
        )
        document = SetNoteAt(second_row.stable_id, 0, b"\x4B\x03\x00\x00").apply(
            document
        )
        snapshot = create_authoring_snapshot(document)
        clock = NoteMetronomeClock(snapshot)
        block = snapshot.splits[0].blocks[0]
        row_duration = 60_000.0 / (block.bpm * block.beat_split)

        chord = clock.note_at(block.start_time + 1)
        after_body = clock.note_at(block.start_time + row_duration + 1)

        self.assertEqual(chord.row_index, 0)
        self.assertEqual(after_body, chord)

    def test_note_metronome_uses_register_bit_not_visibility(self) -> None:
        document = parse_bytes(make_normal_nx20(), source="NM.NX")
        split = document.splits[0]
        block = replace(split.blocks[0], smooth_speed=RawU8.from_value(1))
        document = replace(
            document, splits=(replace(split, blocks=(block,)),)
        )
        first_row, second_row = document.splits[0].blocks[0].rows
        # Hidden + Invisible still registers; Ghost + Visible does not.
        document = SetNoteAt(first_row.stable_id, 0, b"\x63\x00\x00\x00").apply(
            document
        )
        document = SetNoteAt(second_row.stable_id, 0, b"\x23\x03\x00\x00").apply(
            document
        )
        snapshot = create_authoring_snapshot(document)
        clock = NoteMetronomeClock(snapshot)
        block = snapshot.splits[0].blocks[0]
        row_duration = 60_000.0 / (block.bpm * block.beat_split)

        registered = clock.note_at(block.start_time + 1)
        after_ghost = clock.note_at(block.start_time + row_duration + 1)

        self.assertEqual(registered.row_index, 0)
        self.assertEqual(after_ghost, registered)

    def test_metronomes_keep_smooth_speed_blocks(self) -> None:
        document = parse_bytes(make_normal_nx20(), source="NM.NX")
        first_row = document.splits[0].blocks[0].rows[0]
        document = SetNoteAt(first_row.stable_id, 0, b"\x43\x03\x00\x00").apply(
            document
        )
        snapshot = create_authoring_snapshot(document)
        block = snapshot.splits[0].blocks[0]

        self.assertIsNotNone(MetronomeClock(snapshot).beat_at(block.start_time))
        self.assertIsNotNone(NoteMetronomeClock(snapshot).note_at(block.start_time))


if __name__ == "__main__":
    unittest.main()
