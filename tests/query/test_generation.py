import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
from doc_insight.query.breaker import CircuitBreaker
from doc_insight.query.extractive import ExtractiveGenerator
from doc_insight.query.generation import FallbackGenerator
from doc_insight.query.openai_provider import (
    OpenAIGenerator,
    ProviderFailure,
    answer_schema,
    parse_response,
)
from doc_insight.query.settings import Settings
from doc_insight.testing.generation import FakeGenerator
from doc_insight.testing.usage import InMemoryUsageLedger


def response(answer="Vaccines stay in refrigerators.", indexes=None, supported=True):
    return {
        "status": "completed",
        "usage": {
            "input_tokens": 120,
            "output_tokens": 30,
            "input_tokens_details": {"cached_tokens": 20},
        },
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "answer": answer,
                                "supported": supported,
                                "cited_passage_indexes": [0]
                                if indexes is None
                                else indexes,
                            }
                        ),
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize("generator", [FakeGenerator(), ExtractiveGenerator()])
def test_local_generator_contract(generator):
    result = generator.generate(
        "Where does the pharmacy store vaccines?",
        ["The pharmacy stores vaccines in monitored refrigerators."],
    )
    assert result.supported and "refrigerators" in result.answer.lower()
    assert result.cited_passage_indexes == [0]


@pytest.mark.parametrize("indexes", [[-1], [2], []])
def test_invalid_citations_preserve_billable_usage(indexes):
    with pytest.raises(ProviderFailure) as failure:
        parse_response(response(indexes=indexes), 1, "request-1")
    assert failure.value.usage.total == 150


def test_refusal_and_incomplete_preserve_usage():
    for kind in ("refusal", "incomplete"):
        data = response()
        if kind == "refusal":
            data["output"][0]["content"] = [{"type": "refusal", "refusal": "no"}]
        else:
            data["status"] = "incomplete"
        with pytest.raises(ProviderFailure) as error:
            parse_response(data, 1, "request-1")
        assert error.value.usage.total == 150


def test_unsupported_is_not_fallback():
    result = parse_response(response("", [], False), 1, None)
    assert not result.supported and result.answer == ""


def test_breaker_ignores_stale_calls_and_allows_one_probe():
    now = [0.0]
    breaker = CircuitBreaker(1, 10, lambda: now[0])
    first = breaker.acquire()
    old = breaker.acquire()
    breaker.finish(first, False)
    breaker.finish(old, True)
    assert breaker.acquire() is None
    now[0] = 10
    probe = breaker.acquire()
    assert probe is not None and breaker.acquire() is None
    breaker.finish(old, True)
    assert breaker.acquire() is None
    breaker.finish(probe, True)
    assert breaker.acquire() is not None


@pytest.mark.parametrize("failure", ["timeout", "status", "json", "shape"])
def test_http_failure_fallback_and_breaker(failure):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private error")
        if failure == "status":
            return httpx.Response(500)
        if failure == "json":
            return httpx.Response(200, text="{")
        return httpx.Response(200, json={})

    settings = Settings(openai_api_key="test", llm_breaker_failures=1)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        generator = FallbackGenerator(
            OpenAIGenerator(settings, client), settings.openai_model
        )
        for _ in range(2):
            result, info = generator.generate(
                "vaccines", ["Vaccines stay in refrigerators."]
            )
            assert result.supported and info.provider == "extractive"
        assert len(calls) == 1


def test_success_schema_and_usage():
    def handler(request):
        data = json.loads(request.content)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert data["store"] is False and data["max_output_tokens"] == 700
        assert data["text"]["format"]["strict"] is True
        assert data["text"]["format"]["schema"]["properties"]["cited_passage_indexes"][
            "items"
        ]["enum"] == [0]
        assert "tenant" not in data["input"]
        return httpx.Response(
            200, json=response(), headers={"x-request-id": "request-1"}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        primary = OpenAIGenerator(
            Settings(openai_api_key="test", llm_concurrency=1), client
        )
        generator = FallbackGenerator(primary, "configured-model")
        result, info = generator.generate(
            "vaccines", ["Vaccines stay in refrigerators."]
        )
        assert result.supported
        assert info.provider == "openai" and info.model == "configured-model"
        assert info.usage.input_tokens == 120 and info.usage.cached_input_tokens == 20
        with primary.slots:
            assert (
                generator.generate("vaccines", ["vaccines"])[1].fallback_reason
                == "busy"
            )


def test_citation_schema_is_request_local_and_never_allows_nonexistent_indexes():
    five = answer_schema(5)
    one = answer_schema(1)

    def indexes(schema):
        return schema["properties"]["cited_passage_indexes"]["items"]["enum"]

    assert indexes(five) == [0, 1, 2, 3, 4]
    assert indexes(one) == [0]
    assert indexes(five) == [0, 1, 2, 3, 4]
    with pytest.raises(ValueError):
        answer_schema(0)


def test_concurrent_calls_are_allowed_up_to_limit():
    entered, release = Event(), Event()

    def handler(request):
        entered.set()
        assert release.wait(3)
        return httpx.Response(200, json=response())

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        ThreadPoolExecutor(2) as pool,
    ):
        primary = OpenAIGenerator(
            Settings(openai_api_key="test", llm_concurrency=2), client
        )
        first = pool.submit(
            primary.generate, "vaccines", ["Vaccines stay in refrigerators."]
        )
        assert entered.wait(3)
        second = pool.submit(
            primary.generate, "vaccines", ["Vaccines stay in refrigerators."]
        )
        release.set()
        assert first.result().supported and second.result().supported


def test_no_key_no_http():
    def handler(request):
        pytest.fail("must not call HTTP")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        primary = OpenAIGenerator(Settings(openai_api_key=""), client)
        assert (
            FallbackGenerator(primary)
            .generate("vaccines", ["vaccines"])[1]
            .fallback_reason
            == "disabled"
        )


@pytest.mark.parametrize(
    "usage",
    [
        {},
        {"input_tokens": 10},
        [],
        {"input_tokens": -1, "output_tokens": 2},
        {"input_tokens": 10, "output_tokens": 2, "input_tokens_details": [1]},
    ],
)
def test_malformed_usage_falls_back_and_charges_unknown_reservation(usage):
    data = response()
    data["usage"] = usage
    ledger = InMemoryUsageLedger(20_000)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))
    ) as client:
        primary = OpenAIGenerator(Settings(openai_api_key="test"), client)
        result, info = FallbackGenerator(primary, "model", ledger).generate(
            "vaccines", ["Vaccines stay in refrigerators."], tenant="demo"
        )
    assert result.supported and info.provider == "extractive"
    assert info.fallback_reason == "invalid_usage" and info.usage is None
    summary = ledger.summary("demo")
    assert summary["charged_tokens"] > 8192 and summary["reserved_tokens"] == 0


def test_null_optional_usage_details_preserves_known_totals():
    data = response()
    data["usage"]["input_tokens_details"] = None
    assert parse_response(data, 1, None).usage.total == 150


@pytest.mark.parametrize("data", [None, [], {"status": "completed", "output": [None]}])
def test_invalid_response_shape_is_provider_failure(data):
    with pytest.raises(ProviderFailure, match="invalid_output"):
        parse_response(data, 1, None)
