from __future__ import annotations

import hashlib
import json
import random
import tempfile
import unittest
import wave
from pathlib import Path

from stepnx.authoring.pcm import PcmDecodeError, decode_mp3_pcm
from stepnx.authoring.pcm_cli import main
from stepnx.authoring.nxa_startup import NxaStartupError, analyze_nxa_mp3_startup
from stepnx.authoring.pcm_metronome import mix_clicks
from tests.unit.test_nxa_startup import _source_chain


FIXTURE = Path(__file__).parents[1] / "fixtures/audio/generated.mp3"


class PcmTests(unittest.TestCase):
    def test_startup_matches_external_oracle_regressions_or_refuses(self):
        fixture = FIXTURE.read_bytes()
        reference = json.loads((FIXTURE.parent / "startup-oracle.json").read_text())
        self.assertEqual(hashlib.sha256(fixture).hexdigest(), reference["fixture_sha256"])
        rng = random.Random(reference["seed"])
        for index, (status, first, recoveries) in enumerate(reference["results"]):
            prefix = bytearray(rng.randbytes(rng.randrange(4, 2048)))
            for _ in range(rng.randrange(4)):
                at = rng.randrange(0, len(prefix) - 3)
                prefix[at:at + 2] = b"\xff\xff"
            payload = bytes(prefix) + fixture
            with self.subTest(case=index):
                if status == "rejected":
                    with self.assertRaises(NxaStartupError):
                        analyze_nxa_mp3_startup(payload)
                else:
                    result = analyze_nxa_mp3_startup(payload)
                    self.assertEqual(result.first_decoded_offset, first)
                    self.assertEqual([[item.offset, item.synthesized_samples] for item in result.recoveries], recoveries)

    def test_clicks_share_sample_grid_and_seek_keeps_overlap_tail(self):
        import struct

        music = bytes(20 * 4)
        click = (1000, -1000, 2000, -2000, 3000, -3000)
        mixed = mix_clicks(music, click, (2, 2, 4, -1, 19))
        frames = list(struct.iter_unpack("<hh", mixed))
        self.assertEqual(frames[:6], [(2000, -2000), (3000, -3000), (1000, -1000),
                                      (2000, -2000), (4000, -4000), (2000, -2000)])
        self.assertEqual(frames[-1], (1000, -1000))
        self.assertEqual(mixed[3 * 4:5 * 4], struct.pack("<hhhh", 2000, -2000, 4000, -4000))
        self.assertEqual(music, bytes(20 * 4))

    def test_metadata_changes_startup_but_never_changes_source_pcm(self):
        payload = FIXTURE.read_bytes()
        clean = decode_mp3_pcm(payload)
        for count, expected in [(0, -1152), (1, -1536), (2, -1920), (3, -2304)]:
            # Deliberately manufactured false headers, not bytes copied from a song.
            prefix = b"Synthetic tag " + (bytes.fromhex("fffe4f00") + b"abcdef") * count
            wrapped = decode_mp3_pcm(prefix + payload)
            self.assertEqual(clean.samples, wrapped.samples)
            self.assertEqual(wrapped.startup.net_source_lead_samples, expected)
            self.assertEqual(clean.frame_count, wrapped.frame_count)

    def test_independent_decodes_are_byte_identical(self):
        payload = FIXTURE.read_bytes()
        first, second = decode_mp3_pcm(payload), decode_mp3_pcm(payload)
        self.assertEqual(first, second)
        self.assertEqual(first.report(), second.report())
        golden = (FIXTURE.parent / "generated.sha256").read_text().strip()
        self.assertEqual(hashlib.sha256(first.samples).hexdigest(), golden)
        self.assertTrue(any(first.samples))

    def test_seek_is_an_exact_slice_of_the_full_decode(self):
        pcm = decode_mp3_pcm(FIXTURE.read_bytes())
        for first, last in [(1, 2), (529, 1679), (1151, 2305), (pcm.frame_count - 17, pcm.frame_count)]:
            self.assertEqual(pcm.slice_frames(first, last), pcm.samples[first * 4:last * 4])
        self.assertEqual(pcm.frame_at_ms(1.0), 48)
        self.assertEqual(pcm.frame_at_ms(pcm.duration_ms + 100), pcm.frame_count)
        with self.assertRaises(ValueError):
            pcm.frame_at_ms(float("nan"))

    def test_sample_ledger_includes_metadata_frames_and_priming(self):
        payload = bytearray(_source_chain())
        payload[36:40] = b"Info"
        pcm = decode_mp3_pcm(bytes(payload))
        self.assertEqual(pcm.frame_count, 4 * 1152)
        self.assertEqual(pcm.duration_ms, 96.0)
        self.assertEqual(pcm.report()["gapless_trim_samples"], 0)

    def test_crc_protected_valid_layer3_is_not_assumed_corrupt(self):
        header = bytes.fromhex("fffab404")
        protected = header[2:] + bytes(32)
        crc = 0xFFFF
        for value in protected:
            for bit in range(8):
                feedback = bool(crc & 0x8000) != bool(value & (0x80 >> bit))
                crc = (crc << 1) & 0xFFFF
                if feedback:
                    crc ^= 0x8005
        frame = header + crc.to_bytes(2, "big") + bytes(570)
        startup = analyze_nxa_mp3_startup(frame * 4)
        self.assertEqual(startup.recoveries, ())
        self.assertEqual(decode_mp3_pcm(frame * 4).frame_count, 4608)
        broken = bytearray(frame * 4)
        broken[4] ^= 1
        with self.assertRaises(PcmDecodeError):
            decode_mp3_pcm(bytes(broken))

    def test_corruption_and_truncation_do_not_silently_shrink_timeline(self):
        payload = FIXTURE.read_bytes()
        broken = bytearray(payload)
        broken[576 * 4] = 0
        for data in (bytes(broken), payload[:-1], payload + b"unknown trailer"):
            with self.subTest(size=len(data)):
                with self.assertRaises(PcmDecodeError):
                    decode_mp3_pcm(data)

    def test_wav_preserves_exact_samples_and_does_not_replace_source(self):
        payload = FIXTURE.read_bytes()
        pcm = decode_mp3_pcm(payload)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "canonical.wav"
            pcm.write_wav(target)
            with wave.open(str(target)) as source:
                self.assertEqual(source.getframerate(), 48000)
                self.assertEqual(source.getnframes(), pcm.frame_count)
                self.assertEqual(source.readframes(pcm.frame_count), pcm.samples)
            self.assertEqual(main([str(target), "--wav", str(target)]), 2)
        self.assertEqual(FIXTURE.read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
