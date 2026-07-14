"""Safety checks shared by VEGA project file tools."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath


DEFAULT_MAX_CHARS = 12_000
BLOCKED_DIRECTORIES = frozenset({
    ".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules",
    "data", "logs", "cache", "caches",
})
SENSITIVE_MARKERS = ("secret", "token", "password", "credential", "private")
SENSITIVE_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx"})


class FileSafetyError(ValueError):
    """A calm, user-facing file safety error."""


def get_project_root() -> Path:
    """Return VEGA's project root, independent of the current directory."""
    return Path(__file__).resolve().parents[1]


def is_blocked_directory(name: str) -> bool:
    return name.lower() in BLOCKED_DIRECTORIES


def is_sensitive_file(path: Path) -> bool:
    name = path.name.lower()
    return (
        name == ".env"
        or name.startswith(".env.")
        or any(marker in name for marker in SENSITIVE_MARKERS)
        or path.suffix.lower() in SENSITIVE_SUFFIXES
    )


def _portable_relative_path(path: str) -> Path:
    """Parse untrusted paths with both POSIX and Windows absolute-path rules."""
    if not isinstance(path, str) or not path.strip() or "\x00" in path:
        raise FileSafetyError("Path must be a non-empty relative path.")
    value = path.strip()
    windows = PureWindowsPath(value)
    posix = PurePosixPath(value.replace("\\", "/"))
    if windows.is_absolute() or windows.drive or posix.is_absolute():
        raise FileSafetyError("Absolute paths are not allowed.")
    parts = tuple(part for part in posix.parts if part not in {"", "."})
    if not parts and value in {".", "./", ".\\"}:
        return Path(".")
    if not parts or ".." in parts:
        raise FileSafetyError("Parent-directory traversal is not allowed.")
    if any(":" in part for part in parts):
        raise FileSafetyError("Windows stream and drive paths are not allowed.")
    return Path(*parts)


def safe_path(path: str = ".", *, must_exist: bool = True) -> Path:
    """Resolve a relative project path and reject escapes/service directories."""
    candidate_input = _portable_relative_path(path)

    root = get_project_root().resolve()
    candidate = (root / candidate_input).resolve(strict=False)
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise FileSafetyError("Path escapes the project root.") from exc

    if any(is_blocked_directory(part) for part in relative.parts):
        raise FileSafetyError("Access to service directories is blocked.")
    if must_exist and not candidate.exists():
        raise FileSafetyError(f"Path does not exist: {path}")
    return candidate


def validate_readable_file(path: str) -> Path:
    candidate = safe_path(path)
    if not candidate.is_file():
        raise FileSafetyError(f"Not a file: {path}")
    if is_sensitive_file(candidate):
        raise FileSafetyError("Reading sensitive files is blocked.")
    return candidate


def _reject_symlink_components(path: str) -> None:
    """Reject traversal and symbolic links in every lexical path component."""
    candidate_input = _portable_relative_path(path)

    current = get_project_root().resolve()

    for part in candidate_input.parts:
        if part in {"", "."}:
            continue

        current = current / part
        if current.is_symlink():
            raise FileSafetyError("Symbolic links are not allowed for writable files.")


def validate_writable_text_file(path: str) -> Path:
    """Validate an existing UTF-8 text file before a controlled write."""
    _portable_relative_path(path)

    _reject_symlink_components(path)

    candidate = safe_path(path)

    if not candidate.is_file():
        raise FileSafetyError(f"Not a file: {path}")

    if is_sensitive_file(candidate):
        raise FileSafetyError("Writing sensitive files is blocked.")

    try:
        raw = candidate.read_bytes()
    except OSError as exc:
        raise FileSafetyError(f"Cannot read file before writing: {path}") from exc

    if b"\x00" in raw:
        raise FileSafetyError("Binary files cannot be modified.")

    try:
        raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FileSafetyError("Only valid UTF-8 text files can be modified.") from exc

    return candidate


def read_text(path: Path, max_chars: int = DEFAULT_MAX_CHARS) -> tuple[str, bool]:
    """Read bounded UTF-8 text and reject binary/invalid input."""
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 1:
        raise FileSafetyError("max_chars must be a positive integer.")
    with path.open("rb") as handle:
        raw = handle.read(max_chars * 4 + 4)
    if b"\x00" in raw:
        raise FileSafetyError("Binary files cannot be read.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FileSafetyError("File is not valid UTF-8 text.") from exc
    truncated = len(text) > max_chars or path.stat().st_size > len(raw)
    return text[:max_chars], truncated
