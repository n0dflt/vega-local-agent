from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rag.document_index import build_documents_index, load_documents_index
from rag.document_loader import get_documents_dir, list_documents, read_document


DOCUMENTS_DIR = Path("data") / "documents"
INDEX_PATH = Path("data") / "index" / "documents_index.json"
TYPO_HINTS = {
    "serch": "search",
    "searh": "search",
    "seach": "search",
    "lst": "list",
    "indx": "index",
}


def ensure_docs_paths(project_root: Path) -> tuple[Path, Path]:
    documents_dir = get_documents_dir(project_root)
    index_dir = project_root / "data" / "index"
    documents_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    return documents_dir, index_dir


def load_index_safe(project_root: Path) -> tuple[dict[str, Any], str]:
    try:
        index = load_documents_index(project_root)
        return index or {}, ""
    except (OSError, json.JSONDecodeError) as exc:
        return {}, str(exc)


def count_indexed_documents(index: dict[str, Any]) -> int | str:
    count = index.get("documents_count")
    if isinstance(count, int):
        return count

    documents = index.get("documents", [])
    if isinstance(documents, list):
        return len(documents)

    return "n/a"


def print_available_docs_commands() -> None:
    print("Available:")
    print("/docs")
    print("/docs list")
    print("/docs index")
    print("/docs search <query>")
    print("/docs read <filename>")


def print_docs_help(project_root: Path) -> None:
    ensure_docs_paths(project_root)

    print("VEGA Documents / RAG")
    print("Commands:")
    print("  /docs")
    print("  /docs list")
    print("  /docs index")
    print("  /docs search <query>")
    print("  /docs read <filename>")
    print("")
    print("Folders:")
    print("  Documents: data\\documents")
    print("  Index:     data\\index\\documents_index.json")


def docs_list(project_root: Path) -> None:
    ensure_docs_paths(project_root)
    documents = list_documents(project_root)

    if not documents:
        print("No documents found in data\\documents")
        return

    for document in documents:
        print(
            f"{document['name']} "
            f"({document['extension']}, {document['size']} bytes) - {document['path']}"
        )


def docs_index(project_root: Path) -> None:
    ensure_docs_paths(project_root)
    index = build_documents_index(project_root)

    print("Document index rebuilt")
    print(f"Documents indexed: {index.get('documents_count', 0)}")
    print(f"Chunks created: {index.get('chunks_count', 0)}")
    print("Index saved to: data\\index\\documents_index.json")


def docs_search(project_root: Path, query: str) -> None:
    query = query.strip()

    if not query:
        print("Usage: /docs search <query>")
        return

    index = load_documents_index(project_root)
    if index is None:
        print("Document index not found. Run /docs index first.")
        return

    from rag.document_search import search_documents

    results = search_documents(project_root, query=query, limit=5)

    if not results:
        print("No results found.")
        return

    for number, item in enumerate(results, start=1):
        text = " ".join(str(item.get("text", "")).split())
        if len(text) > 500:
            text = text[:497].rstrip() + "..."

        print(f"{number}. {item.get('document', 'unknown')}")
        print(f"Chunk: {item.get('chunk_id', 0)}")
        print(f"Score: {item.get('score', 0)}")
        print(text)
        print("")


def docs_read(project_root: Path, filename: str) -> None:
    filename = filename.strip()

    if not filename:
        print("Usage: /docs read <filename>")
        return

    try:
        document = read_document(project_root, filename)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc))
        return

    content = document["content"]
    print(f"# {document['name']}")
    print(f"Extension: {document['extension']}")
    print(f"Size: {document['size']} bytes")
    print("")

    if len(content) > 4000:
        print(content[:4000])
        print("[truncated]")
        return

    print(content)


def handle_docs_command(command: str, project_root: Path) -> bool:
    command = command.strip()

    if command != "/docs" and not command.startswith("/docs "):
        return False

    parts = command.split(maxsplit=2)

    if len(parts) == 1:
        print_docs_help(project_root)
        return True

    subcommand = parts[1].lower()

    if subcommand == "list":
        docs_list(project_root)
        return True

    if subcommand == "index":
        docs_index(project_root)
        return True

    if subcommand == "search":
        query = parts[2] if len(parts) >= 3 else ""
        docs_search(project_root, query)
        return True

    if subcommand == "read":
        filename = parts[2] if len(parts) >= 3 else ""
        docs_read(project_root, filename)
        return True

    if subcommand in TYPO_HINTS:
        suggestion = TYPO_HINTS[subcommand]
        suffix = " <query>" if suggestion == "search" else ""
        print(f"Unknown /docs command: {subcommand}")
        print(f"Did you mean: /docs {suggestion}{suffix}?")
        print("")
        print_available_docs_commands()
        return True

    print("Unknown /docs command.")
    print_available_docs_commands()
    return True
