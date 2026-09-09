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
  w._set_metronome_snapshot(create_authoring_snapshot(parse_bytes(make_normal_nx20(),source='generated.NX')))
  w.metronome_enabled.setChecked(True)
  w.metronome_mode_actions['beat'].trigger()
  w.audio_offset.setValue(7)
  w.audio_transport.pcm_prepare_playback()
  assert w.audio_transport._pcm_playback._click_configuration is not None
  w._selected_profile=lambda:'fiesta2'
  w.profile_actions['fiesta2'].triggered[bool].emit(False)
  assert w.audio_transport.canonical_pcm is None
  assert w.audio_transport.playback_source==fixture
  w._selected_profile=lambda:'nxa-native'
  w.profile_actions['nxa-native'].triggered[bool].emit(False)
  assert w.audio_transport.canonical_pcm is not None
  assert w.audio_transport.original_source==fixture
  for _ in range(5): app.processEvents()
  print('PASS full GUI load, offset, metronome mode, profile round trip')
 finally:
  w.audio_transport.cleanup_aud_staging()
  w.close()
 return 0
with patch.object(QMainWindow,'show',show),patch.object(QApplication,'exec',exercise):
 raise SystemExit(main(['--profile','nxa-native']))
