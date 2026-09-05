"""Versioned schema checking and migration for ``.stru`` files.

A hand-written checker rather than a JSON-Schema dependency: the format is small, and the
error messages a user actually needs ("member 4 is missing 'j'") are easier to produce
directly than to extract from a generic validator.

Adding a field: bump ``CURRENT_VERSION``, register a migration below, and keep readers
tolerant of missing optional keys so old files still open.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

CURRENT_VERSION = "1.0"

_REQUIRED_TOP_LEVEL = ("schema_version", "nodes", "members")

_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "nodes": ("id", "x", "y"),
    "members": ("id", "i", "j"),
    "materials": ("id",),
    "sections": ("id",),
    "supports": ("node",),
    "load_cases": ("id",),
}


class SchemaError(ValueError):
    """Raised when a file cannot be interpreted as a Structura project."""


def validate_document(data: Any) -> None:
    """Check the raw parsed JSON before it reaches the model constructors.

    Catching malformed input here means ``Structure.from_dict`` can assume well-formed data
    and stay readable, and the user gets a message naming the offending record.
    """
    if not isinstance(data, dict):
        raise SchemaError(
            "Project file must contain a JSON object at the top level, "
            f"found {type(data).__name__}."
        )

    for key in _REQUIRED_TOP_LEVEL:
        if key not in data:
            raise SchemaError(f"Project file is missing the required top-level key {key!r}.")

    version = data["schema_version"]
    if not isinstance(version, str):
        raise SchemaError(f"'schema_version' must be a string, found {type(version).__name__}.")
    if version not in _MIGRATIONS and version != CURRENT_VERSION:
        raise SchemaError(
            f"Unsupported schema version {version!r}. "
            f"This build understands {sorted({*_MIGRATIONS, CURRENT_VERSION})}."
        )

    for collection, required in _REQUIRED_KEYS.items():
        _validate_collection(data, collection, required)

    _validate_unique_ids(data, "nodes")
    _validate_unique_ids(data, "members")
    _validate_cross_references(data)


def _validate_collection(data: dict[str, Any], name: str, required: tuple[str, ...]) -> None:
    records = data.get(name, [])
    if not isinstance(records, list):
        raise SchemaError(f"'{name}' must be a list, found {type(records).__name__}.")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise SchemaError(
                f"'{name}[{index}]' must be an object, found {type(record).__name__}."
            )
        for key in required:
            if key not in record:
                raise SchemaError(f"'{name}[{index}]' is missing the required key {key!r}.")


def _validate_unique_ids(data: dict[str, Any], name: str) -> None:
    seen: set[int] = set()
    for record in data.get(name, []):
        identifier = record["id"]
        if not isinstance(identifier, int):
            raise SchemaError(f"'{name}' id must be an integer, found {identifier!r}.")
        if identifier in seen:
            raise SchemaError(f"Duplicate {name[:-1]} id {identifier} in the project file.")
        seen.add(identifier)


def _validate_cross_references(data: dict[str, Any]) -> None:
    """Referential integrity at the file level, before any model object is built."""
    node_ids = {record["id"] for record in data.get("nodes", [])}
    member_ids = {record["id"] for record in data.get("members", [])}

    for record in data.get("members", []):
        for key in ("i", "j"):
            if record[key] not in node_ids:
                raise SchemaError(
                    f"Member {record['id']} references node {record[key]}, "
                    "which is not in the file."
                )
        if record["i"] == record["j"]:
            raise SchemaError(
                f"Member {record['id']} starts and ends at the same node ({record['i']})."
            )

    for record in data.get("supports", []):
        if record["node"] not in node_ids:
            raise SchemaError(
                f"A support references node {record['node']}, which is not in the file."
            )

    for case in data.get("load_cases", []):
        for record in case.get("nodal", []):
            if record.get("node") not in node_ids:
                raise SchemaError(
                    f"Load case {case['id']} has a nodal load on node {record.get('node')}, "
                    "which is not in the file."
                )
        for record in case.get("member", []):
            if record.get("member") not in member_ids:
                raise SchemaError(
                    f"Load case {case['id']} has a load on member {record.get('member')}, "
                    "which is not in the file."
                )


# ---------------------------------------------------------------- migrations


def _identity(data: dict[str, Any]) -> dict[str, Any]:
    return data


_MIGRATIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    # "0.9": _migrate_0_9_to_1_0,
}
"""Map of source version to a function producing the next version up.

Empty today because 1.0 is the first released format. The machinery exists so that the first
format change does not require inventing it under pressure.
"""


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a parsed document to ``CURRENT_VERSION``, applying migrations in order."""
    version = str(data.get("schema_version", CURRENT_VERSION))
    guard = 0
    while version != CURRENT_VERSION:
        migration = _MIGRATIONS.get(version)
        if migration is None:
            raise SchemaError(f"No migration path from schema version {version!r}.")
        data = migration(data)
        new_version = str(data.get("schema_version", CURRENT_VERSION))
        if new_version == version:
            raise SchemaError(f"Migration from {version!r} did not advance the version.")
        version = new_version
        guard += 1
        if guard > 50:
            raise SchemaError("Migration loop detected while upgrading the project file.")
    return data


__all__ = ["CURRENT_VERSION", "SchemaError", "migrate", "validate_document"]
