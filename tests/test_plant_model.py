from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from host.otis_tools.plant_model import load_plant_model, validate_plant_model


MODEL = Path("profiles/plant_models/cx317_h1_bench_v1.json")
SCHEMA = Path("schemas/plant_model_v1.schema.json")


def test_loads_initial_cx317_h1_plant_model() -> None:
    model = load_plant_model(MODEL)

    assert model.model_id == "cx317_h1_bench"
    assert model.model_version == 1
    assert model.automatic_control_range == (0x7000, 0x9000)
    assert not model.control_ready
    assert not model.actuation_enabled
    assert model.data["dac"]["reference_voltage_v"] is None
    assert model.data["plant_response"]["local_slope"]["hz_per_v"] == pytest.approx(4.297009404868848)
    assert model.data["plant_response"]["temperature_range_c"] == {"min_c": 23.296, "max_c": 27.825}


def test_schema_and_source_artifacts_are_present() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    model = load_plant_model(MODEL).data

    assert schema["properties"]["schema_version"]["const"] == 1
    for artifact in model["source_evidence"]["source_artifacts"]:
        assert Path(artifact).exists()


def test_rejects_automatic_range_wider_than_first_h1_limit() -> None:
    model = load_plant_model(MODEL).data
    changed = copy.deepcopy(model)
    changed["dac"]["automatic_control_range_codes"]["min"] = 0x6FFF

    with pytest.raises(ValueError, match="below 0x7000"):
        validate_plant_model(changed)

    changed = copy.deepcopy(model)
    changed["dac"]["automatic_control_range_codes"]["max"] = 0x9001

    with pytest.raises(ValueError, match="above 0x9000"):
        validate_plant_model(changed)


def test_rejects_empty_string_unknowns_and_enabled_actuation() -> None:
    model = load_plant_model(MODEL).data
    changed = copy.deepcopy(model)
    changed["dac"]["reference_voltage_v"] = ""

    with pytest.raises(ValueError, match="must be null when unknown"):
        validate_plant_model(changed)

    changed = copy.deepcopy(model)
    changed["status"]["actuation_enabled"] = True

    with pytest.raises(ValueError, match="actuation_enabled must remain false"):
        validate_plant_model(changed)

    changed = copy.deepcopy(model)
    changed["status"]["control_ready"] = True

    with pytest.raises(ValueError, match="control_ready must remain false"):
        validate_plant_model(changed)


def test_rejects_zero_slope_as_unknown_sentinel() -> None:
    model = load_plant_model(MODEL).data
    changed = copy.deepcopy(model)
    changed["plant_response"]["local_slope"]["hz_per_v"] = 0

    with pytest.raises(ValueError, match="must be null when unknown"):
        validate_plant_model(changed)
