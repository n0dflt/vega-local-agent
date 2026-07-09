from __future__ import annotations


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 150) -> list[dict]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    if overlap < 0:
        raise ValueError("overlap must be 0 or greater")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    if not text:
        return []

    chunks: list[dict] = []
    start = 0
    chunk_id = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append({
            "chunk_id": chunk_id,
            "text": text[start:end],
            "start": start,
            "end": end,
        })

        if end >= len(text):
            break

        next_start = end - overlap
        if next_start <= start:
            break

        start = next_start
        chunk_id += 1

    return chunks
