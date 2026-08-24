from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QObject, QTemporaryDir, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QSoundEffect

from stepnx.authoring.audio import AudDecodeError, decode_enc2_aud


class AudioTransport(QObject):
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    playbackChanged = Signal(bool)
    errorOccurred = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.output = QAudioOutput(self)
        self.output.setVolume(0.8)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.output)
        self.metronome = QSoundEffect(self)
        self.metronome.setLoopCount(1)
        self.metronome.setVolume(0.9)
        self._aud_directory: QTemporaryDir | None = None
        self._playback_source: Path | None = None
        application = QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self.cleanup_aud_staging)
        self._aud_serial = 0
        self._position_anchor = 0
        self._last_emitted_position = -1
        self._position_clock = QElapsedTimer()
        self._position_timer = QTimer(self)
        self._position_timer.setInterval(16)
        self._position_timer.timeout.connect(self._poll_position)
        # QMediaPlayer exposes both values as qlonglong. PySide 6.11 refuses
        # to connect those signals directly to our Python ``Signal(int)``;
        # route them through callables so the values are normalized before
        # they are re-emitted.
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._playback_state)
        self.player.errorOccurred.connect(
            lambda error, message: self.errorOccurred.emit(message or str(error))
        )

    @property
    def playback_source(self) -> Path | None:
        """Exact local file currently handed to QMediaPlayer.

        For ordinary formats this is the selected source. ENC2 AUD/A is decoded
        and staged as MP3 first, so waveform decoding can consume precisely the
        same bytes as playback instead of independently repeating that pipeline.
        """

        return self._playback_source

    def load(self, path: str | Path | None) -> bool:
        self.player.stop()
        self.player.setSource(QUrl())
        self._playback_source = None
        self._position_timer.stop()
        self._position_clock.invalidate()
        self._position_anchor = 0
        self._last_emitted_position = -1
        if path is None:
            if self._aud_directory is not None:
                self.cleanup_aud_staging()
            return True
        source = Path(path)
        if source.suffix.casefold() in {".aud", ".a"}:
            try:
                payload = decode_enc2_aud(source)
            except AudDecodeError as exc:
                self.errorOccurred.emit(str(exc))
                return False
            directory = self._ensure_aud_directory()
            if directory is None:
                return False
            self._aud_serial += 1
            source = Path(directory.path()) / f"decoded-{self._aud_serial}.mp3"
            try:
                source.write_bytes(payload)
            except OSError as exc:
                self.errorOccurred.emit(f"cannot stage decoded ENC2 audio: {exc}")
                return False
        source = source.resolve()
        self._playback_source = source
        self.player.setSource(QUrl.fromLocalFile(str(source)))
        return True

    def toggle(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek(self, milliseconds: int) -> None:
        position = max(0, milliseconds)
        self.player.setPosition(position)
        self._position_changed(position)

    def _ensure_aud_directory(self) -> QTemporaryDir | None:
        if self._aud_directory is not None and self._aud_directory.isValid():
            return self._aud_directory
        directory = QTemporaryDir("stepnx-audio-XXXXXX")
        if not directory.isValid():
            self.errorOccurred.emit("cannot create temporary directory for decoded ENC2 audio")
            return None
        directory.setAutoRemove(True)
        self._aud_directory = directory
        return directory

    def cleanup_aud_staging(self) -> bool:
        directory = self._aud_directory
        if directory is None:
            return True
        self.player.stop()
        self.player.setSource(QUrl())
        self._playback_source = None
        self._position_timer.stop()
        self._position_clock.invalidate()
        self._aud_directory = None
        return bool(directory.remove())

    def load_metronome(self, path: str | Path | None) -> None:
        self.metronome.stop()
        self.metronome.setSource(
            QUrl() if path is None else QUrl.fromLocalFile(str(Path(path).resolve()))
        )

    def play_metronome(self) -> bool:
        if self.metronome.source().isEmpty() or not self.metronome.isLoaded():
            return False
        self.metronome.stop()
        self.metronome.play()
        return True

    def _position_changed(self, milliseconds: int) -> None:
        self._position_anchor = int(milliseconds)
        self._position_clock.restart()
        self._emit_position(self._position_anchor)

    def _emit_position(self, milliseconds: int) -> None:
        milliseconds = int(milliseconds)
        if milliseconds != self._last_emitted_position:
            self._last_emitted_position = milliseconds
            self.positionChanged.emit(milliseconds)

    def _poll_position(self) -> None:
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        estimate = self._position_anchor
        if self._position_clock.isValid():
            estimate += self._position_clock.elapsed()
        duration = self.player.duration()
        if duration > 0:
            estimate = min(estimate, duration)
        self._emit_position(estimate)

    def _duration_changed(self, milliseconds: int) -> None:
        self.durationChanged.emit(int(milliseconds))

    def _playback_state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        if playing:
            self._position_anchor = int(self.player.position())
            self._position_clock.restart()
            self._position_timer.start()
        else:
            self._position_timer.stop()
            self._position_changed(int(self.player.position()))
        self.playbackChanged.emit(playing)
