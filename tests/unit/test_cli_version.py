import runpy

import pytest

from querylens import __version__
from querylens.cli import main
from querylens.errors import InputError, QueryLensError


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"querylens {__version__}"


def test_version_is_0_1_0() -> None:
    assert __version__ == "0.1.0"


def test_python_dash_m_entry_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["querylens", "--version"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("querylens", run_name="__main__")
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_input_error_is_a_querylens_error() -> None:
    assert issubclass(InputError, QueryLensError)
