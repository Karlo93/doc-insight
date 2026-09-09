import json
import subprocess
from pathlib import Path

import pytest
from doc_insight.worker.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_cli_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["di", "extract", str(FIXTURES / "text_en.pdf")])
    main()
    output = capsys.readouterr().out
    assert "Pages: 1 | application/pdf" in output
    assert "Page 1 | text_layer" in output
    assert "Alice Johnson" in output


def test_cli_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["di", "extract", str(FIXTURES / "text_hr.pdf"), "--json"]
    )
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["page_count"] == 1
    assert "Marić" in result["pages"][0]["text"]
    assert result["pages"][0]["char_count"] == len(result["pages"][0]["text"])


def test_installed_entry_point_handles_a_path_with_spaces(tmp_path: Path) -> None:
    path = tmp_path / "hrvatski dokument.pdf"
    path.write_bytes((FIXTURES / "text_hr.pdf").read_bytes())
    result = subprocess.run(
        ["di", "extract", str(path), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert "Marić" in json.loads(result.stdout)["pages"][0]["text"]
    assert result.stderr == ""


@pytest.mark.parametrize("arguments", [[], ["extract"], ["unknown"]])
def test_cli_requires_a_known_command_and_path(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["di", *arguments])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
