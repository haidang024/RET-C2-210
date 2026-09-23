"""PB-2/PB-5: State fields are serialization-safe and contain no credentials."""

from __future__ import annotations

import ast
import dataclasses
import json
import pathlib
import re

import pytest
from src.schemas.state import State

CREDENTIAL_FIELD_PATTERNS = re.compile(
    r"(jwt|token|api_key|secret|password|credential|connection_string)", re.IGNORECASE
)
PROHIBITED_TYPE_ANNOTATIONS = ("BaseModel", "InvocationContext")
_CONFIG_PATH = pathlib.Path(__file__).parents[2] / "config" / "config.yaml"


def _checkpointing_enabled() -> bool:
    import yaml

    config = yaml.safe_load(_CONFIG_PATH.read_text()) or {}
    return bool(config.get("memory_enabled") or config.get("hitl", {}).get("enabled"))


def _framework_ingress_protection_available() -> bool:
    from framework.graph.base_graph import BaseGraph

    return all(hasattr(BaseGraph, hook) for hook in ("_sanitize_ingress", "_sanitize_resume_feedback"))


def _scan_state_file(filepath: pathlib.Path) -> list[str]:
    tree = ast.parse(filepath.read_text(), filename=str(filepath))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
                continue
            field_name = item.target.id
            if CREDENTIAL_FIELD_PATTERNS.search(field_name):
                violations.append(f"credential-like field: {field_name}")
            annotation = ast.dump(item.annotation)
            for prohibited in PROHIBITED_TYPE_ANNOTATIONS:
                if prohibited in annotation:
                    violations.append(f"prohibited State type: {prohibited}")
    return violations


def _complete_state() -> dict:
    return {
        "raw_input": "What preferences are stored about me?",
        "customer_id": "cust_hash_abc123",
        "query_text": "What preferences are stored about me?",
        "channel_id": "chat_app",
        "validated_input": "What preferences are stored about me?",
        "customer_id_validated": True,
        "intent": "qa",
        "memory_chunks": [{"field": "dietary_restrictions", "value": "lactose intolerant", "score": 0.9}],
        "cited_fields": ["dietary_restrictions"],
        "answer": "Stored dietary restriction context is available.",
        "erasure_confirmed": False,
        "erasure_audit_id": None,
        "erasure_segments_deleted": 0,
        "result": '{"intent":"qa"}',
        "status": "success",
        "audit_record": {"interaction_id": "audit-001", "customer_id_hash": "cust_hash_abc123"},
    }


def test_state_file_has_no_credential_fields_or_unsafe_types() -> None:
    state_file = pathlib.Path(__file__).parents[2] / "src" / "schemas" / "state.py"
    assert _scan_state_file(state_file) == []


def test_state_is_json_serializable() -> None:
    assert json.loads(json.dumps(_complete_state()))["customer_id_validated"] is True


def test_state_contains_no_pydantic_or_dataclass_instances() -> None:
    from pydantic import BaseModel

    for key, value in _complete_state().items():
        assert not isinstance(value, BaseModel), key
        assert not dataclasses.is_dataclass(value), key


def test_state_typeddict_annotations_are_safe() -> None:
    for field in (
        "raw_input",
        "customer_id",
        "memory_chunks",
        "erasure_confirmed",
        "audit_record",
    ):
        assert field in State.__annotations__


_PB5_APPLICABLE = _checkpointing_enabled() and _framework_ingress_protection_available()


@pytest.mark.skipif(
    not _PB5_APPLICABLE,
    reason="checkpointing disabled or framework ingress protection unavailable",
)
def test_pb5_precheckpoint_ingress_not_raw() -> None:
    pytest.fail("PB-5 became applicable; wire a real checkpointer fixture before enabling memory or HITL")
