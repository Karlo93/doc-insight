from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import pytest
from doc_insight.ingest.main import create_app
from doc_insight.ingest.runtime import Resources
from doc_insight.ingest.settings import Settings
from doc_insight.testing.ingest import InMemoryObjectStore
from doc_insight.testing.storage import InMemoryRepository
from fastapi.testclient import TestClient

PDF = b"%PDF-1.7\nfixture"


@pytest.fixture
def clients():
    repository, objects = InMemoryRepository(384), InMemoryObjectStore()
    settings = Settings(s3_access_key="test", s3_secret_key="test", max_upload_bytes=32)
    resources = Resources(repository, objects, lambda: None, lambda: None)
    with TestClient(
        create_app(resources, settings), raise_server_exceptions=False
    ) as client:
        yield client, repository, objects


def post(client, data=PDF, tenant="demo"):
    return client.post(
        "/ingest",
        files={"file": ("private.pdf", data)},
        headers={"X-Tenant-Id": tenant},
    )


def test_upload_duplicate_and_tenant_read(clients, monkeypatch):
    client, repository, objects = clients
    response = post(client)
    assert response.status_code == 202
    saved = response.json()
    assert saved["sha256"] == sha256(PDF).hexdigest()
    assert saved["status"] == "uploaded"
    assert objects.objects[f"demo/{saved['sha256']}"] == PDF
    assert len(repository.events) == 1
    event = repository.events[0]
    assert str(event.document_id) == saved["document_id"] and event.size_bytes == len(
        PDF
    )
    monkeypatch.setattr(
        objects, "put", lambda *args: pytest.fail("duplicate writes storage")
    )
    assert post(client).json() == {**saved, "status": "duplicate"}
    assert len(repository.events) == 1
    path = f"/documents/{saved['document_id']}"
    found = client.get(path, headers={"X-Tenant-Id": "demo"}).json()
    assert found == {
        "document_id": saved["document_id"],
        "status": "uploaded",
        "filename": "private.pdf",
        "page_count": None,
        "language": None,
        "pipeline_version": None,
        "created_at": event.occurred_at.isoformat().replace("+00:00", "Z"),
        "processed_at": None,
        "error": None,
    }
    assert client.get(path, headers={"X-Tenant-Id": "other"}).status_code == 404
    assert client.get(path).status_code == 400


@pytest.mark.parametrize(
    "data,status", [(b"text", 415), (b"", 415), (PDF * 3, 413), (b"x" * 17000, 413)]
)
def test_invalid_upload_has_no_writes(clients, data, status):
    client, repository, objects = clients
    response = post(client, data)
    assert response.status_code == status
    assert set(response.json()) == {"error"}
    assert not objects.objects and not repository.documents and not repository.events


@pytest.mark.parametrize(
    "signature", [b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"II*\x00", b"MM\x00*"]
)
def test_supported_magic_bytes_ignore_filename(clients, signature):
    assert post(clients[0], signature).status_code == 202


@pytest.mark.parametrize("tenant", ["", "bad/tenant", "a" * 65, "space tenant"])
def test_invalid_tenant(clients, tenant):
    assert post(clients[0], tenant=tenant).status_code == 400
    assert not clients[1].documents


def test_missing_header(clients):
    client, repository, objects = clients
    assert client.post("/ingest", files={"file": ("a.pdf", PDF)}).status_code == 400
    assert not repository.documents and not objects.objects


@pytest.mark.parametrize("target", ["storage", "transaction"])
def test_failure_order_and_sanitized_error(clients, monkeypatch, caplog, target):
    client, repository, objects = clients

    def fail(*args):
        raise OSError("private document text must not escape")

    monkeypatch.setattr(
        objects if target == "storage" else repository,
        "put" if target == "storage" else "register_upload",
        fail,
    )
    with caplog.at_level("WARNING", logger="doc_insight.ingest.main"):
        response = post(client)
    assert response.status_code == 503
    assert "private" not in response.text
    # Operators see the class and route; the message never reaches the log.
    assert "error=OSError" in caplog.text and "route=/ingest" in caplog.text
    assert "private" not in caplog.text
    assert not repository.documents and not repository.events
    assert bool(objects.objects) == (target == "transaction")


