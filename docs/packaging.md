# Desktop packaging

Distribution builds run only in GitHub Actions. Open **Actions → Desktop builds →
Run workflow**, or push a change/PR to trigger `.github/workflows/desktop-build.yml`.
The former local `compile` build entry point is removed. `transcribl compile`
still compiles canonical translation data into document projections.

| Target | Native runner | Download | Launch |
| --- | --- | --- | --- |
| macOS ARM64 | `macos-15` | `Transcribl-macos-arm64.zip` | `Transcribl.app` |
| Windows x64 | `windows-2025` | `Transcribl-windows-x64.zip` | `Transcribl/Transcribl.exe` |

Extract the entire download. Windows needs the adjacent runtime files, not just
the EXE. The Windows executable remains console-capable to retain CLI use. On
macOS, invoke `Transcribl.app/Contents/MacOS/Transcribl --help` for CLI commands.
No arguments open the NiceGUI native desktop window.

The workflow uses locked uv environments, runs formatting, lint, type, unit,
integration and fake-provider tests, and builds with the Actions-owned
`.github/packaging/transcribl.spec`. That spec checks `GITHUB_ACTIONS` and the
native CPU/OS before calling PyInstaller; there is no cross-compilation or Linux
build. GitHub retains successful ZIP artifacts for 14 days. It does not publish
releases automatically.

The resource allowlist includes application package data, NiceGUI's local JS/CSS,
pywebview, prompts, the checked-in default TOML, MarkItDown/Magika and PDFium.
It does not collect a checkout directory wholesale. `.env`, `.provider-keys`,
personal TOML, PDFs, canonical runs, and review data are never build inputs.
`multiprocessing.freeze_support()` executes before GUI imports in the frozen
entrypoint. This is necessary for NiceGUI's native window subprocess.

The packages are currently unsigned and not notarized. Windows requires the
Microsoft Edge WebView2 Runtime; macOS uses its system WebKit. Reviewed PDF export
requires an external XeLaTeX installation visible to the configured
`pdf_export.latex_engine`. Other export formats require no TeX installation.

## Persistent runtime paths

| Platform | Data root |
| --- | --- |
| macOS | `~/Library/Application Support/Transcribl` |
| Windows | `%LOCALAPPDATA%/Transcribl` |

The app refreshes `config/default.toml` from bundled defaults atomically, preserves
`config/personal.local.toml`, and retains existing `artifacts/`, glossary catalog,
`.env` and `.provider-keys`. Personal TOML must add the new `[desktop]` section;
strict validation does not invent missing settings. Upgrading the app does not
rewrite PDFs, canonical runs or editorial revisions.

## Verification boundary

Each workflow tests the built executable's CLI, synthetic PDF extraction (including
bundled render/extraction dependencies), NiceGUI HTML page and safe configuration
API. The smoke test uses temporary config/data and strips provider keys from the
child process. No provider call is made.

A passing CI smoke test does not establish live provider behavior, native window
rendering/download dialogs, code signing, or recipient-machine compatibility.
Those need validation on the two actual desktop targets. Source development uses
`uv run app` for native mode or `uv run transcribl serve` for browser mode; neither
command builds a distribution.

Framework and runner references: [NiceGUI native packaging](https://nicegui.io/documentation/section_configuration_deployment),
[GitHub runner architectures](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
