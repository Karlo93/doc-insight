from pathlib import Path
from unittest.mock import Mock

import pytest
from doc_insight.worker import pipeline, store_cli

from .conftest import measurements


@pytest.mark.parametrize("failure", [None, "extract", "analyze", "embed", "store"])
def test_index_telemetry_preserves_pipeline_order_and_cli_durations(
    telemetry, monkeypatch, capsys, failure
):
    # Instrumentation must preserve processing order and the CLI's existing timing contract.
    operations = [Mock() for _ in range(4)]
    if failure:
        operations[
            ["extract", "analyze", "embed", "store"].index(failure)
        ].side_effect = ValueError("private")
    for name, operation in zip(("extract", "analyze", "embed_document"), operations):
        monkeypatch.setattr(pipeline, name, operation)
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


def test_worker_attaches_event_trace_and_restores_ambient_context(telemetry):
    from uuid import uuid4

    from doc_insight.contracts.ingest import DocumentUploaded
    from doc_insight.observability import stage
    from doc_insight.testing.streams import InMemoryStreamConsumer
    from doc_insight.worker.service import STREAM, Worker
    from doc_insight.worker.settings import Settings
    from opentelemetry import trace

    event = DocumentUploaded(
        tenant_id="demo",
        document_id=uuid4(),
        sha256="a" * 64,
        object_key="demo/" + "a" * 64,
        media_type="application/pdf",
        size_bytes=10,
        traceparent="00-" + "1" * 32 + "-" + "2" * 16 + "-01",
    )
    stream = InMemoryStreamConsumer()
    processor = Mock()
    processor.completed.return_value = False
    worker = Worker(stream, processor, Settings(), "test-1")
    stream.xadd(STREAM, event.stream_fields())
    with stage("ambient"):
        ambient = trace.get_current_span().get_span_context()
        worker.run_once()
        assert trace.get_current_span().get_span_context() == ambient
    spans = telemetry[1].get_finished_spans()
    processed = next(span for span in spans if span.name == "process")
    assert processed.context.trace_id == int("1" * 32, 16)
    assert processed.parent.span_id == int("2" * 16, 16)
    assert processed.parent.is_remote
