# TC-01: State TypedDict compliance tests for RET-C2-210

import os

from src.schemas.state import State


class TestStateSchema:
    """TC-01, TC-03, TC-04: State must be flat TypedDict, no credentials, no InvocationContext."""

    def test_state_is_dict_compatible(self):
        """TC-01: State is TypedDict (dict-compatible, not Pydantic/dataclass)."""
        # TypedDict produces a class whose instances are plain dicts
        # State can be used as a type annotation (TypedDict) — verify it's not BaseModel
        assert not hasattr(State, "__fields__"), "State must NOT be a Pydantic BaseModel"
        assert not hasattr(State, "__dataclass_fields__"), "State must NOT be a dataclass"

    def test_state_no_pydantic_base(self):
        """TC-01: State does not inherit from Pydantic BaseModel."""
        for base in State.__mro__:
            assert "BaseModel" not in base.__name__, f"State must not inherit from Pydantic BaseModel, found: {base}"

    def test_state_annotations_present(self):
        """TC-01: State has expected TypedDict annotations."""
        annotations = State.__annotations__
        required_fields = [
            "raw_input",
            "customer_id",
            "query_text",
            "memory_chunks",
            "cited_fields",
            "answer",
            "erasure_confirmed",
            "erasure_audit_id",
            "audit_record",
        ]
        for field in required_fields:
            assert field in annotations, f"State missing expected field: {field}"

    def test_state_no_credential_fields(self):
        """TC-03: State annotations do not contain credential field names."""
        credential_keywords = ["api_key", "secret", "password", "token", "jwt", "credential"]
        annotations = State.__annotations__
        for field_name in annotations:
            for kw in credential_keywords:
                assert kw not in field_name.lower(), f"State field '{field_name}' looks like a credential field"

    def test_state_no_invocation_context(self):
        """TC-04: State does not store InvocationContext."""
        state_file = os.path.join(os.path.dirname(__file__), "..", "..", "src", "schemas", "state.py")
        with open(state_file) as f:
            source = f.read()
        assert "InvocationContext" not in source, "State must not reference InvocationContext"

    def test_customer_id_is_not_pii_annotated(self):
        """TC-03: customer_id field description documents it as hashed/tokenised."""
        # customer_id is type str — no PII annotation. Document check via source scan.
        state_file = os.path.join(os.path.dirname(__file__), "..", "..", "src", "schemas", "state.py")
        with open(state_file) as f:
            source = f.read()
        # The state file comment should mention hashed/tokenised (per instruction 03)
        assert (
            "hashed" in source.lower() or "tokenised" in source.lower()
        ), "state.py must document that customer_id is hashed/tokenised"
