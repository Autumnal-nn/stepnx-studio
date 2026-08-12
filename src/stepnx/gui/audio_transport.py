from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QObject, QTemporaryDir, QTimer, QUrl, Signal
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
        self._aud_directory = QTemporaryDir("stepnx-aud-XXXXXX")
        self._aud_serial = 0
        self._position_anchor = 0
        self._last_emitted_position = -1
        self._position_clock = QElapsedTimer()
        self._position_timer = QTimer(self)
        self._position_timer.setInterval(16)
        self._position_timer.timeout.connect(self._poll_position)
        # QMediaPlayer exposes both values as qlonglong.  PySide 6.11 refuses
        # to connect those signals directly to our Python ``Signal(int)``;
        # route them through callables so the values are normalized before
        # they are re-emitted.
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._playback_state)
        self.player.errorOccurred.connect(
            lambda error, message: self.errorOccurred.emit(message or str(error))
        )

    def load(self, path: str | Path | None) -> bool:
        self.player.stop()
        self.player.setSource(QUrl())
        self._position_timer.stop()
        self._position_clock.invalidate()
        self._position_anchor = 0
        self._last_emitted_position = -1
        if path is None:
            return True
        source = Path(path)
        if source.suffix.casefold() == ".aud":
            try:
                payload = decode_enc2_aud(source)
            except AudDecodeError as exc:
                self.errorOccurred.emit(str(exc))
                return False
            if not self._aud_directory.isValid():
                self.errorOccurred.emit("cannot create temporary directory for decoded AUD")
                return False
            self._aud_serial += 1
            source = Path(self._aud_directory.path()) / f"decoded-{self._aud_serial}.mp3"
            try:
                source.write_bytes(payload)
            except OSError as exc:
                self.errorOccurred.emit(f"cannot stage decoded AUD: {exc}")
                return False
        self.player.setSource(QUrl.fromLocalFile(str(source.resolve())))
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
