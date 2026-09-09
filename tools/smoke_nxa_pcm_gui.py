#!/usr/bin/env python3
"""Exercise NXA PCM integration in the complete GUI without an audio device.

Run from the repository root with the GUI extra installed and, on Linux,
QT_QPA_PLATFORM=offscreen. Uses only the original generated audio/NX fixtures.
"""
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QMainWindow, QApplication
from stepnx.gui.phase10_app import main
from stepnx.authoring import create_authoring_snapshot
from stepnx.codecs.nx20 import parse_bytes
from tests.fixture_factory import make_normal_nx20
from tests.unit.test_pcm_gui import _Sink, QtAudio
from stepnx.gui.phase10_timeline import Phase10TimelineWidget

windows=[]
original_show=QMainWindow.show
fixture=Path('tests/fixtures/audio/generated.mp3').resolve()
def show(window,*args,**kwargs):
 if window.windowTitle()=='StepNX Studio': windows.append(window)
 return original_show(window,*args,**kwargs)
def exercise(app):
 w=windows[0]
 try:
  w._load_audio(fixture)
  assert w.audio_transport.canonical_pcm is not None
  snapshot=create_authoring_snapshot(parse_bytes(make_normal_nx20(),source='generated.NX'))
  w._set_metronome_snapshot(snapshot)
  w.metronome_enabled.setChecked(True)
  w.metronome_mode_actions['beat'].trigger()
  w.audio_offset.setValue(7)
  w.audio_transport.pcm_prepare_playback()
  assert w.audio_transport._pcm_playback._click_configuration is not None
  timeline=Phase10TimelineWidget(snapshot)
  w.tabs.addTab(timeline,'Generated transport regression')
  w.tabs.setCurrentWidget(timeline)
  w.follow_audio_action.setChecked(True)
  for error in (QtAudio.Error.NoError, QtAudio.Error.UnderrunError):
   playback=w.audio_transport._pcm_playback
   sink=_Sink()
   sink.start_error=error
   playback._sink=sink
   with patch.object(w,'_selected_chart_time',return_value=0.0), patch.object(timeline,'set_playback_time',wraps=timeline.set_playback_time) as updates:
    w._toggle_audio_playback()
    assert w.audio_playing and playback.playing and sink.running
    assert w.audio_play.text()=='Pause'
    initial=playback.position_frames
    sink.processed=100_000
    playback._poll()
    assert w.audio_position.value()==(initial+4800)*1000//48000
    assert updates.call_args.kwargs['follow'] is True
    w._toggle_audio_playback()
    assert not w.audio_playing and not playback.playing and not sink.running
    assert w.audio_play.text()=='Play'
    assert sink.starts==1, 'Pause must not restart the sink'
    assert playback.position_frames==initial+4800
  w._selected_profile=lambda:'fiesta2'
  w.profile_actions['fiesta2'].triggered[bool].emit(False)
  assert w.audio_transport.canonical_pcm is None
  assert w.audio_transport.playback_source==fixture
  w._selected_profile=lambda:'nxa-native'
  w.profile_actions['nxa-native'].triggered[bool].emit(False)
  assert w.audio_transport.canonical_pcm is not None
  assert w.audio_transport.original_source==fixture
  for _ in range(5): app.processEvents()
  print('PASS full GUI load, offset, metronome mode, play/follow/pause with normal and underrun starts, profile round trip')
 finally:
  w.audio_transport.cleanup_aud_staging()
  w.close()
 return 0
with patch.object(QMainWindow,'show',show),patch.object(QApplication,'exec',exercise):
 raise SystemExit(main(['--profile','nxa-native']))
