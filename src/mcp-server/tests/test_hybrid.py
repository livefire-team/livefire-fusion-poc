"""Hybrid incident retrieval: the index definition and the search tool's hybrid query, with its keyword fallback."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("load_incidents", ROOT / "scripts" / "load-incidents.py")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


def test_without_an_embedding_model_the_index_is_keyword_only():
    index = loader.index_definition()
    assert loader.VECTOR_FIELD not in [f.name for f in index.fields]
    assert index.vector_search is None


def test_with_an_embedding_model_the_index_is_hybrid_and_keyless():
    index = loader.index_definition("https://ais-x.openai.azure.com", "text-embedding-3-small")
    field = next(f for f in index.fields if f.name == loader.VECTOR_FIELD)
    assert field.vector_search_dimensions == 1536 and field.vector_search_profile_name == "vec"
    vectorizer = index.vector_search.vectorizers[0]
    assert vectorizer.parameters.deployment_name == "text-embedding-3-small"
    assert vectorizer.parameters.api_key is None                   # the search service's own identity, no keys


def test_embedding_text_covers_title_summary_and_resolution():
    assert loader.embed_text({"title": "T", "summary": "S", "resolution": "R", "id": "x"}) == "T\nS\nR"


class FakeSearch:
    def __init__(self, fail_vector=False):
        self.calls, self.fail_vector = [], fail_vector

    def search(self, **kwargs):
        self.calls.append(kwargs)
        if "vector_queries" in kwargs and self.fail_vector:
            raise RuntimeError("vectorizer unavailable")
        return iter([{"id": "EX-1", "title": "t", "@search.score": 1.0}])


def evidence(search):
    from backends.azure import AzureEvidence
    e = AzureEvidence.__new__(AzureEvidence)
    e.search = search
    return e


def test_hybrid_query_sends_keyword_and_vector_together(server, monkeypatch):
    monkeypatch.setenv("SEARCH_VECTOR_FIELD", "content_vector")
    search = FakeSearch()
    out = evidence(search).search_incidents("example query text", 3)
    call = search.calls[0]
    assert call["search_text"] == "example query text" and call["filter"] == "service eq 'order-service'"
    vq = call["vector_queries"][0]
    assert (vq.text, vq.k_nearest_neighbors, vq.fields) == ("example query text", 3, "content_vector")
    assert out == [{"id": "EX-1", "title": "t", "retrieval": "hybrid", "score": 1.0}]   # v2.2: the retrieval score


def test_vector_failure_falls_back_to_keyword_and_says_so(server, monkeypatch):
    monkeypatch.setenv("SEARCH_VECTOR_FIELD", "content_vector")
    search = FakeSearch(fail_vector=True)
    out = evidence(search).search_incidents("q", 2)
    assert "vector_queries" not in search.calls[-1] and out[0]["retrieval"] == "keyword (hybrid unavailable)"


@pytest.mark.parametrize("field", ["", None])
def test_keyword_only_when_the_index_has_no_vectors(server, monkeypatch, field):
    monkeypatch.delenv("SEARCH_VECTOR_FIELD", raising=False)
    if field is not None:
        monkeypatch.setenv("SEARCH_VECTOR_FIELD", field)
    search = FakeSearch()
    assert evidence(search).search_incidents("q", 2)[0]["retrieval"] == "keyword"
    assert "vector_queries" not in search.calls[0]


def test_fixture_search_also_finds_what_earlier_drills_learned(tmp_path, monkeypatch):
    """The learning loop on a laptop: a finding the Drill Runner wrote is found by the Planner's search tool."""
    import json as _json
    from backends.fixtures import FixtureEvidence
    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "planner.json"
    learned = {"id": "LF-drill-earlier", "kind": "drill-finding", "service": "order-service",
               "title": "LiveFire drill drill-earlier: example finding, verified",
               "summary": "A placeholder finding from an earlier drill.", "resolution": "Placeholder resolution.",
               "source": "livefire:drill-earlier/package.json"}
    (tmp_path / "LF-drill-earlier.json").write_text(_json.dumps(learned))
    e = FixtureEvidence(str(fixtures))
    monkeypatch.delenv("KNOWLEDGE_DIR", raising=False)
    assert all(r["id"] != "LF-drill-earlier" for r in e.search_incidents("placeholder finding earlier", 5))
    monkeypatch.setenv("KNOWLEDGE_DIR", str(tmp_path))
    assert e.search_incidents("placeholder finding earlier", 5)[0]["id"] == "LF-drill-earlier"
