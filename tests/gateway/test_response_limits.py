import httpx
import pytest
from doc_insight.gateway.http import HttpUpstream

pytestmark = pytest.mark.anyio


async def body():
    yield b""


class LargeResponse(httpx.AsyncByteStream):
    def __init__(self):
        self.closed = False
        self.sent = 0

    async def __aiter__(self):
        for _ in range(18):
            self.sent += 1
            yield b"x" * (1024 * 1024)

    async def aclose(self):
        self.closed = True


async def test_successful_response_size_is_bounded_and_closed():
    stream = LargeResponse()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=stream)
        )
    ) as client:
        reply = await HttpUpstream(client, "http://query").exchange(
            "POST", "/query", {}, body(), 5
        )
    assert reply.status == 502
    assert reply.body == b""
    assert stream.closed
    assert stream.sent == 17


async def test_missing_content_type_defaults_to_json():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"{}")
        )
    ) as client:
        reply = await HttpUpstream(client, "http://query").exchange(
            "POST", "/query", {}, body(), 5
        )
    assert reply.content_type == "application/json"
