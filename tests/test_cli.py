import json
import subprocess
import sys
from pathlib import Path

import pytest
from doc_insight.testing.embedding import FakeEmbedder
from doc_insight.testing.structure import FakeTokenizer
from doc_insight.worker import cli
from doc_insight.worker.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_text_cli_does_not_import_the_embedding_runtime() -> None:
    # Plain extraction must stay usable without importing or initializing the embedding runtime.
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import doc_insight.worker.cli; assert 'onnxruntime' not in sys.modules",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


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


@pytest.mark.parametrize("as_json", [False, True])
def test_analyze_cli_reports_language_entities_and_chunks(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], as_json: bool
) -> None:
    monkeypatch.setattr(cli, "HfTokenizer", lambda settings: FakeTokenizer())
    arguments = ["di", "analyze", str(FIXTURES / "text_hr.pdf")]
    monkeypatch.setattr("sys.argv", arguments + (["--json"] if as_json else []))
    main()
    output = capsys.readouterr().out
    if as_json:
        result = json.loads(output)
        assert result["language"] == "hr"
        assert result["entities"]
        for chunk in result["chunks"]:
            assert (
                result["pages"][0]["text"][chunk["char_start"] : chunk["char_end"]]
                == chunk["text"]
            )
    else:
        assert "Language: hr | Pages: 1" in output
        assert "Page 1 | hr | confidence=" in output
        assert "Entity | Label | Page | Count" in output
        assert "Marić" in output
        assert "Chunks: 1 | Tokens min/max:" in output


@pytest.mark.parametrize("as_json", [False, True])
def test_analyze_embed_outputs_vectors_or_metadata(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], as_json: bool
) -> None:
    monkeypatch.setattr(cli, "HfTokenizer", lambda settings: FakeTokenizer())
    monkeypatch.setattr(cli, "FastEmbedEmbedder", lambda settings: FakeEmbedder())
    args = ["di", "analyze", str(FIXTURES / "text_en.pdf"), "--embed"]
    monkeypatch.setattr("sys.argv", args + (["--json"] if as_json else []))
    main()
    output = capsys.readouterr().out
    if as_json:
        result = json.loads(output)
        assert result["embed_model"] == "fake/hash"
        assert result["embed_dimension"] == 384
        assert all(len(chunk["embedding"]) == 384 for chunk in result["chunks"])
    else:
        assert "Embeddings: 384 dimensions | fake/hash" in output
