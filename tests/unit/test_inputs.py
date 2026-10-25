import gzip
import io
import sys
from pathlib import Path

import pytest

from querylens.errors import InputError
from querylens.inputs import display_name, open_lines


def test_reads_plain_file_and_normalizes_crlf(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_bytes(b"one\r\ntwo\nthree")
    assert list(open_lines(str(path))) == ["one", "two", "three"]


def test_gzip_detected_by_magic_bytes_not_extension(tmp_path: Path) -> None:
    path = tmp_path / "plain-name.log"
    path.write_bytes(gzip.compress(b"alpha\nbeta\n"))
    assert list(open_lines(str(path))) == ["alpha", "beta"]


def test_non_gzip_with_gz_extension_is_read_as_text(tmp_path: Path) -> None:
    path = tmp_path / "fake.gz"
    path.write_bytes(b"hello\n")
    assert list(open_lines(str(path))) == ["hello"]


def test_invalid_utf8_is_replaced(tmp_path: Path) -> None:
    path = tmp_path / "bad.log"
    path.write_bytes(b"caf\xe9 \xff\n")
    assert list(open_lines(str(path))) == ["caf� �"]


def test_missing_file_raises_input_error(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="cannot read"):
        open_lines(str(tmp_path / "nope.log"))


def test_directory_raises_input_error(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="cannot read"):
        open_lines(str(tmp_path))


def test_truncated_gzip_raises_input_error(tmp_path: Path) -> None:
    path = tmp_path / "cut.gz"
    path.write_bytes(gzip.compress(b"x\n" * 5000)[:-20])
    with pytest.raises(InputError, match="truncated"):
        list(open_lines(str(path)))


def test_corrupt_gzip_raises_input_error(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.gz"
    path.write_bytes(b"\x1f\x8b" + b"not really gzip data at all")
    with pytest.raises(InputError, match="cannot read"):
        list(open_lines(str(path)))


def test_stdin_plain_and_gzip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"a\nb\n")))
    assert list(open_lines("-")) == ["a", "b"]
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(gzip.compress(b"c\nd\n"))))
    assert list(open_lines("-")) == ["c", "d"]


def test_display_name() -> None:
    assert display_name("-") == "<stdin>"
    assert display_name("x.log") == "x.log"
