# -*- mode: python ; coding: utf-8 -*-
import pathlib
from PyInstaller.utils.hooks import copy_metadata

block_cipher = None

project_root = pathlib.Path.cwd()
app_pkg = project_root / "aws_deployer_app"

datas = [
    (str(app_pkg / "Logo.png"), "."),
    (str(app_pkg / "Logo.icns"), "."),
]
datas += copy_metadata("boto3")
datas += copy_metadata("botocore")

hiddenimports = []

a = Analysis(
    [str(app_pkg / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AWS Deployer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(app_pkg / "Logo.icns"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AWS Deployer",
)

