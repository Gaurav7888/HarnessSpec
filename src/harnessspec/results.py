"""Strict benchmark result validation and JSON persistence (standard library)."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "pilot" / "result.schema.json"
KEY_FIELDS = ("benchmark", "task_id", "designer", "seed")
_SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
_TYPES = {"integer": (int,), "number": (int, float), "boolean": (bool,), "string": (str,)}


def result_key(row: dict) -> tuple[str, str, str, int]:
    return tuple(row[field] for field in KEY_FIELDS)


def validate_result(row: object) -> None:
    """Raise ValueError for a row outside the shared contract.

    JSON's integer values must be serialized as integers, and boolean values
    cannot be used as numeric counters.
    """
    if not isinstance(row, dict):
        raise ValueError("result must be an object")
    missing = set(_SCHEMA["required"]) - row.keys()
    extra = row.keys() - _SCHEMA["properties"].keys()
    if missing or extra:
        raise ValueError(f"missing fields {sorted(missing)}; unexpected fields {sorted(map(str, extra))}")
    for field, rule in _SCHEMA["properties"].items():
        value = row[field]
        if "enum" in rule:
            if value not in rule["enum"]:
                raise ValueError(f"{field} must be one of {rule['enum']}")
            continue
        if type(value) not in _TYPES[rule["type"]]:
            raise ValueError(f"{field} must be a JSON {rule['type']}")
        if type(value) is float and not math.isfinite(value):
            raise ValueError(f"{field} must be finite")
        if "minLength" in rule and len(value) < rule["minLength"]:
            raise ValueError(f"{field} must be non-empty")
        if ("minimum" in rule and value < rule["minimum"] or
                "maximum" in rule and value > rule["maximum"]):
            raise ValueError(f"{field} is outside its allowed range")


def read_results(paths: list[Path]) -> list[dict]:
    """Read arrays of rows and reject duplicate run identities across files."""
    rows = {}
    for path in paths:
        records = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_fields)
        if not isinstance(records, list):
            raise ValueError(f"{path}: expected an array of result objects")
        for index, row in enumerate(records):
            try:
                validate_result(row)
                key = result_key(row)
                if key in rows:
                    raise ValueError(f"duplicate run {key}")
                rows[key] = row
            except ValueError as error:
                raise ValueError(f"{path} row {index + 1}: {error}") from error
    return [rows[key] for key in sorted(rows)]


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for field, value in pairs:
        if field in result:
            raise ValueError(f"duplicate JSON field {field}")
        result[field] = value
    return result


def write_json(path: Path, value: object) -> None:
    """Replace one JSON artifact atomically after flushing its contents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
