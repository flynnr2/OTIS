"""Dispatch validation for either member of the matched CX319 live pair."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _identity(path: Path) -> tuple[object, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("CX319 proposal must be a JSON object")
    return value.get("gate"), value.get("leg")


def validate_frozen_proposal(path: Path) -> dict[str, Any]:
    identity = _identity(path)
    if identity in {("PBL", "L"), ("PBU", "U"), ("PBUC", "C")}:
        from .conditional_part_b_bundle import validate_frozen_proposal as validate
    elif identity == ("G3", "B"):
        from .bounded_tight_deadband_upper_bundle import validate_frozen_proposal as validate
    else:
        from .bounded_tight_deadband_bundle import validate_frozen_proposal as validate
    return validate(path)


def validate_proposal(path: Path) -> dict[str, Any]:
    identity = _identity(path)
    if identity in {("PBL", "L"), ("PBU", "U"), ("PBUC", "C")}:
        from .conditional_part_b_bundle import validate_proposal as validate
    elif identity == ("G3", "B"):
        from .bounded_tight_deadband_upper_bundle import validate_proposal as validate
    else:
        from .bounded_tight_deadband_bundle import validate_proposal as validate
    return validate(path)
