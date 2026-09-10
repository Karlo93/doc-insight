from uuid import UUID

from doc_insight.contracts.query import QueryFilter
from doc_insight.query.retrieval import named_scope


def test_filename_scope_tolerates_typo_and_ignores_unrelated_document():
    # A misspelled document reference should narrow retrieval without favoring unrelated files.
    diagram, overview = UUID(int=1), UUID(int=2)
    names = [
        (diagram, "doc-insight-architecture-v2_1.png"),
        (overview, "platform-tech-overview.pdf"),
    ]
    scope = named_scope(
        "what tech stack is in 'woker' in arhitecture diagram", names, QueryFilter()
    )
    assert scope.document_ids == [diagram]


def test_name_resolution_never_overrides_explicit_filter_or_language():
    names = [(UUID(int=1), "architecture.png")]
    for ids in ([], [UUID(int=2)]):
        requested = QueryFilter(document_ids=ids, language="hr")
        assert named_scope("architecture", names, requested) == requested
    assert (
        named_scope("architecture", names, QueryFilter(language="hr")).language == "hr"
    )


def test_no_name_match_keeps_library_search_and_multiple_names_are_supported():
    names = [(UUID(int=1), "architecture.png"), (UUID(int=2), "operations.pdf")]
    requested = QueryFilter()
    assert (
        named_scope("What is the capital of Atlantis?", names, requested) == requested
    )
    assert named_scope(
        "Compare architecture and operations", names, requested
    ).document_ids == [UUID(int=1), UUID(int=2)]


def test_names_outside_tenant_cannot_be_inferred():
    assert named_scope("architecture", [], QueryFilter()).document_ids is None
