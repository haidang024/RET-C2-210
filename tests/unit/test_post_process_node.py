# RET-C2-210 — Unit Tests: PostProcessNode
# TC-07, BL out/qa/erasure branches

import json
import pytest

from framework.errors import SecurityViolationError
from framework.schemas.trust_level import TrustLevel
from src.nodes.post_process_node import PostProcessNode


class TestPostProcessNode:
    """Tests for PostProcessNode — S-2 PII redaction + audit."""

    def setup_method(self):
        self.node = PostProcessNode()

    # ── TC-07: framework gate is final; domain extension hook is overridable ─

    def test_framework_security_gate_output_is_final(self):
        """TC-07: framework-owned _security_gate_output() must be final."""
        method = PostProcessNode._security_gate_output
        assert getattr(method, "__final__", False)

    def test_required_trust_level(self):
        """required_trust_level must be TrustLevel.VERIFIED_EXTERNAL."""
        assert PostProcessNode.required_trust_level == TrustLevel.VERIFIED_EXTERNAL

    # ── Q&A branch ───────────────────────────────────────────────────────────

    def test_qa_branch_formats_result_json(self):
        """BL: Q&A branch returns JSON with answer, cited_fields, intent."""
        state = {
            "intent": "qa",
            "answer": "Your stored context shows you are lactose intolerant.",
            "cited_fields": ["dietary_restrictions"],
            "customer_id": "cust_hash_abc123",
        }
        result = self.node.execute(state)
        assert "result" in result
        parsed = json.loads(result["result"])
        assert parsed["intent"] == "qa"
        assert "answer" in parsed
        assert "cited_fields" in parsed
        assert "audit_id" in parsed

    def test_qa_branch_redacts_email_in_answer(self):
        """S-2: Email address in answer is redacted before delivery."""
        state = {
            "intent": "qa",
            "answer": "We store your email: user@example.com as a preference.",
            "cited_fields": [],
            "customer_id": "cust_hash_abc123",
        }
        result = self.node.execute(state)
        parsed = json.loads(result["result"])
        assert "user@example.com" not in parsed["answer"]
        assert "[EMAIL_REDACTED]" in parsed["answer"]

    # ── Erasure branch ───────────────────────────────────────────────────────

    def test_erasure_branch_formats_result_json(self):
        """BL: Erasure branch returns JSON with erasure_confirmed, audit_id."""
        state = {
            "intent": "erasure",
            "erasure_confirmed": True,
            "erasure_audit_id": "era_abc123",
            "erasure_segments_deleted": 5,
            "customer_id": "cust_hash_abc123",
        }
        result = self.node.execute(state)
        assert "result" in result
        parsed = json.loads(result["result"])
        assert parsed["intent"] == "erasure"
        assert parsed["erasure_confirmed"] is True
        assert parsed["segments_deleted"] == 5
        assert "audit_id" in parsed

    # ── Out-of-scope branch ──────────────────────────────────────────────────

    def test_out_of_scope_returns_scope_notice(self):
        """BL-03: out_of_scope intent returns a redirect/scope notice."""
        state = {
            "intent": "out_of_scope",
            "customer_id": "cust_hash_abc123",
        }
        result = self.node.execute(state)
        parsed = json.loads(result["result"])
        assert parsed["intent"] == "out_of_scope"
        assert "answer" in parsed
        assert len(parsed["answer"]) > 0

    # ── Audit record ─────────────────────────────────────────────────────────

    def test_audit_record_written_to_state(self):
        """S-4: audit_record is written to state with required fields."""
        state = {
            "intent": "qa",
            "answer": "Some answer",
            "cited_fields": [],
            "customer_id": "cust_hash_abc123",
            "channel_id": "chat_app",
        }
        result = self.node.execute(state)
        assert "audit_record" in result
        audit = result["audit_record"]
        assert "interaction_id" in audit
        assert "customer_id_hash" in audit
        assert "intent" in audit
        assert "timestamp" in audit
        assert audit["intent"] == "qa"

    # ── Blocked state ────────────────────────────────────────────────────────

    def test_raises_on_blocked_status(self):
        """Security gate raises SecurityViolationError if upstream status is 'blocked'."""
        state = {
            "intent": "qa",
            "status": "blocked",
            "customer_id": "cust_hash_abc123",
        }
        with pytest.raises(SecurityViolationError):
            self.node.execute(state)
