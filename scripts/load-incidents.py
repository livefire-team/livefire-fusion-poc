"""Creates (or updates) the AI Search index `incidents` and loads <corpus>/*.json.

The incidents are the agents' test material and live outside this public repo (ADR-004): pass the incidents folder
of a private checkout with --corpus, or set INCIDENT_CORPUS.

Usage:
  python scripts/load-incidents.py --endpoint https://<search>.search.windows.net --corpus <folder> [--dry-run]
      [--embedding-endpoint https://<foundry>.cognitiveservices.azure.com --embedding-deployment text-embedding-3-small]
  python scripts/load-incidents.py --endpoint ... --forget-drills
      delete every finding earlier drills wrote (kind drill-finding), for a clean evaluation run

Earlier drills add their findings to this index (the learning loop, the Drill Runner's KNOWLEDGE=search), so the
next drill's Planner can find them. Reloading the curated corpus keeps those findings; --forget-drills removes them.

With an embedding deployment, the index is hybrid (blueprint 4.1): each record also stores a vector of its title,
summary and resolution, and the index's Azure OpenAI vectorizer embeds each query through the search service's own
managed identity. Without one, the index stays keyword-only (BM25), the documented fallback.

Signs in with your Azure CLI login (needs Search Service Contributor and Search Index Data
Contributor on the service). Set SEARCH_ADMIN_KEY to use the admin key instead, for example in a
lab where you can't assign data-plane roles.
"""
import argparse
import json
import os
from pathlib import Path

from azure.core.credentials import AzureKeyCredential
from azure.identity import AzureCliCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    AzureOpenAIVectorizer, AzureOpenAIVectorizerParameters, HnswAlgorithmConfiguration, SearchableField, SearchField,
    SearchFieldDataType, SearchIndex, SimpleField, VectorSearch, VectorSearchProfile,
)

INDEX = "incidents"
VECTOR_FIELD = "content_vector"
DIMENSIONS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072, "text-embedding-ada-002": 1536}


def index_definition(embedding_endpoint: str = "", embedding_deployment: str = "",
                     embedding_model: str = "text-embedding-3-small") -> SearchIndex:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SimpleField(name="kind", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="service", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="occurred_at", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SearchableField(name="summary", type=SearchFieldDataType.String),
        SearchableField(name="resolution", type=SearchFieldDataType.String),
        SimpleField(name="source", type=SearchFieldDataType.String),
    ]
    if not embedding_deployment:
        return SearchIndex(name=INDEX, fields=fields)
    fields.append(SearchField(name=VECTOR_FIELD, type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                              searchable=True, retrievable=False, vector_search_dimensions=DIMENSIONS[embedding_model],
                              vector_search_profile_name="vec"))
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
        profiles=[VectorSearchProfile(name="vec", algorithm_configuration_name="hnsw", vectorizer_name="aoai")],
        # No api_key and no auth_identity: the search service calls the model with its system-assigned identity.
        vectorizers=[AzureOpenAIVectorizer(vectorizer_name="aoai", parameters=AzureOpenAIVectorizerParameters(
            resource_url=embedding_endpoint, deployment_name=embedding_deployment, model_name=embedding_model))],
    )
    return SearchIndex(name=INDEX, fields=fields, vector_search=vector_search)


def embed_text(doc: dict) -> str:
    return "\n".join(str(doc.get(k, "")) for k in ("title", "summary", "resolution"))


def embed(docs: list[dict], endpoint: str, deployment: str) -> None:
    """Adds the vector to each record, signing in to Azure OpenAI with your Azure CLI login (no keys)."""
    from azure.identity import get_bearer_token_provider
    from openai import AzureOpenAI
    token = get_bearer_token_provider(AzureCliCredential(), "https://cognitiveservices.azure.com/.default")
    client = AzureOpenAI(azure_endpoint=endpoint, azure_ad_token_provider=token, api_version="2024-10-21")
    vectors = client.embeddings.create(model=deployment, input=[embed_text(d) for d in docs]).data
    for doc, item in zip(docs, vectors):
        doc[VECTOR_FIELD] = item.embedding


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--corpus", default=os.environ.get("INCIDENT_CORPUS", ""),
                        help="folder of incident JSON files (default: INCIDENT_CORPUS)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--embedding-endpoint", default=os.environ.get("OPENAI_ENDPOINT", ""))
    parser.add_argument("--embedding-deployment", default=os.environ.get("EMBEDDING_DEPLOYMENT", ""))
    parser.add_argument("--embedding-model", default="text-embedding-3-small", choices=sorted(DIMENSIONS))
    parser.add_argument("--forget-drills", action="store_true", help="delete the findings earlier drills wrote")
    args = parser.parse_args()

    if args.forget_drills:
        key = os.environ.get("SEARCH_ADMIN_KEY")
        client = SearchClient(args.endpoint, INDEX, AzureKeyCredential(key) if key else AzureCliCredential())
        learned = [{"id": d["id"]} for d in client.search(search_text="*", filter="kind eq 'drill-finding'", select=["id"])]
        if learned:
            client.delete_documents(learned)
        print(f"forgot {len(learned)} drill findings")
        return

    corpus = Path(args.corpus) if args.corpus else None
    if corpus is None or not corpus.is_dir():
        parser.error("--corpus (or INCIDENT_CORPUS) must name the incidents folder of the private corpus")
    docs = [json.loads(p.read_text()) for p in sorted(corpus.glob("*.json"))]
    definition = index_definition(args.embedding_endpoint, args.embedding_deployment, args.embedding_model)
    mode = "hybrid" if args.embedding_deployment else "keyword-only (BM25)"
    if args.dry_run:
        print(f"index {definition.name}, {mode}: {[f.name for f in definition.fields]}")
        print(f"{len(docs)} documents: {[d['id'] for d in docs]}")
        return

    key = os.environ.get("SEARCH_ADMIN_KEY")
    credential = AzureKeyCredential(key) if key else AzureCliCredential()
    if args.embedding_deployment:
        embed(docs, args.embedding_endpoint, args.embedding_deployment)
    SearchIndexClient(args.endpoint, credential).create_or_update_index(definition)
    results = SearchClient(args.endpoint, INDEX, credential).merge_or_upload_documents(docs)
    failed = [r.key for r in results if not r.succeeded]
    print(f"loaded {len(docs) - len(failed)} of {len(docs)} documents, {mode}" + (f"; failed: {failed}" if failed else ""))


if __name__ == "__main__":
    main()
