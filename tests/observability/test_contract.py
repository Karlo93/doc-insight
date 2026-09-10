import pytest
from doc_insight.contracts.telemetry import StageObserver
from doc_insight.testing.telemetry import FakeStageObserver


@pytest.mark.parametrize("provider", ["fake", "sdk"])
@pytest.mark.parametrize("fails", [False, True])
def test_stage_observer_contract(provider, fails, telemetry):
    # The same observer contract applies to the production helper and deterministic fake.
    instance, exporter, _ = telemetry
    fake = FakeStageObserver()
    observer: StageObserver = fake if provider == "fake" else instance
    calls = []
    error = RuntimeError("private data")
    try:
        with observer.stage("extract") as value:
            assert value is None
            calls.append("ran")
            if fails:
                raise error
    except RuntimeError as raised:
        assert raised is error
    assert calls == ["ran"]
    if provider == "fake":
        assert fake.completed == [("extract", "failed" if fails else "processed")]
    else:
        spans = exporter.get_finished_spans()
        assert len(spans) == 1 and spans[0].name == "extract"
        assert spans[0].status.status_code.name == ("ERROR" if fails else "UNSET")
