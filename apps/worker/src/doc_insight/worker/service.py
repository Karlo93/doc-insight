"""Sequential stream consumer; durable persistence precedes acknowledgement."""

import logging
from collections.abc import Callable
from threading import Event
from time import monotonic

from doc_insight.contracts.streams import StreamConsumer, StreamMessage, WorkerEvent
from doc_insight.observability import extract, stage
from doc_insight.worker.processing import DocumentProcessor, StorageUnavailable
from doc_insight.worker.settings import Settings
from opentelemetry.context import attach, detach
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy.exc import InterfaceError, OperationalError, TimeoutError

STREAM = "di:documents"
DLQ = "di:documents:dlq"
TRANSIENT = (StorageUnavailable, OperationalError, InterfaceError, TimeoutError)
logger = logging.getLogger(__name__)


class Worker:
    """Process stream deliveries sequentially and acknowledge durable outcomes.

    Transient storage failures stay pending for reclaim. Invalid/terminal work
    uses the dead-letter path; current-version completed documents are replay-safe.
    Heartbeats signal progress at loop boundaries, not from a background thread.
    """

    def __init__(
        self,
        stream: StreamConsumer,
        processor: DocumentProcessor,
        settings: Settings,
        consumer: str,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.stream, self.processor, self.settings = stream, processor, settings
        self.consumer, self.clock = consumer, clock
        self.stopping = Event()
        self.ready = False
        self.next_reclaim = 0.0
        self.cursor = "0-0"

    def dead_letter(self, message: StreamMessage, error: str, attempts: int) -> None:
        """Persist a terminal delivery to the dead-letter stream before acknowledging it."""
        # A crash between these calls may duplicate a DLQ entry, but cannot lose it.
        self.stream.xadd(DLQ, dict(message.fields, error=error, attempts=str(attempts)))
        self.stream.xack(STREAM, self.settings.worker_group, message.id)
        logger.warning("message_id=%s status=failed attempts=%d", message.id, attempts)

    def handle(self, message: StreamMessage) -> None:
        """Validate one pending delivery and scope its parent trace to this attempt."""
        attempts = self.stream.xpending(STREAM, self.settings.worker_group, message.id)
        if not attempts:
            return
        try:
            event = WorkerEvent.model_validate(message.fields)
        except ValidationError:
            self.dead_letter(message, "ValidationError: invalid event", attempts)
            return
        token = attach(extract(message.fields))
        try:
            self._handle_valid(message, event, attempts)
        except TRANSIENT as error:
            logger.warning(
                "message_id=%s status=pending error_class=%s",
                message.id,
                type(error).__name__,
            )
        finally:
            detach(token)

    def _handle_valid(
        self, message: StreamMessage, event: WorkerEvent, attempts: int
    ) -> None:
        """Check replay and retry limits, then acknowledge only a durable outcome."""
        try:
            document = self.processor.lookup(event)
        except TRANSIENT:
            raise
        except (LookupError, ValueError) as error:
            self.dead_letter(
                message, f"{type(error).__name__}: invalid document reference", attempts
            )
            return
        if self.processor.completed(document):
            # Replay after a successful commit must succeed even past the delivery limit.
            self.stream.xack(STREAM, self.settings.worker_group, message.id)
            return
        if attempts > self.settings.worker_max_attempts:
            self._fail(
                message, event, "DeliveryLimit: retry budget exhausted", attempts
            )
            return
        try:
            with stage("process"):
                self.processor.process(event, document)
        except TRANSIENT:
            raise
        except Exception as error:  # noqa: BLE001 - provider failures must become poison messages.
            self._fail(
                message, event, f"{type(error).__name__}: processing failed", attempts
            )
            return
        self.stream.xack(STREAM, self.settings.worker_group, message.id)
        logger.info("document_id=%s status=processed", event.document_id)

    def _fail(
        self, message: StreamMessage, event: WorkerEvent, error: str, attempts: int
    ) -> None:
        self.processor.repository.mark_status(
            event.tenant_id, event.document_id, "failed", error
        )
        self.dead_letter(message, error, attempts)

    def _reclaim(self) -> list[StreamMessage]:
        """Advance the pending-entry scan; schedule cooldown only when the cursor wraps."""
        self.cursor, messages = self.stream.xautoclaim(
            STREAM,
            self.settings.worker_group,
            self.consumer,
            self.settings.worker_claim_min_idle_ms,
            self.cursor,
            self.settings.worker_batch,
        )
        # An empty page can still have a continuation cursor; keep scanning next pass.
        if self.cursor == "0-0":
            self.next_reclaim = self.clock() + self.settings.worker_reclaim_seconds
        return messages

    def run_once(self) -> None:
        """Reclaim idle work before new deliveries and stop between document attempts."""
        if self.stopping.is_set():
            return
        if not self.ready:
            self.stream.xgroup_create(STREAM, self.settings.worker_group)
            self.ready = True
        self.stream.heartbeat(self.consumer)
        messages = []
        if self.cursor != "0-0" or self.clock() >= self.next_reclaim:
            messages = self._reclaim()
        if not messages:
            messages = self.stream.xreadgroup(
                STREAM,
                self.settings.worker_group,
                self.consumer,
                self.settings.worker_batch,
                self.settings.worker_block_ms,
            )
        for message in messages:
            if self.stopping.is_set():
                break
            self.stream.heartbeat(self.consumer)
            self.handle(message)
        self.stream.heartbeat(self.consumer)

    def run(self) -> None:
        """Keep consuming with interruptible backoff when queue or storage is unavailable."""
        while not self.stopping.is_set():
            try:
                self.run_once()
            except (RedisError, *TRANSIENT) as error:
                self.ready = False
                logger.warning(
                    "status=unavailable error_class=%s", type(error).__name__
                )
                self.stopping.wait(min(self.settings.worker_reclaim_seconds, 5))
