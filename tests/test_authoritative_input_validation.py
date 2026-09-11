from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json

import pytest
from jsonschema.exceptions import SchemaError

from host.otis_tools import authoritative_inputs as inputs


def _replace_document(value, group, path, document):
    data = json.dumps(document, sort_keys=True).encode()
    entry = next(item for item in value[group] if item["path"] == path)
    entry.update(content=data.decode(), size_bytes=len(data), sha256=sha256(data).hexdigest())
    value["set_sha256"] = inputs._canonical_sha256(
        {key: item for key, item in value.items() if key != "set_sha256"}
    )


def test_repeated_authority_access_checks_schema_syntax_once_per_content(monkeypatch):
    inputs._check_schema_bytes.cache_clear()
    original = inputs.Draft202012Validator.check_schema
    checked = []

    def check(schema):
        checked.append(json.dumps(schema, sort_keys=True))
        return original(schema)

    monkeypatch.setattr(inputs.Draft202012Validator, "check_schema", check)
    frozen = inputs.collect_authoritative_inputs()
    first = inputs.validate_authoritative_inputs(frozen)
    for path in inputs.CURRENT_PROFILE_PATHS:
        assert first.document(path) == inputs.validate_authoritative_inputs(deepcopy(frozen)).document(path)
        first.binding(path)
    assert len(checked) == len(set(checked)) == len(inputs.CURRENT_SCHEMA_PATHS)
    assert inputs._check_schema_bytes.cache_info().maxsize == 32


def test_warm_schema_cache_does_not_admit_changed_profile_or_forged_bytes():
    frozen = inputs.collect_authoritative_inputs()
    documents = inputs.validate_authoritative_inputs(frozen)
    profile = deepcopy(documents.document(inputs.ROOT_PROFILE))
    profile["unexpected_profile_field"] = True
    _replace_document(frozen, "profiles", inputs.ROOT_PROFILE, profile)
    with pytest.raises(ValueError, match="frozen profile fails"):
        inputs.validate_authoritative_inputs(frozen)

    frozen = inputs.collect_authoritative_inputs()
    inputs.validate_authoritative_inputs(frozen)
    frozen["profiles"][0]["content"] += " "
    with pytest.raises(ValueError, match="identity differs"):
        inputs.validate_authoritative_inputs(frozen)


def test_changed_schema_is_checked_and_invalid_syntax_is_not_cached():
    frozen = inputs.collect_authoritative_inputs()
    documents = inputs.validate_authoritative_inputs(frozen)
    path = inputs.PROFILE_SCHEMA_BINDINGS[inputs.ROOT_PROFILE]
    schema = deepcopy(documents.document(path))
    schema["type"] = "not_a_json_schema_type"
    _replace_document(frozen, "schemas", path, schema)
    for _ in range(2):
        with pytest.raises(SchemaError):
            inputs.validate_authoritative_inputs(frozen)


def test_returned_documents_cannot_poison_later_validation():
    frozen = inputs.collect_authoritative_inputs()
    first = inputs.validate_authoritative_inputs(frozen)
    original = deepcopy(first.document(inputs.ROOT_PROFILE))
    first.document(inputs.ROOT_PROFILE).clear()
    assert first.document(inputs.ROOT_PROFILE) == original


def test_validated_context_detaches_raw_input_and_all_returned_views():
    from dataclasses import FrozenInstanceError
    raw = inputs.collect_authoritative_inputs()
    context = inputs.validate_authoritative_inputs(raw)
    original = context.as_dict()
    raw["profiles"][0]["content"] += " "
    assert not context.matches(raw)
    assert context.matches(original)
    context.as_dict()["profiles"].clear()
    context.summary()["profiles"].clear()
    context.binding(inputs.ROOT_PROFILE).clear()
    assert context.as_dict() == original
    with pytest.raises(FrozenInstanceError):
        context.set_sha256 = "f" * 64


def test_transaction_consumer_rejects_context_for_different_payload():
    raw = inputs.collect_authoritative_inputs()
    context = inputs.validate_authoritative_inputs(raw)
    raw["profiles"][0]["content"] += " "
    with pytest.raises(ValueError, match="differ"):
        inputs.transaction_identities_from_bundle({"authoritative_inputs": raw}, inputs=context)


def test_transaction_policy_identity_comes_from_frozen_policy():
    context = inputs.validate_authoritative_inputs(inputs.collect_authoritative_inputs())
    expected = context.binding(inputs.ROOT_PROFILE)["sha256"]
    bundle = {"authoritative_inputs": context.as_dict(), "policy": {"policy_sha256": expected}}
    identities = inputs.transaction_identities_from_bundle(bundle, inputs=context)
    assert identities["active_policy_sha256"] == identities["numerical_policy_sha256"] == expected
    bundle["policy"]["policy_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="policy identity differs"):
        inputs.transaction_identities_from_bundle(bundle, inputs=context)
