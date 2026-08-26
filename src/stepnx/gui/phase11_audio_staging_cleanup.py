from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QUrl

from stepnx.gui.audio_transport import AudioTransport


def _cleanup_aud_staging_retryable(transport) -> bool:
    """Release QMediaPlayer and remove staged AUD data without losing retry state."""

    directory = transport._aud_directory
    if directory is None:
        return True

    transport.player.stop()
    transport.player.setSource(QUrl())
    transport._playback_source = None
    transport._position_timer.stop()
    transport._position_clock.invalidate()

    removed = bool(directory.remove())
    if removed:
        transport._aud_directory = None
    return removed


def install_phase11_audio_staging_transport() -> None:
    """Make AUD temporary-directory cleanup retryable before transports exist."""

    if getattr(AudioTransport, "_phase11_retryable_aud_cleanup_installed", False):
        return
    AudioTransport._phase11_retryable_aud_cleanup_installed = True
    AudioTransport.cleanup_aud_staging = _cleanup_aud_staging_retryable


def _release_waveform_source(decoder) -> None:
    """Drop QAudioDecoder's source so Windows releases the staged MP3 handle."""

    decoder.decoder.stop()
    decoder.decoder.setSource(QUrl())
    decoder._source = None


def install_phase11_audio_staging_cleanup(window) -> None:
    """Coordinate waveform and transport teardown for staged AUD playback."""

    if getattr(window, "_phase11_audio_staging_cleanup_installed", False):
        return
    decoder = getattr(window, "phase11_waveform_decoder", None)
    if decoder is None:
        return
    window._phase11_audio_staging_cleanup_installed = True

    original_stop = decoder.stop

    def stop_and_release() -> None:
        original_stop()
        decoder.decoder.setSource(QUrl())
        decoder._source = None

    decoder.stop = stop_and_release

    # Qt signals are synchronous here. These callbacks therefore run after the
    # waveform result/error has been fully assembled by QtWaveformDecoder and
    # can safely release the source file immediately.
    decoder.waveformReady.connect(lambda _waveform: _release_waveform_source(decoder))
    decoder.failed.connect(lambda _message: _release_waveform_source(decoder))

    application = QCoreApplication.instance()
    if application is None:
        return

    def shutdown_cleanup() -> None:
        # On Windows QAudioDecoder may keep decoded-N.mp3 open. Release that
        # handle first, then retry the transport directory removal. The
        # transport cleanup deliberately retains QTemporaryDir on failure so a
        # later retry can still remove it.
        decoder.stop()
        window.audio_transport.cleanup_aud_staging()

    window._phase11_audio_staging_shutdown_cleanup = shutdown_cleanup
    application.aboutToQuit.connect(shutdown_cleanup)
