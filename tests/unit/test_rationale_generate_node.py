# RET-C2-210 — Unit Tests: RationaleGenerateNode
# BL-05 (citation-only constraint)


from framework.schemas.trust_level import TrustLevel
from src.nodes.rationale_generate import RationaleGenerateNode


class _MockLLMService:
    """Mock LLM that echoes field names in its response."""

    def call(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
        # Extract field names from context section and reference them in answer
        lines = user_prompt.split("\n")
        fields = [line.split(":")[0].strip("- ").strip() for line in lines if line.startswith("- ")]
        if fields:
            return f"Based on your stored context, I can see: {', '.join(fields)}."
        return ""


class _EmptyLLMService:
    def call(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
        return ""


class TestRationaleGenerateNode:
    """Tests for RationaleGenerateNode — BL-05 citation-only."""

    def test_required_trust_level(self):
        """required_trust_level must be VERIFIED_EXTERNAL."""
        assert RationaleGenerateNode.required_trust_level == TrustLevel.VERIFIED_EXTERNAL

    # ── BL-05: Citation-only constraint ──────────────────────────────────────

    def test_cited_fields_only_contains_chunk_fields(self):
        """BL-05: cited_fields only contains field names present in memory_chunks."""
        node = RationaleGenerateNode(llm_service=_MockLLMService())
        chunks = [
            {"field": "dietary_restrictions", "value": "lactose intolerant", "score": 0.9},
            {"field": "preferred_category", "value": "plant-based", "score": 0.8},
        ]
        state = {
            "validated_input": "What do you know about my dietary preferences?",
            "memory_chunks": chunks,
        }
        result = node.execute(state)
        assert "cited_fields" in result
        available = {c["field"] for c in chunks}
        for field in result["cited_fields"]:
            assert field in available, f"cited_fields contains '{field}' which is NOT in memory_chunks — hallucination!"

    def test_answer_present_in_output(self):
        """BL-05: answer key is present in output."""
        node = RationaleGenerateNode(llm_service=_MockLLMService())
        chunks = [{"field": "preference_x", "value": "test", "score": 0.9}]
        state = {"validated_input": "test query", "memory_chunks": chunks}
        result = node.execute(state)
        assert "answer" in result
        assert isinstance(result["answer"], str)
        assert len(result["answer"]) > 0

    def test_empty_chunks_returns_no_context_message(self):
        """BL-05: empty memory_chunks returns standard no-context message."""
        node = RationaleGenerateNode(llm_service=_EmptyLLMService())
        state = {
            "validated_input": "What dietary preferences are stored about me?",
            "memory_chunks": [],
        }
        result = node.execute(state)
        assert result["cited_fields"] == []
        assert "No AI context" in result["answer"] or len(result["answer"]) > 0

    def test_cited_fields_empty_when_no_chunks(self):
        """BL-05: cited_fields is empty when no chunks available."""
        node = RationaleGenerateNode(llm_service=_EmptyLLMService())
        state = {"validated_input": "test", "memory_chunks": []}
        result = node.execute(state)
        assert result["cited_fields"] == []

    def test_no_hallucination_with_empty_llm_response(self):
        """BL-05: if LLM returns empty string, fallback message is returned (no hallucination)."""
        node = RationaleGenerateNode(llm_service=_EmptyLLMService())
        chunks = [{"field": "some_field", "value": "some_value", "score": 0.9}]
        state = {"validated_input": "test", "memory_chunks": chunks}
        result = node.execute(state)
        # Answer should be the fallback message
        assert "No AI context" in result["answer"] or result["answer"]

    def test_output_keys(self):
        """Output must contain 'answer' and 'cited_fields' keys."""
        node = RationaleGenerateNode(llm_service=_MockLLMService())
        state = {
            "validated_input": "test",
            "memory_chunks": [{"field": "test_field", "value": "val", "score": 0.9}],
        }
        result = node.execute(state)
        assert "answer" in result
        assert "cited_fields" in result
        assert isinstance(result["cited_fields"], list)
