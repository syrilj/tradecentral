"""Validation and loading for external research provenance.

This is intentionally metadata-only.  Referenced projects are not imported,
vendored, or made runtime dependencies by this module.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_EDGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROVENANCE_PATH = _EDGE_ROOT / "config" / "upstream_provenance.json"


@dataclass(frozen=True)
class UpstreamSource:
    """A pinned upstream reference and the permitted way it informs research."""

    name: str
    url: str
    commit: str
    license: str
    purpose: str
    usage: str
    code_imported: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("upstream source name is required")
        if not self.url.startswith("https://"):
            raise ValueError("upstream URL must use https")
        if not _COMMIT.fullmatch(self.commit):
            raise ValueError("commit must be a full, lowercase 40-character SHA-1")
        if not self.license:
            raise ValueError("upstream license is required")
        if self.code_imported:
            raise ValueError("external source code must not be imported into edge runtime")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "UpstreamSource":
        return cls(
            name=str(value["name"]),
            url=str(value["url"]),
            commit=str(value["commit"]),
            license=str(value["license"]),
            purpose=str(value["purpose"]),
            usage=str(value["usage"]),
            code_imported=bool(value.get("code_imported", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "commit": self.commit,
            "license": self.license,
            "purpose": self.purpose,
            "usage": self.usage,
            "code_imported": self.code_imported,
        }


def load_upstream_provenance(path: str | Path = DEFAULT_PROVENANCE_PATH) -> tuple[UpstreamSource, ...]:
    """Load the checked-in, schema-versioned list of pinned references."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != "edge-upstream-provenance-v1":
        raise ValueError("unsupported upstream provenance schema")
    sources = tuple(UpstreamSource.from_mapping(item) for item in raw.get("sources", ()))
    if not sources:
        raise ValueError("at least one upstream source is required")
    names = [item.name for item in sources]
    if len(set(names)) != len(names):
        raise ValueError("upstream source names must be unique")
    return sources
