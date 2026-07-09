from __future__ import annotations

from pathlib import Path


DOCUMENTS_DIR = Path("data") / "documents"
SUPPORTED_EXTENSIONS = {".txt", ".md", ".py", ".json", ".csv"}
SYSTEM_FILE_NAMES = {
    ".gitkeep",
    ".gitignore",
    "desktop.ini",
    "thumbs.db",
}


def get_documents_dir(project_root: Path) -> Path:
    return project_root / DOCUMENTS_DIR


def _is_supported_file(path: Path) -> bool:
    return (
        path.is_file()
        and not path.name.startswith(".")
        and path.name.lower() not in SYSTEM_FILE_NAMES
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode document: {path.name}")


def list_documents(project_root: Path) -> list[dict]:
    documents_dir = get_documents_dir(project_root)
    documents_dir.mkdir(parents=True, exist_ok=True)

    documents: list[dict] = []

    for path in sorted(documents_dir.iterdir()):
        if not _is_supported_file(path):
            continue

        documents.append({
            "name": path.name,
            "path": str(path.relative_to(project_root)),
            "extension": path.suffix.lower(),
            "size": path.stat().st_size,
        })

    return documents


def read_document(project_root: Path, filename: str) -> dict:
    documents_dir = get_documents_dir(project_root)
    documents_dir.mkdir(parents=True, exist_ok=True)

    if not filename or not filename.strip():
        raise ValueError("Document filename is required.")

    requested = Path(filename.strip())

    if requested.is_absolute() or ".." in requested.parts or requested.name != filename.strip():
        raise ValueError("Invalid document filename. Use a file name inside data\\documents.")

    extension = requested.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported document format: {extension or '(none)'}")

    document_path = (documents_dir / requested.name).resolve()
    documents_root = documents_dir.resolve()

    if document_path.parent != documents_root:
        raise ValueError("Invalid document filename. Use a file name inside data\\documents.")

    if not document_path.exists() or not document_path.is_file():
        raise FileNotFoundError(f"Document not found: {requested.name}")

    return {
        "name": document_path.name,
        "extension": document_path.suffix.lower(),
        "content": _read_text(document_path),
        "size": document_path.stat().st_size,
    }
