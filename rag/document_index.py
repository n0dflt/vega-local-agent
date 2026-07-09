from __future__ import annotations

import json
from pathlib import Path

from rag.document_chunker import chunk_text
from rag.document_loader import list_documents, read_document


INDEX_PATH = Path("data") / "index" / "documents_index.json"
INDEX_VERSION = "v0.7.0"


def _get_index_path(project_root: Path) -> Path:
    return project_root / INDEX_PATH


def build_documents_index(project_root: Path) -> dict:
    index_path = _get_index_path(project_root)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    documents = []
    chunks_count = 0

    for item in list_documents(project_root):
        document = read_document(project_root, item["name"])
        chunks = chunk_text(document["content"])
        chunks_count += len(chunks)

        documents.append({
            "name": document["name"],
            "extension": document["extension"],
            "size": document["size"],
            "chunks": chunks,
        })

    index = {
        "version": INDEX_VERSION,
        "documents_count": len(documents),
        "chunks_count": chunks_count,
        "documents": documents,
    }

    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return index


def load_documents_index(project_root: Path) -> dict | None:
    index_path = _get_index_path(project_root)

    if not index_path.exists():
        return None

    return json.loads(index_path.read_text(encoding="utf-8"))
