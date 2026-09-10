"""Validate ownership and object integrity before invoking expensive providers."""

from contextlib import closing
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from botocore.exceptions import BotoCoreError, ClientError
from doc_insight.contracts.extraction import PIPELINE_VERSION
from doc_insight.contracts.ingest import ObjectStore
from doc_insight.contracts.storage import DocumentRepository, StoredDocument
from doc_insight.contracts.streams import WorkerEvent
from doc_insight.worker.extraction import media_type
from doc_insight.worker.pipeline import Pipeline


class StorageUnavailable(Exception):
    """An object operation can be retried without acknowledging its event."""


class MissingObject(Exception):
    """The referenced object no longer exists."""


def download(store: ObjectStore, event: WorkerEvent, path: Path) -> None:
    digest, size = sha256(), 0
    try:
        with closing(store.get(event.object_key)) as source, path.open("wb") as target:
            while data := source.read(1024 * 1024):
                size += len(data)
                if size > event.size_bytes:
                    raise ValueError("Object size mismatch")
                digest.update(data)
                target.write(data)
    except ClientError as error:
        if error.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
            raise MissingObject from None
        raise StorageUnavailable from None
    except (BotoCoreError, OSError) as error:
        raise StorageUnavailable from error
    except KeyError:
        raise MissingObject from None
    if size != event.size_bytes or digest.hexdigest() != event.sha256:
        raise ValueError("Object integrity mismatch")
    with path.open("rb") as source:
        if media_type(source.read(8)) != event.media_type:
            raise ValueError("Object media type mismatch")


class DocumentProcessor:
    def __init__(
        self, repository: DocumentRepository, objects: ObjectStore, pipeline: Pipeline
    ) -> None:
        self.repository, self.objects, self.pipeline = repository, objects, pipeline

    def lookup(self, event: WorkerEvent) -> StoredDocument:
        document = self.repository.get_document(event.tenant_id, event.document_id)
        if document is None:
            raise LookupError("Document not found for tenant")
        if (
            document.sha256,
            document.object_key,
            document.media_type,
            document.size_bytes,
        ) != (event.sha256, event.object_key, event.media_type, event.size_bytes):
            raise ValueError("Event does not match document")
        return document

    @staticmethod
    def completed(document: StoredDocument) -> bool:
        return (
            document.status == "processed"
            and document.pipeline_version == PIPELINE_VERSION
        )

    def process(self, event: WorkerEvent, document: StoredDocument) -> None:
        self.repository.mark_status(event.tenant_id, event.document_id, "processing")
        with TemporaryDirectory(prefix="di-worker-") as directory:
            path = Path(directory) / "original"
            download(self.objects, event, path)
            self.pipeline.index(
                path, event.tenant_id, self.repository, document.filename
            )
        self.repository.mark_status(event.tenant_id, event.document_id, "processed")
