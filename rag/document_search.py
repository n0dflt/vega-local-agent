from __future__ import annotations

import re
from pathlib import Path

from rag.document_index import load_documents_index


def _query_terms(query: str) -> list[str]:
    return re.findall(r"[a-zа-я0-9_#./-]+", query.lower(), flags=re.IGNORECASE)


def search_documents(project_root: Path, query: str, limit: int = 5) -> list[dict]:
    index = load_documents_index(project_root)
    if index is None:
        return []

    terms = _query_terms(query)
    if not terms:
        return []

    results: list[dict] = []

    for document in index.get("documents", []):
        document_name = document.get("name", "")

        for chunk in document.get("chunks", []):
            text = str(chunk.get("text", ""))
            normalized_text = text.lower()
            score = sum(normalized_text.count(term) for term in terms)

            if score <= 0:
                continue

            results.append({
                "document": document_name,
                "chunk_id": chunk.get("chunk_id", 0),
                "score": score,
                "text": text,
            })

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]
