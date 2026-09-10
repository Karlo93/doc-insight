from pathlib import Path
from unittest.mock import Mock

import pytest
from doc_insight.worker import store_cli

from .conftest import measurements


@pytest.mark.parametrize("failure", [None, "extract", "analyze", "embed", "store"])
def test_index_telemetry_preserves_pipeline_order_and_cli_durations(
    telemetry, monkeypatch, capsys, failure
):
    operations = [Mock() for _ in range(4)]
    if failure:
        operations[
            ["extract", "analyze", "embed", "store"].index(failure)
        ].side_effect = ValueError("private")
    for name, operation in zip(("extract", "analyze", "embed_document"), operations):
        monkeypatch.setattr(store_cli, name, operation)
    for name in (
        "LinguaLanguageDetector",
        "SpacyNerExtractor",
        "HfTokenizer",
        "FastEmbedEmbedder",
    ):
        monkeypatch.setattr(store_cli, name, Mock())
    repository = Mock(upsert_document=operations[3])
    if failure:
        with pytest.raises(ValueError, match="private"):
            store_cli.index_file(Path("private.pdf"), "tenant", repository)
    else:
        result = store_cli.index_file(Path("private.pdf"), "tenant", repository)
        assert result is operations[3].return_value
        operations[0].assert_called_once_with(Path("private.pdf"))
        assert operations[1].call_args.args[0] is operations[0].return_value
        assert operations[2].call_args.args[0] is operations[1].return_value
        operations[3].assert_called_once_with(
            "tenant", "private.pdf", operations[2].return_value
        )
        output = capsys.readouterr().out
        assert all(
            f"{name}=" in output for name in ("extract", "analyze", "embed", "store")
        )
    _, exporter, reader = telemetry
    names = ["extract", "analyze", "embed", "store"]
    expected = names[: names.index(failure) + 1] if failure else names
    assert [span.name for span in exporter.get_finished_spans()] == expected
    assert [
        point.attributes["stage"]
        for point in measurements(reader)["di_stage_duration_seconds"]
    ] == expected
    assert all(
        "private" not in str(span.attributes) for span in exporter.get_finished_spans()
    )
