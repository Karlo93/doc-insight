"""Public errors are small, structured and independent of exception text."""

import json
import re

from doc_insight.contracts.gateway import UpstreamReply
from starlette.responses import JSONResponse, Response


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}}, status_code=status
    )


def upstream_response(reply: UpstreamReply) -> Response:
    if 200 <= reply.status < 300:
        return Response(
            reply.body, reply.status, headers={"content-type": reply.content_type}
        )
    if (
        400 <= reply.status < 500
        and reply.content_type.split(";")[0] == "application/json"
    ):
        try:
            payload = json.loads(reply.body)
            detail = payload["error"]
            if (
                set(payload) == {"error"}
                and set(detail) == {"code", "message"}
                and isinstance(detail["code"], str)
                and re.fullmatch(r"[a-z0-9][a-z0-9_]{0,63}", detail["code"])
                and isinstance(detail["message"], str)
                and len(detail["message"]) <= 1024
            ):
                return JSONResponse(payload, reply.status)
        except (ValueError, KeyError, TypeError):
            pass
    if reply.status == 504:
        return error(504, "upstream_timeout", "upstream timed out")
    return error(502, "bad_gateway", "upstream request failed")
