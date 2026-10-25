"""Assemble the static demo site into web/dist (standard library only).

Copies the page, zips the querylens package so Pyodide can unpack it and copies the sample logs
from examples/. Run from anywhere: ``python3 web/build.py``.

By default the browser loads Pyodide from the jsDelivr CDN. Set ``QUERYLENS_PYODIDE_DIR`` to a
local Pyodide distribution (for example ``node_modules/pyodide``) to bundle it instead, which is
how the site can be tested offline.
"""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DIST = WEB / "dist"
PACKAGE = ROOT / "src" / "querylens"
SAMPLES = ("postgres-sample.log", "mysql-slow-sample.log")
PAGE_FILES = ("index.html", "app.css", "app.js", "worker.js", "bridge.py")
PYODIDE_VERSION = "0.27.7"
PYODIDE_CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
PYODIDE_FILES = (
    "pyodide.js",
    "pyodide.asm.js",
    "pyodide.asm.wasm",
    "pyodide-lock.json",
    "python_stdlib.zip",
)


def build() -> Path:
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "samples").mkdir(parents=True)
    for name in PAGE_FILES:
        shutil.copy(WEB / name, DIST / name)
    with zipfile.ZipFile(DIST / "querylens.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PACKAGE.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                archive.write(path, Path("querylens") / path.relative_to(PACKAGE))
    for name in SAMPLES:
        shutil.copy(ROOT / "examples" / name, DIST / "samples" / name)
    pyodide_dir = os.environ.get("QUERYLENS_PYODIDE_DIR")
    base = PYODIDE_CDN
    if pyodide_dir:
        base = "pyodide/"
        (DIST / "pyodide").mkdir()
        for name in PYODIDE_FILES:
            shutil.copy(Path(pyodide_dir) / name, DIST / "pyodide" / name)
    (DIST / "config.json").write_text(json.dumps({"pyodideBase": base}) + "\n", encoding="utf-8")
    return DIST


if __name__ == "__main__":
    dist = build()
    total = sum(f.stat().st_size for f in dist.rglob("*") if f.is_file())
    print(f"built {dist} ({total} bytes)")
