"""Provider-free packaged CLI/resource/server smoke test on each native CI host."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from pypdf import PdfWriter


def main() -> None:
    executable = Path(sys.argv[1]).resolve()
    with TemporaryDirectory(prefix="transcribl-smoke-") as directory:
        root = Path(directory)
        environment = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
        environment.update(LOCALAPPDATA=directory)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config = root / "config.toml"
        source = Path("config/default.toml").read_text(encoding="utf-8")
        source = source.replace('artifacts_dir = "../artifacts"', 'artifacts_dir = "artifacts"')
        source = source.replace("port = 8000", f"port = {port}")
        source = source.replace("open_browser_on_start = true", "open_browser_on_start = false")
        config.write_text(source, encoding="utf-8")
        command = [str(executable), "--config", str(config)]
        subprocess.run([str(executable), "--help"], check=True, env=environment, timeout=90)
        subprocess.run([*command, "show-config"], check=True, env=environment, timeout=90)
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        pdf = root / "synthetic.pdf"
        writer.write(pdf)
        subprocess.run([*command, "ingest", str(pdf)], check=True, env=environment, timeout=180)
        with (root / "server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([*command, "serve"], env=environment, stdout=log, stderr=log)
            try:
                for _ in range(120):
                    if process.poll() is not None:
                        raise RuntimeError("Packaged desktop server exited before startup")
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/", timeout=2
                        ) as response:
                            html = response.read().decode()
                        assert "nicegui" in html.lower()
                        assert "Transcribl" in html
                        break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(0.5)
                else:
                    raise RuntimeError("Packaged desktop server did not start")
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/backend/api/config", timeout=5
                ) as response:
                    assert response.status == 200
                    assert response.headers["Cache-Control"] == "no-store"
                # Nested editor modules and styles must survive PyInstaller collection.
                for asset in ("editor/index.js", "editor/review.js", "styles/workspace.css"):
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/editor-assets/{asset}", timeout=5
                    ) as response:
                        assert response.status == 200
                        assert response.read()
                        assert response.headers["Cache-Control"] == "no-store"

            finally:
                process.terminate()
                process.wait(timeout=30)
                print((root / "server.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
