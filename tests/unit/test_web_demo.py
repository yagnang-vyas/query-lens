"""The browser demo's glue code must produce exactly what the CLI produces."""

from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests" / "golden"
SAMPLES = ("postgres-sample", "mysql-slow-sample")


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"web_{name}", ROOT / "web" / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bridge = _load("bridge")
build = _load("build")


@pytest.fixture
def log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "input.log"
    monkeypatch.setattr(bridge, "LOG_PATH", str(path))
    return path


@pytest.mark.parametrize("sample", SAMPLES)
def test_analyze_matches_golden_report(sample: str, log_path: Path) -> None:
    log_path.write_bytes((ROOT / "examples" / f"{sample}.log").read_bytes())
    result = bridge.analyze({"top": 100})
    expected = json.loads((GOLDEN / f"{sample}.json").read_text(encoding="utf-8"))
    got = json.loads(result["json"])
    assert got["fingerprints"] == expected["fingerprints"]
    assert got["summary"] == expected["summary"]
    assert result["code"] == 0
    assert result["text"].startswith("QueryLens")
    assert result["markdown"].lstrip().startswith("#")


def test_analyze_reports_unparseable_input(log_path: Path) -> None:
    log_path.write_text("not a log\n", encoding="utf-8")
    result = bridge.analyze({})
    assert result["code"] == 2
    assert str(log_path) not in result["stderr"]
    assert "json" in result
    assert "markdown" not in result


def test_analyze_applies_gates_and_clamps_top(log_path: Path) -> None:
    log_path.write_bytes((ROOT / "examples" / "postgres-sample.log").read_bytes())
    result = bridge.analyze({"top": 99999, "failOverMs": "1", "failOnHint": "QL004"})
    assert result["code"] == 1
    assert "p95 exceeded" in result["stderr"]
    assert json.loads(result["json"])["summary"]["top"] == bridge.MAX_TOP


def test_analyze_rejects_bad_option_values(log_path: Path) -> None:
    log_path.write_bytes((ROOT / "examples" / "postgres-sample.log").read_bytes())
    assert bridge.analyze({"failOnHint": "NOPE"})["code"] == 2


def test_build_assembles_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build, "DIST", tmp_path / "dist")
    monkeypatch.delenv("QUERYLENS_PYODIDE_DIR", raising=False)
    dist = build.build()
    for name in (*build.PAGE_FILES, "config.json", "querylens.zip", "samples/postgres-sample.log"):
        assert (dist / name).is_file(), name
    config = json.loads((dist / "config.json").read_text(encoding="utf-8"))
    assert config["pyodideBase"] == build.PYODIDE_CDN
    with zipfile.ZipFile(dist / "querylens.zip") as archive:
        names = archive.namelist()
    assert "querylens/cli.py" in names
    assert not any("__pycache__" in name for name in names)
