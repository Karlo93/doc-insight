import json
import os

import httpx
import pytest
from doc_insight.query.extractive import ExtractiveGenerator
from doc_insight.query.generation import FallbackGenerator
from doc_insight.query.mistral import (
    CircuitBreaker,
    MistralGenerator,
    messages,
    parse_generation,
)
from doc_insight.query.settings import Settings
from doc_insight.testing.generation import FakeGenerator


@pytest.fixture(
    params=["fake", "extractive", pytest.param("mistral", marks=pytest.mark.external)]
)
def generator(request):
    if request.param == "fake":
        yield FakeGenerator()
    elif request.param == "extractive":
        yield ExtractiveGenerator()
    else:
        if os.environ.get("CI") or not os.environ.get("DI_LLM_API_KEY"):
            pytest.skip(
                "External contract requires an explicit key and never runs in CI"
            )
        with httpx.Client() as client:
            yield MistralGenerator(Settings(), client)


def test_generator_contract(generator):
    result = generator.generate(
        "Where does the pharmacy store vaccines?",
        ["The pharmacy stores vaccines in monitored refrigerators."],
    )
    assert result.supported
    assert result.answer.strip()
    assert result.cited_passage_indexes == [0]
    assert "refrigerators" in result.answer.lower()


@pytest.mark.parametrize("content", ["INSUFFICIENT", "  INSUFFICIENT\n"])
def test_insufficient(content):
    result = parse_generation(content, 3)
    assert (
        not result.supported and not result.answer and not result.cited_passage_indexes
    )


@pytest.mark.parametrize(
    "content",
    [
        "answer",
        "answer [0]",
        "answer [4]",
        "[1]",
        "answer [1,2]",
        "INSUFFICIENT [1]",
        "answer [-1]",
        "answer [1] [x]",
    ],
)
def test_invalid_citation_format(content):
    with pytest.raises(ValueError):
        parse_generation(content, 3)


def test_parsing_deduplicates_and_prompt_contains_only_text():
    result = parse_generation("Water [2]. Salt [1] [2]", 2)
    assert result.cited_passage_indexes == [1, 0]
    assert result.answer == "Water. Salt"
    prompt = messages("Where?", ["Here."])
    assert "INSUFFICIENT" in prompt[0]["content"]
    data = json.loads(prompt[1]["content"])
    assert data == {"question": "Where?", "passages": [{"number": 1, "text": "Here."}]}


def test_breaker_state_machine_without_sleep():
    now = [0.0]
    breaker = CircuitBreaker(2, 10, lambda: now[0])
    assert breaker.acquire()
    breaker.finish(False)
    assert breaker.acquire()
    breaker.finish(True)
    assert breaker.failures == 0
    breaker.finish(False)
    breaker.finish(False)
    assert not breaker.acquire()
    now[0] = 10
    assert breaker.acquire()
    assert not breaker.acquire()
    breaker.finish(False)
    assert not breaker.acquire()
    now[0] = 20
    assert breaker.acquire()
    breaker.finish(True)
    assert breaker.acquire() and breaker.failures == 0


@pytest.mark.parametrize(
    "failure", ["timeout", "status", "format", "json", "shape", "type"]
)
def test_http_failure_fallback_and_open_breaker(failure):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.extensions["timeout"]["read"] == 0.1
        if failure == "timeout":
            raise httpx.ReadTimeout("timeout")
        if failure == "status":
            return httpx.Response(500)
        if failure == "json":
            return httpx.Response(200, text="{")
        if failure == "shape":
            return httpx.Response(200, json={})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None if failure == "type" else "uncited answer"
                        }
                    }
                ]
            },
        )

    settings = Settings(
        llm_api_key="test", llm_breaker_failures=1, llm_timeout_seconds=0.1
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        primary = MistralGenerator(settings, client)
        generator = FallbackGenerator(primary, settings.llm_model)
        for _ in range(2):
            result, provider = generator.generate(
                "Where are vaccines?", ["Vaccines stay in refrigerators."]
            )
            assert result.supported and provider.provider == "extractive"
        assert len(calls) == 1


def test_missing_key_never_calls_http():
    def forbidden(request):
        pytest.fail("HTTP must not be called")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        generator = FallbackGenerator(
            MistralGenerator(Settings(llm_api_key=""), client)
        )
        assert generator.generate("vaccines", ["vaccines"])[1].provider == "extractive"


def test_success_reports_model_and_busy_falls_back():
    def handler(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "Vaccines are cold [1]"}}]}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        primary = MistralGenerator(Settings(llm_api_key="test"), client)
        generator = FallbackGenerator(primary, "configured-model")
        result, provider = generator.generate("vaccines", ["Vaccines are cold"])
        assert result.supported and provider.model == "configured-model"
        assert provider.provider == "mistral"
        with primary.call_lock:
            assert (
                generator.generate("vaccines", ["Vaccines are cold"])[1].provider
                == "extractive"
            )
