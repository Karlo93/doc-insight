"""Process-owned clients; unavailable storage leaves process health accessible."""

from threading import Lock

import httpx
from doc_insight.query.generation import FallbackGenerator
from doc_insight.query.mistral import MistralGenerator
from doc_insight.query.service import QueryService
from doc_insight.query.settings import Settings
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
        self.client = httpx.Client()
        self.embedder = FastEmbedEmbedder(settings)
        self.service: QueryService | None = None
        self.lock = Lock()

    def get_service(self) -> QueryService:
        with self.lock:
            if self.service is None:
                primary = (
                    MistralGenerator(self.settings, self.client)
                    if (self.settings.llm_api_key.get_secret_value())
                    else None
                )
                self.service = QueryService(
                    PostgresRepository(self.engine),
                    self.embedder,
                    FallbackGenerator(primary, self.settings.llm_model),
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
