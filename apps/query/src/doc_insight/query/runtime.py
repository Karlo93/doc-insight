"""Process-owned clients; unavailable storage leaves process health accessible."""

from threading import Lock

import httpx
from doc_insight.query.generation import FallbackGenerator
from doc_insight.query.openai_provider import OpenAIGenerator
from doc_insight.query.service import QueryService
from doc_insight.query.settings import Settings
from doc_insight.query.usage import PostgresUsageLedger
from doc_insight.worker.embedder import FastEmbedEmbedder
from doc_insight.worker.repository import PostgresRepository
from sqlalchemy import create_engine, text


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = create_engine(
            settings.database_url,
            hide_parameters=True,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
        )
        self.client = httpx.Client(follow_redirects=False, trust_env=False)
        self.ledger = PostgresUsageLedger(self.engine, settings.llm_daily_tokens)
        self.embedder = FastEmbedEmbedder(settings)
        self.service: QueryService | None = None
        self.lock = Lock()

    def get_service(self) -> QueryService:
        with self.lock:
            if self.service is None:
                primary = (
                    OpenAIGenerator(self.settings, self.client)
                    if self.settings.api_key()
                    else None
                )
                self.service = QueryService(
                    PostgresRepository(self.engine),
                    self.embedder,
                    FallbackGenerator(
                        primary,
                        self.settings.openai_model,
                        self.ledger,
                        self.settings.llm_max_output_tokens,
                    ),
                    self.settings,
                )
            return self.service

    def ready(self) -> None:
        self.get_service()
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        self.embedder.embed_query("readiness")

    def close(self) -> None:
        self.client.close()
        self.engine.dispose()
