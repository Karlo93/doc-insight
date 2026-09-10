"""Upload ordering, with all persistence supplied through contracts."""

from typing import BinaryIO

from doc_insight.contracts.ingest import ObjectStore
from doc_insight.contracts.storage import DocumentRepository
from doc_insight.ingest.upload import UploadBody
from doc_insight.observability import stage
from doc_insight.worker.extraction import media_type


def register(
    tenant: str,
    upload: UploadBody,
    stream: BinaryIO,
    repository: DocumentRepository,
    objects: ObjectStore,
) -> dict[str, str]:
    """Store an upload, then register its document and outbox atomically in SQL.

    Existing tenant/hash pairs return their ID without another event. The object
    write is outside SQL, so failed registration can leave an orphan object.
    """
    kind = media_type(upload.prefix)
    digest = upload.digest.hexdigest()
    if previous := repository.find_by_sha256(tenant, digest):
        return {
            "document_id": str(previous.id),
            "sha256": digest,
            "status": "duplicate",
        }
    key = f"{tenant}/{digest}"
    with stage("upload.storage"):
        objects.put(key, stream, upload.size, kind)
    with stage("upload.register"):
        record = repository.register_upload(
            tenant,
            upload.filename,
            digest,
            kind,
            upload.size,
            key,
        )
    return {"document_id": str(record.id), "sha256": digest, "status": record.status}
