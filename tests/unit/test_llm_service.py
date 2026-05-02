"""
tests/unit/test_llm_service.py
Unit tests for the LLMService JSON repair strategy.
Tests all 4 repair layers without making real API calls.
"""
import pytest

from app.services.llm_service import LLMService


@pytest.fixture
def llm() -> LLMService:
    # We test the parsing logic only — no API key needed
    import os
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-" + "x" * 20)
    os.environ.setdefault("SECRET_KEY", "test-secret-key-" + "x" * 20)
    return LLMService()


class TestRobustParse:
    """Tests for LLMService._robust_parse()"""

    VALID_JSON = """{
        "caseTitle": "Worker Injury Compensation",
        "legalAreas": ["Labour Law"],
        "scenarioSummary": "A factory worker was injured.",
        "jurisdiction": "India",
        "sourceType": "scenario",
        "applicableLaws": [{"name": "Factories Act", "year": "1948", "relevance": "Workplace safety."}],
        "applicableSections": [],
        "relevantCaseLaws": [],
        "smartDefence": {
            "overview": "Strong case on employer liability.",
            "pillars": [],
            "keyArguments": [],
            "prosecutionCounters": [],
            "evidenceRequired": [],
            "proceduralMoves": []
        },
        "possibleOutcomes": [],
        "litigationStrategy": ["File complaint."],
        "immediateActions": ["Preserve evidence."],
        "keyRisks": ["Employer counter-claim."]
    }"""

    def test_layer1_valid_json(self, llm: LLMService) -> None:
        result = llm._robust_parse(self.VALID_JSON)
        assert result is not None
        assert result["caseTitle"] == "Worker Injury Compensation"

    def test_layer1_strips_markdown_fence(self, llm: LLMService) -> None:
        fenced = f"```json\n{self.VALID_JSON}\n```"
        result = llm._robust_parse(fenced)
        assert result is not None
        assert result["jurisdiction"] == "India"

    def test_layer1_strips_plain_fence(self, llm: LLMService) -> None:
        fenced = f"```\n{self.VALID_JSON}\n```"
        result = llm._robust_parse(fenced)
        assert result is not None

    def test_layer2_truncated_json(self, llm: LLMService) -> None:
        """Simulate response cut off mid-array."""
        truncated = self.VALID_JSON[:400]  # Cut off in the middle
        result = llm._robust_parse(truncated)
        # Should not crash — may return partial result or None
        # The key assertion is no exception is raised

    def test_layer3_trailing_comma(self, llm: LLMService) -> None:
        bad_json = '{"key": "value", "arr": ["a", "b",], "nested": {"x": 1,}}'
        result = llm._robust_parse(bad_json)
        assert result is not None
        assert result["key"] == "value"

    def test_layer4_fallback_extracts_fields(self, llm: LLMService) -> None:
        """Completely broken JSON should still extract scalar fields."""
        broken = '{"caseTitle": "My Case", "jurisdiction": "India", BROKEN JSON HERE ...'
        result = llm._robust_parse(broken)
        assert result is not None
        assert result["caseTitle"] == "My Case"
        assert result["jurisdiction"] == "India"

    def test_empty_string_returns_none(self, llm: LLMService) -> None:
        assert llm._robust_parse("") is None

    def test_no_json_object_returns_none(self, llm: LLMService) -> None:
        assert llm._robust_parse("This is just text with no JSON.") is None

    def test_preamble_before_json(self, llm: LLMService) -> None:
        with_preamble = f"Here is the analysis:\n{self.VALID_JSON}"
        result = llm._robust_parse(with_preamble)
        assert result is not None
        assert result["caseTitle"] == "Worker Injury Compensation"


class TestExtractFieldsFallback:
    def test_extracts_string_fields(self, llm: LLMService) -> None:
        raw = '{"caseTitle": "Test Case", "jurisdiction": "United Kingdom"}'
        result = llm._extract_fields_fallback(raw)
        assert result["caseTitle"] == "Test Case"
        assert result["jurisdiction"] == "United Kingdom"

    def test_extracts_array_fields(self, llm: LLMService) -> None:
        raw = '{"litigationStrategy": ["Step 1", "Step 2", "Step 3"]}'
        result = llm._extract_fields_fallback(raw)
        assert result["litigationStrategy"] == ["Step 1", "Step 2", "Step 3"]

    def test_missing_fields_return_defaults(self, llm: LLMService) -> None:
        result = llm._extract_fields_fallback("{}")
        assert result["caseTitle"] == "Legal Analysis"
        assert result["applicableLaws"] == []
        assert result["smartDefence"]["pillars"] == []
