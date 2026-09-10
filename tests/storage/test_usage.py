from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from doc_insight.contracts.usage import BudgetExceeded, TokenUsage
from doc_insight.query.usage import PostgresUsageLedger
from doc_insight.testing.usage import InMemoryUsageLedger


@pytest.fixture(
    params=["memory", pytest.param("postgres", marks=pytest.mark.integration)]
)
def ledger(request):
    if request.param == "memory":
        return InMemoryUsageLedger(1000)
    return PostgresUsageLedger(request.getfixturevalue("database"), 1000)


def test_atomic_concurrent_reservations(ledger):
    tenant = uuid4().hex

    def reserve(_):
        try:
            return ledger.reserve(tenant, 200, "model")
        except BudgetExceeded:
            return None

    with ThreadPoolExecutor(10) as pool:
        reservations = [key for key in pool.map(reserve, range(20)) if key]
    assert len(reservations) == 5
    assert ledger.summary(tenant)["reserved_tokens"] == 1000
    for key in reservations:
        ledger.settle(
            tenant,
            key,
            TokenUsage(input_tokens=40, output_tokens=10, cached_input_tokens=20),
            "completed",
        )
    summary = ledger.summary(tenant)
    assert summary["reserved_tokens"] == 0 and summary["charged_tokens"] == 250
    assert summary["cached_input_tokens"] == 100


def test_settlement_is_idempotent_and_tenant_scoped(ledger):
    tenant, other = uuid4().hex, uuid4().hex
    key = ledger.reserve(tenant, 300, "model")
    ledger.settle(other, key, TokenUsage(), "rejected")
    assert ledger.summary(tenant)["reserved_tokens"] == 300
    assert ledger.summary(other)["requests"] == 0
    ledger.settle(tenant, key, None, "unknown")
    ledger.settle(tenant, key, TokenUsage(), "completed")
    assert ledger.summary(tenant)["charged_tokens"] == 300
    assert ledger.summary(tenant)["reserved_tokens"] == 0


def test_unsettled_reservation_prevents_overspend(ledger):
    tenant = uuid4().hex
    ledger.reserve(tenant, 800, "model")
    with pytest.raises(BudgetExceeded):
        ledger.reserve(tenant, 201, "model")
    key = ledger.reserve(tenant, 200, "model")
    ledger.settle(tenant, key, TokenUsage(), "busy")
    assert ledger.summary(tenant)["charged_tokens"] == 0
    assert ledger.summary(tenant)["reserved_tokens"] == 800


def test_listing_is_paginated_and_scoped(repository, document):
    tenant, other = uuid4().hex, uuid4().hex
    first = repository.upsert_document(tenant, "first.pdf", document)
    repository.upsert_document(other, "hidden.pdf", document)
    second = repository.upsert_document(
        tenant, "second.pdf", document.model_copy(update={"sha256": "b" * 64})
    )
    assert [doc.id for doc in repository.list_documents(tenant, 1)] == [second.id]
    assert [doc.id for doc in repository.list_documents(tenant, 1, 1)] == [first.id]
    assert repository.list_documents(tenant, 1, 2) == []