@pytest.mark.parametrize(
    "content,content_type",
    [
        (b"", "application/json"),
        (b"--x\r\n", "multipart/form-data; boundary=x"),
        (b"", "multipart/form-data"),
        (b"--x\r\nBroken\r\n", "multipart/form-data; boundary=x"),
    ],
)
def test_malformed_multipart(clients, content, content_type):
    response = clients[0].post(
        "/ingest",
        content=content,
        headers={"X-Tenant-Id": "demo", "Content-Type": content_type},
    )
    assert response.status_code == 400


def test_rejects_extra_and_wrong_fields(clients):
    client = clients[0]
    for files in (
        {"wrong": ("a.pdf", PDF)},
        [("file", ("a.pdf", PDF)), ("file", ("b.pdf", PDF))],
    ):
        assert (
            client.post(
                "/ingest", files=files, headers={"X-Tenant-Id": "demo"}
            ).status_code
            == 400
        )
    assert not clients[2].objects


def test_health_and_readiness(clients, monkeypatch):
    client = clients[0]
    assert (
        client.get("/healthz").status_code == client.get("/readyz").status_code == 200
    )

    def unavailable():
        raise OSError("dependency down")

    monkeypatch.setattr(client.app.state.resources, "ready", unavailable)
    assert client.get("/readyz").status_code == 503
    assert client.get("/healthz").status_code == 200
    assert (
        client.get(f"/documents/{uuid4()}", headers={"X-Tenant-Id": "demo"}).status_code
        == 404
    )
    assert (
        client.get("/documents/invalid", headers={"X-Tenant-Id": "demo"}).status_code
        == 422
    )


def test_stream_parser_handles_single_byte_fragments():
    import asyncio

    from doc_insight.ingest.upload import UploadBody
    from starlette.requests import Request

    raw = (
        b'--x\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\n\r\n'
        + PDF
        + b"\r\n--x--\r\n"
    )
    fragments = iter(raw)

    async def receive():
        value = next(fragments, None)
        return {
            "type": "http.request",
            "body": bytes([value]) if value is not None else b"",
            "more_body": value is not None,
        }

    request = Request(
        {
            "type": "http",
            "headers": [(b"content-type", b"multipart/form-data; boundary=x")],
        },
        receive,
    )
    stream = BytesIO()
    upload = UploadBody(stream, len(PDF))
    asyncio.run(upload.read(request))
    assert stream.read() == PDF and upload.prefix == PDF[:8]
    assert upload.digest.hexdigest() == sha256(PDF).hexdigest()


@pytest.mark.parametrize("repeated", [False, True])
@pytest.mark.parametrize("header_count,status", [(8, 202), (9, 400)])
def test_multipart_header_count_bound(clients, repeated, header_count, status):
    headers = [b'Content-Disposition: form-data; name="file"; filename="a.pdf"']
    headers += [
        f"X-{0 if repeated else index}: value".encode()
        for index in range(header_count - 1)
    ]
    body = b"--x\r\n" + b"\r\n".join(headers) + b"\r\n\r\n" + PDF + b"\r\n--x--\r\n"
    response = clients[0].post(
        "/ingest",
        content=body,
        headers={
            "X-Tenant-Id": "demo",
            "Content-Type": "multipart/form-data; boundary=x",
        },
    )
    assert response.status_code == status
    if status == 400:
        assert not clients[1].documents and not clients[2].objects


@pytest.mark.parametrize("repeated", [False, True])
def test_header_callbacks_enforce_limit_independently_of_parser(repeated):
    from doc_insight.ingest.upload import UploadBody
    from fastapi import HTTPException

    upload = UploadBody(BytesIO(), 32)
    for index in range(16):
        field = f"x-{0 if repeated else index}".encode()
        upload.header_field(field, 0, len(field))
        upload.header_value(b"value", 0, 5)
        upload.header_end()
    with pytest.raises(HTTPException) as caught:
        upload.header_end()
    assert caught.value.status_code == 400
