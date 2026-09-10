from uuid import uuid4

import pytest


def test_upload_registration_status_and_processing(repository, document):
    # Registration and processing are separate states; an accepted upload is not yet searchable.
    tenant = uuid4().hex
    record = repository.register_upload(
        tenant,
        "a.pdf",
        document.sha256,
        "application/pdf",
        123,
        f"{tenant}/{document.sha256}",
    )
    assert record.status == "uploaded" and record.page_count is None
    assert record.processed_at is None and record.error is None
    assert repository.find_by_sha256(tenant, document.sha256) == record
    assert repository.find_by_sha256("other", document.sha256) is None
    assert (
        repository.register_upload(
            tenant,
            "renamed.pdf",
            document.sha256,
            "application/pdf",
            123,
            record.object_key,
        )
        == record
    )
    for status, error in (
        ("processing", None),
        ("failed", "DecodeError: invalid input"),
        ("processing", None),
    ):
        repository.mark_status(tenant, record.id, status, error)
        loaded = repository.get_document(tenant, record.id)
        assert loaded.status == status and loaded.error == error
    with pytest.raises(LookupError):
        repository.mark_status("other", record.id, "failed", "test")
    processed = repository.upsert_document(tenant, "a.pdf", document)
    assert processed.id == record.id and processed.status == "processed"
    assert processed.size_bytes == 123 and processed.object_key == record.object_key
    assert processed.processed_at is not None and processed.error is None
    assert processed.page_count == 1
    with pytest.raises(ValueError):
        repository.mark_status(tenant, record.id, "invalid")
