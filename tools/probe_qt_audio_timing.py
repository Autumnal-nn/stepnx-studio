#!/usr/bin/env python3
"""Measure Qt's decoded sample timeline without playing or modifying music.

This probes the compressed-audio waveform path used by Prime+/Fiesta. It is
not an original-game timing oracle or a measurement of speaker latency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import PySide6
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer, QUrl, qVersion
from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat


def probe(source: Path, timeout_ms: int = 30000) -> dict:
    source = source.resolve(strict=True)
    with source.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    decoder = QAudioDecoder()
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    rows, declared, errors = [], [], []
    pcm_hash = hashlib.sha256()
    finished = False
    declared_at_finish = -1

    def fail(message):
        errors.append(str(message))
        loop.quit()

    def buffer_ready():
        buffer = decoder.read()
        if not buffer.isValid():
            fail('Qt returned an invalid audio buffer')
            return
        fmt = buffer.format()
        rows.append({'start_us': int(buffer.startTime()),
                     'duration_us': int(buffer.duration()),
                     'frames': int(buffer.frameCount()),
                     'rate': int(fmt.sampleRate()),
                     'channels': int(fmt.channelCount()),
                     'sample_format': fmt.sampleFormat().name})
        pcm_hash.update(bytes(buffer.constData()))

    def complete():
        nonlocal finished, declared_at_finish
        declared_at_finish = int(decoder.duration())
        finished = True
        loop.quit()

    decoder.bufferReady.connect(buffer_ready)
    decoder.durationChanged.connect(lambda value: declared.append(int(value)))
    decoder.finished.connect(complete)
    decoder.error.connect(lambda: fail(decoder.errorString()))
    timer.timeout.connect(lambda: fail('Qt decode timed out'))
    decoder.setAudioFormat(QAudioFormat())  # Same native format as Studio.
    decoder.setSource(QUrl.fromLocalFile(str(source)))
    try:
        if not decoder.isSupported():
            raise ValueError('Qt audio decoding is unavailable')
        timer.start(timeout_ms)
        decoder.start()
        if not finished and not errors:
            loop.exec()
        if errors or not finished or not rows:
            raise ValueError('; '.join(errors) or 'Qt did not finish decoding audio')
        formats = {(r['rate'], r['channels'], r['sample_format']) for r in rows}
        if len(formats) != 1 or rows[0]['rate'] <= 0:
            raise ValueError('Qt decoded a changing or invalid audio format')
        frames = sum(r['frames'] for r in rows)
        rate = rows[0]['rate']
        sample_ms = frames * 1000.0 / rate
        span_us = 0
        for row in rows:
            duration = max(0, row['duration_us'])
            span_us = (max(span_us, row['start_us'] + duration)
                       if row['start_us'] >= 0 else span_us + duration)
        waveform_ms = max(0.0, span_us / 1000.0, float(declared_at_finish))
        gaps = []
        for previous, current in zip(rows, rows[1:]):
            if previous['start_us'] >= 0 and current['start_us'] >= 0:
                delta = current['start_us'] - previous['start_us'] - previous['frames'] * 1e6 / rate
                if abs(delta) > 2.0:
                    gaps.append(delta)
        return {
            'source_name': source.name, 'source_sha256': digest,
            'pyside_version': PySide6.__version__, 'qt_version': qVersion(),
            'pipeline': 'QAudioDecoder native format; Prime+/Fiesta waveform probe',
            'pcm_sha256': pcm_hash.hexdigest(), 'decoded_frames': frames,
            'sample_rate': rate, 'channels': rows[0]['channels'],
            'sample_format': rows[0]['sample_format'], 'buffers': len(rows),
            'first_buffer': rows[0], 'last_buffer': rows[-1],
            'declared_duration_changes_ms': declared,
            'declared_duration_at_finish_ms': declared_at_finish,
            'sample_duration_ms': sample_ms,
            'timestamp_span_ms': span_us / 1000.0,
            'studio_waveform_duration_ms': waveform_ms,
            'waveform_minus_sample_duration_ms': waveform_ms - sample_ms,
            'summary_grid_span_ms': math.ceil(frames / 16) * 16 * 1000.0 / rate,
            'timestamp_gap_count': len(gaps), 'first_timestamp_gaps_us': gaps[:10],
            'limitations': 'No playback, manual calibration, chart comparison, or original-game timing measurement',
        }
    finally:
        timer.stop()
        decoder.stop()
        decoder.deleteLater()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', nargs='+', type=Path, help='MP3/WAV/OGG or another Qt-supported audio file')
    args = parser.parse_args(argv)
    app = QCoreApplication.instance() or QCoreApplication([])
    results = []
    for source in args.sources:
        try:
            results.append(probe(source))
        except (OSError, ValueError) as exc:
            results.append({'source_name': source.name, 'error': str(exc)})
        app.processEvents()
    print(json.dumps(results, indent=2))
    return int(any('error' in row for row in results))


if __name__ == '__main__':
    raise SystemExit(main())
