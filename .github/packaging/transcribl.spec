# This spec is owned by the desktop-build workflow, not a local build command.
import os
import platform
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('Desktop distributions are built by GitHub Actions only.')
expected = {'darwin': 'arm64', 'win32': 'AMD64'}
if sys.platform not in expected or platform.machine().lower() != expected[sys.platform].lower():
    raise SystemExit('Supported build hosts: macOS ARM64 and Windows x64.')
root = Path(SPECPATH).resolve().parents[1]
datas = [(str(root / 'config' / 'default.toml'), 'config')]
binaries = []
hiddenimports = []
for package in ('nicegui', 'webview', 'markitdown', 'magika', 'pypdfium2'):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports
datas += collect_data_files('transcribl')
datas += copy_metadata('markitdown')
hiddenimports += ['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto',
                  'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on']
a = Analysis(
    [str(root / 'src' / 'transcribl' / 'executable.py')],
    pathex=[str(root / 'src')], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[], excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='Transcribl',
    debug=False, strip=False, upx=False, console=True,
    target_arch='arm64' if sys.platform == 'darwin' else None,
)
folder = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Transcribl')
if sys.platform == 'darwin':
    app = BUNDLE(
        folder, name='Transcribl.app', bundle_identifier='org.transcribl.desktop',
        info_plist={'NSHighResolutionCapable': True, 'CFBundleDisplayName': 'Transcribl'},
    )
