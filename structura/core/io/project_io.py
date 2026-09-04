"""Reading and writing ``.stru`` project files.

The format is pretty-printed JSON in **SI base units** — readable, diffable, and safe to hand
to another tool. The ``display_units`` block is a UI preference and carries no numerical
meaning (conventions §1).

Analysis results are deliberately *not* stored in the project file. They can be written
alongside it as a ``.res.json`` sidecar carrying the model hash they came from, so stale
results are detectable rather than silently trusted.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..model import Structure
from .schema import SchemaError, migrate, validate_document

PROJECT_SUFFIX = ".stru"
RESULT_SUFFIX = ".res.json"


def save(structure: Structure, path: str | os.PathLike[str]) -> Path:
    """Write a structure to disk atomically.

    Writes to a temporary file in the same directory and then replaces the target, so an
    interrupted save can never leave a half-written project where the original used to be.
    """
    target = Path(path)
    if target.suffix == "":
        target = target.with_suffix(PROJECT_SUFFIX)
    target.parent.mkdir(parents=True, exist_ok=True)

    payload = structure.to_dict()
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    handle, temp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.stem}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return target


def load(path: str | os.PathLike[str]) -> Structure:
    """Read a structure from disk, validating and migrating the document first."""
    source = Path(path)
    try:
        raw = source.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SchemaError(f"Project file not found: {source}") from exc

    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SchemaError(
            f"{source.name} is not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})."
        ) from exc

    validate_document(data)
    data = migrate(data)
    return Structure.from_dict(data)


def loads(text: str) -> Structure:
    """Parse a structure from a JSON string. Convenient in tests and for the clipboard."""
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaError(
            f"Input is not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})."
        ) from exc
    validate_document(data)
    return Structure.from_dict(migrate(data))


def dumps(structure: Structure) -> str:
    """Serialise a structure to a JSON string."""
    return json.dumps(structure.to_dict(), indent=2, ensure_ascii=False) + "\n"


def result_path_for(project_path: str | os.PathLike[str]) -> Path:
    """Where the results sidecar for a given project file lives."""
    source = Path(project_path)
    return source.with_suffix("").with_suffix(RESULT_SUFFIX)


__all__ = [
    "PROJECT_SUFFIX",
    "RESULT_SUFFIX",
    "SchemaError",
    "dumps",
    "load",
    "loads",
    "result_path_for",
    "save",
]
