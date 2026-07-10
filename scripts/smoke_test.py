#!/usr/bin/env python3
from __future__ import annotations

import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "v1.4.0"


def status(label: str, ok: bool, detail: str = "") -> str:
    result = "OK" if ok else "FAIL"
    line = f"{label}: {result}"
    if detail:
        line += f" - {detail}"
    return line


def warning(label: str, detail: str = "") -> str:
    line = f"{label}: WARN"
    if detail:
        line += f" - {detail}"
    return line


def import_module(name: str) -> tuple[object | None, str]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    try:
        return importlib.import_module(name), ""
    except Exception as exc:
        return None, str(exc)


def main() -> int:
    failed = False
    lines = [
        "# VEGA smoke test",
        "",
        f"Version expected: {EXPECTED_VERSION}",
        "",
    ]

    version_module, error = import_module("scripts.version")
    version_ok = bool(version_module and getattr(version_module, "VERSION", "") == EXPECTED_VERSION)
    failed = failed or not version_ok
    lines.append(status("scripts.version", version_ok, error or getattr(version_module, "VERSION", "n/a")))

    modules = [
        "rag.document_loader",
        "rag.document_chunker",
        "rag.document_index",
        "rag.document_search",
        "rag.document_analyzer",
        "rag.supported_formats",
        "core.model_router",
    ]

    loaded = {}
    for name in modules:
        module, error = import_module(name)
        loaded[name] = module
        ok = module is not None
        failed = failed or not ok
        lines.append(status(name, ok, error))

    documents_dir = ROOT / "data" / "documents"
    try:
        documents_dir.mkdir(parents=True, exist_ok=True)
        lines.append(status("data/documents", True))
    except OSError as exc:
        failed = True
        lines.append(status("data/documents", False, str(exc)))

    smoke_file = documents_dir / "smoke_test.md"
    try:
        smoke_file.write_text(
            "\n".join([
                "# Smoke Test Document",
                "",
                "VEGA smoke document analysis test.",
                "TODO: update smoke coverage when new document commands are added.",
                "This file contains smoke keyword data for search.",
                "",
            ]),
            encoding="utf-8",
        )
        lines.append(status("write smoke_test.md", True))
    except OSError as exc:
        failed = True
        lines.append(status("write smoke_test.md", False, str(exc)))

    try:
        index = loaded["rag.document_index"].build_documents_index(ROOT)
        ok = index.get("documents_count", 0) >= 1 and index.get("chunks_count", 0) >= 1
        failed = failed or not ok
        lines.append(status("build_documents_index", ok))
    except Exception as exc:
        failed = True
        lines.append(status("build_documents_index", False, str(exc)))

    try:
        results = loaded["rag.document_search"].search_documents(ROOT, "smoke")
        ok = len(results) >= 1
        failed = failed or not ok
        lines.append(status("search_documents", ok, f"results={len(results)}"))
    except Exception as exc:
        failed = True
        lines.append(status("search_documents", False, str(exc)))

    try:
        analysis = loaded["rag.document_analyzer"].analyze_document(ROOT, "smoke_test.md")
        ok = analysis.get("words", 0) > 0
        failed = failed or not ok
        lines.append(status("analyze_document", ok))
    except Exception as exc:
        failed = True
        lines.append(status("analyze_document", False, str(exc)))

    try:
        summary = loaded["rag.document_analyzer"].summarize_document(ROOT, "smoke_test.md")
        ok = len(summary.get("summary", [])) >= 1
        failed = failed or not ok
        lines.append(status("summarize_document", ok))
    except Exception as exc:
        failed = True
        lines.append(status("summarize_document", False, str(exc)))

    try:
        answer = loaded["rag.document_analyzer"].ask_documents(ROOT, "VEGA")
        ok = isinstance(answer, dict) and "chunks" in answer and "answer" in answer
        failed = failed or not ok
        lines.append(status("ask_documents", ok, f"sources={len(answer.get('chunks', []))}"))
    except Exception as exc:
        failed = True
        lines.append(status("ask_documents", False, str(exc)))

    model_router = loaded.get("core.model_router")
    try:
        ollama_available = model_router.is_ollama_available()
        ok = isinstance(ollama_available, bool)
        failed = failed or not ok
        lines.append(status("is_ollama_available", ok, str(ollama_available)))
    except Exception as exc:
        failed = True
        lines.append(status("is_ollama_available", False, str(exc)))

    try:
        models = model_router.get_installed_ollama_models()
        ok = isinstance(models, list)
        failed = failed or not ok
        detail = f"count={len(models)}"
        if not models:
            lines.append(warning("installed ollama models", "none found or Ollama unavailable"))
        lines.append(status("get_installed_ollama_models", ok, detail))
    except Exception as exc:
        failed = True
        lines.append(status("get_installed_ollama_models", False, str(exc)))

    try:
        model_status = model_router.get_model_status(ROOT)
        required = {"current_profile", "current_model", "ollama_available", "model_installed", "install_command"}
        ok = isinstance(model_status, dict) and required.issubset(model_status)
        failed = failed or not ok
        if ok and not model_status["model_installed"]:
            lines.append(warning("current model", model_status["install_command"]))
        lines.append(status("get_model_status", ok))
    except Exception as exc:
        failed = True
        lines.append(status("get_model_status", False, str(exc)))

    lines.extend(["", f"Result: {'FAIL' if failed else 'OK'}"])
    print("\n".join(lines))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
