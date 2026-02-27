# -*- mode: python ; coding: utf-8 -*-
import sys

a = Analysis(
    ['kvanet_vpn.py'],
    pathex=[],
    binaries=[],
    datas=[],  # сюда можно добавить файлы, например 'icon.ico'
    hiddenimports=[
        'PIL._tkinter_finder',  # для Pillow
        'customtkinter.windows.widgets.theme',
        'requests.packages.urllib3.packages.six.moves',
        'psutil._psutil_linux' if sys.platform.startswith('linux') else 'psutil._psutil_osx',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='kvanet-vpn',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,      # оставляем консоль для логов, можно убрать если не нужно
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico'    # если есть иконка
)
