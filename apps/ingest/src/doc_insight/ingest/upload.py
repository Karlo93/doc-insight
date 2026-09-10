"""Bounded multipart parsing: reject before object storage or database writes."""

from hashlib import sha256
from typing import BinaryIO

from fastapi import HTTPException, Request
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header


class UploadBody:
    def __init__(self, target: BinaryIO, limit: int) -> None:
        self.target, self.limit = target, limit
        self.size = 0
        self.digest = sha256()
        self.prefix = b""
        self.filename = ""
        self.headers: dict[bytes, bytes] = {}
        self.field = b""
        self.value = b""
        self.parts = 0
        self.complete = False

    def part_begin(self) -> None:
        self.parts += 1
        if self.parts != 1:
            raise HTTPException(400, "Expected one file field")

    def header_field(self, data: bytes, start: int, end: int) -> None:
        self.field += data[start:end].lower()
        self._bound_headers()

    def header_value(self, data: bytes, start: int, end: int) -> None:
        self.value += data[start:end]
        self._bound_headers()

    def _bound_headers(self) -> None:
        if len(self.field) + len(self.value) > 8192 or len(self.headers) > 16:
            raise HTTPException(400, "Multipart headers too large")

    def header_end(self) -> None:
        self.headers[self.field] = self.value
        self.field = self.value = b""

    def headers_finished(self) -> None:
        _, options = parse_options_header(self.headers.get(b"content-disposition", b""))
        if options.get(b"name") != b"file" or b"filename" not in options:
            raise HTTPException(400, "Expected a multipart file field")
        self.filename = options[b"filename"].decode("utf-8", errors="replace")

    def part_data(self, data: bytes, start: int, end: int) -> None:
        self.size += end - start
        if self.size > self.limit:
            raise HTTPException(413, "Upload exceeds the configured limit")
        block = data[start:end]
        self.prefix = (self.prefix + block[:8])[:8]
        self.digest.update(block)
        self.target.write(block)

    def finish(self) -> None:
        self.complete = True

    async def read(self, request: Request) -> None:
        kind, options = parse_options_header(request.headers.get("content-type", ""))
        boundary = options.get(b"boundary", b"")
        if kind != b"multipart/form-data" or not 1 <= len(boundary) <= 200:
            raise HTTPException(400, "Expected multipart/form-data with a boundary")
        parser = MultipartParser(
            boundary,
            {
                "on_part_begin": self.part_begin,
                "on_header_field": self.header_field,
                "on_header_value": self.header_value,
                "on_header_end": self.header_end,
                "on_headers_finished": self.headers_finished,
                "on_part_data": self.part_data,
                "on_end": self.finish,
            },
        )
        total = 0
        async for block in request.stream():
            total += len(block)
            if total > self.limit + 16384:
                raise HTTPException(413, "Upload exceeds the configured limit")
            parser.write(block)
        parser.finalize()
        if not self.complete or self.parts != 1:
            raise HTTPException(400, "Incomplete multipart upload")
        self.target.seek(0)
