# RET-C2-210 — Unit Tests: IntentClassifyNode
# BL-01, BL-02, BL-03 + framework compliance


from framework.schemas.trust_level import TrustLevel
from src.nodes.intent_classify import IntentClassifyNode


class _MockLLMService:
    """Deterministic mock LLM for intent tests."""

    def call(self, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
        lower = user_prompt.lower()
        if any(kw in lower for kw in ["delete", "erase", "erasure", "削除", "消去"]):
            return "erasure"
        if any(kw in lower for kw in ["loyalty point", "balance", "complaint", "product question"]):
            return "out_of_scope"
        if any(kw in lower for kw in ["know", "stored", "recommended", "lactose", "preferences", "context"]):
            return "qa"
        return "qa"  # default


class TestIntentClassifyNode:
    """Tests for IntentClassifyNode — BL-01, BL-02, BL-03."""

    def setup_method(self):
        self.node = IntentClassifyNode(llm_service=_MockLLMService())

    def test_required_trust_level(self):
        """required_trust_level must be VERIFIED_EXTERNAL."""
        assert IntentClassifyNode.required_trust_level == TrustLevel.VERIFIED_EXTERNAL

    # ── BL-01: Q&A intent ────────────────────────────────────────────────────

    def test_qa_intent_preference_question(self):
        """BL-01: preference question classified as 'qa'."""
        state = {"validated_input": "Does your system know I am lactose intolerant?"}
        result = self.node.execute(state)
        assert result["intent"] == "qa"

    def test_qa_intent_recommendation_question(self):
        """BL-01: recommendation question classified as 'qa'."""
        state = {"validated_input": "Why was this product recommended to me?"}
        result = self.node.execute(state)
        assert result["intent"] == "qa"

    def test_qa_intent_stored_context_question(self):
        """BL-01: stored context question classified as 'qa'."""
        state = {"validated_input": "What preferences are stored about me?"}
        result = self.node.execute(state)
        assert result["intent"] == "qa"

    # ── BL-02: Erasure intent ────────────────────────────────────────────────

    def test_erasure_intent_english_delete(self):
        """BL-02: English deletion request classified as 'erasure'."""
        state = {"validated_input": "Delete all my stored preferences"}
        result = self.node.execute(state)
        assert result["intent"] == "erasure"

    def test_erasure_intent_english_erase(self):
        """BL-02: English erasure request classified as 'erasure'."""
        state = {"validated_input": "I want my data erased"}
        result = self.node.execute(state)
        assert result["intent"] == "erasure"

    def test_erasure_intent_japanese(self):
        """BL-02: Japanese erasure request classified as 'erasure'."""
        state = {"validated_input": "個人情報を削除してください"}
        result = self.node.execute(state)
        assert result["intent"] == "erasure"

    # ── BL-03: Out-of-scope intent ───────────────────────────────────────────

    def test_out_of_scope_loyalty_points(self):
        """BL-03: loyalty point query classified as 'out_of_scope'."""
        state = {"validated_input": "What is my loyalty point balance?"}
        result = self.node.execute(state)
        assert result["intent"] == "out_of_scope"

    def test_out_of_scope_product_question(self):
        """BL-03: product question classified as 'out_of_scope'."""
        state = {"validated_input": "Can you tell me about this product question?"}
        result = self.node.execute(state)
        assert result["intent"] == "out_of_scope"

    # ── Fallback ──────────────────────────────────────────────────────────────

    def test_fallback_to_qa_on_unrecognised_llm_response(self):
        """Fallback: if LLM returns empty string, keyword fallback used."""

        class _EmptyLLM:
            def call(self, system_prompt, user_prompt, temperature=0.0):
                return ""  # unrecognised

        node = IntentClassifyNode(llm_service=_EmptyLLM())
        state = {"validated_input": "I want to know what context you have about me"}
        result = node.execute(state)
        # keyword fallback: "know" is in QA keywords → "qa"
        assert result["intent"] == "qa"

    def test_output_key_is_intent(self):
        """Output must contain 'intent' key."""
        state = {"validated_input": "What do you know about me?"}
        result = self.node.execute(state)
        assert "intent" in result
        assert result["intent"] in ("qa", "erasure", "out_of_scope")
