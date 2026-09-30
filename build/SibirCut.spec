# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['../launcher.py'],
    pathex=['..'],
    binaries=[],
    datas=[('../THIRD_PARTY_NOTICES.md','.'),('../LICENSE.txt','.')],
    hiddenimports=['sibir_cut.selftest','sibir_cut.app'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SibirCut',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='../assets/SibirCut.ico',
)
