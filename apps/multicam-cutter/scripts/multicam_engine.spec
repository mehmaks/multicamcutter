# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec für multicam-engine.

Baut ein OneDir-Bundle mit allen Dependencies.
Aufruf: pyinstaller scripts/multicam_engine.spec
"""

import os
import sys
from pathlib import Path

ROOT = Path(os.path.abspath(SPECPATH)).parent.parent.parent  # resolve-toolkit root
ENGINE = ROOT / 'apps' / 'multicam-cutter' / 'engine'

block_cipher = None

# Hidden imports die PyInstaller nicht automatisch findet
hidden_imports = [
    # Toolkit-Module
    'modules.multicam_cutter.run_from_bin',
    'modules.multicam_cutter.build_aaf',
    'modules.multicam_cutter.add_reactions_to_edl',
    'modules.multicam_cutter.build_base_edl_from_audio',
    'modules.multicam_cutter.video_reaction_analyzer_v2_4',
    'modules.multicam_cutter.pause_trim_edl',
    'modules.multicam_cutter.build_fcpxml',
    'shared.waveform_sync',
    'shared.frame_utils',
    'shared.ffmpeg_utils',
    'shared.aaf_builder',
    'licensing.license',

    # Lizenz: Remote-Validierung (HTTP) + Signaturprüfung (Ed25519)
    'requests',
    'cryptography',
    'cryptography.hazmat.primitives.asymmetric.ed25519',
    'cryptography.hazmat.backends.openssl',

    # MediaPipe
    'mediapipe',
    'mediapipe.python',
    'mediapipe.python.solutions',
    'mediapipe.tasks',
    'mediapipe.tasks.c',
    'mediapipe.tasks.metadata',
    'mediapipe.tasks.python',
    'mediapipe.tasks.python.vision',
    'mediapipe.tasks.python.core',
    'mediapipe.tasks.python.components',

    # PyTorch (CPU)
    'torch',
    'torch.nn',
    'torch.nn.functional',
    'torchaudio',

    # CLIP / Transformers
    'transformers',
    'transformers.models.clip',

    # Audio
    'soundfile',

    # AAF
    'aaf2',

    # Numerisch
    'numpy',
    'scipy',
    'scipy.signal',
    'scipy.fft',

    # OpenCV
    'cv2',

    # Pillow
    'PIL',
    'PIL.Image',
]

# Daten die mitgebundlet werden müssen
datas = [
    # MediaPipe Modell
    (str(ROOT / 'modules' / 'multicam_cutter' / 'face_landmarker.task'), 'modules/multicam_cutter'),
    # Nodding Patterns Config
    (str(ROOT / 'config' / 'nodding_patterns.json'), 'config'),
    # CLIP Ignore Prompts
    (str(ROOT / 'config' / 'clip_ignore_prompts.json'), 'config'),
    # Licensing — NUR license.py (enthaelt den PUBLIC Key) + __init__.py.
    # NIEMALS license_private.key / keygen.py / keysign.py / licenses/ bundlen —
    # der Lizenz-Private-Key wuerde sonst mit jeder App ausgeliefert und
    # koennte zum Faelschen beliebiger Lizenzen genutzt werden!
    (str(ROOT / 'licensing' / 'license.py'), 'licensing'),
    (str(ROOT / 'licensing' / '__init__.py'), 'licensing'),
    # Protocol module
    (str(ENGINE / 'protocol.py'), 'engine'),
]

# Toolkit-Quellcode als Daten einbinden (werden via sys.path importiert)
for subdir in ['modules/multicam_cutter', 'shared']:
    src = ROOT / subdir
    if src.exists():
        datas.append((str(src), subdir))

# MediaPipe native library
import mediapipe as _mp
_mp_dir = os.path.dirname(_mp.__file__)
_mp_dylib = os.path.join(_mp_dir, 'tasks', 'c', 'libmediapipe.dylib')
_mp_binaries = [(_mp_dylib, 'mediapipe/tasks/c')] if os.path.exists(_mp_dylib) else []

a = Analysis(
    [str(ENGINE / 'multicam_engine.py')],
    pathex=[str(ROOT)],
    binaries=_mp_binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Nicht benötigt — spart Platz
        'streamlit',
        'notebook',
        'jupyter',
        'tkinter',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='multicam-engine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX kann Probleme mit signed binaries machen
    console=True,  # CLI-Tool, kein GUI
    target_arch='arm64',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='multicam-engine',
)
