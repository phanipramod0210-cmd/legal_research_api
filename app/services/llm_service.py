"""
app/services/llm_service.py
Anthropic Claude integration with:
- Structured prompt building
- Retry with exponential backoff (tenacity)
- 4-layer JSON repair strategy
- Token usage tracking
"""
import json
import re
import time
from typing import Any

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.core.exceptions import AnalysisFailedException, AnthropicAPIException
from app.core.logger import logger


settings = get_settings()

# Singleton client
_client: anthropic.AsyncAnthropic | None = None


def get_anthropic_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            timeout=settings.ANTHROPIC_TIMEOUT,
            max_retries=0,  # We handle retries via tenacity
        )
    return _client


# ─────────────────────────────────────────────────────────────
#  Prompt Builder
# ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """\
You are an elite legal research AI specialising in {jurisdiction} law.
Return ONLY a raw JSON object — no markdown fences, no preamble, no text outside JSON.
Start the response with {{ and end with }}.

Keep ALL string values concise (1-2 sentences) to avoid truncation.
Use this EXACT structure:

{{
  "caseTitle": "Short descriptive title (max 10 words)",
  "legalAreas": ["area1", "area2"],
  "scenarioSummary": "2-3 sentence factual summary.",
  "jurisdiction": "{jurisdiction}",
  "sourceType": "{source_type}",
  "applicableLaws": [
    {{ "name": "Full Act Name", "year": "YYYY", "relevance": "One sentence why." }}
  ],
  "applicableSections": [
    {{ "act": "Short Act", "section": "Sec X — Title", "provision": "One sentence application." }}
  ],
  "relevantCaseLaws": [
    {{ "citation": "Party v Party, Court, Year", "court": "Court", "principle": "One sentence principle." }}
  ],
  "smartDefence": {{
    "overview": "One sentence overall strategy.",
    "pillars": [
      {{ "title": "Pillar name", "argument": "One sentence argument.", "legalBasis": "Cite", "strength": 80 }}
    ],
    "keyArguments": [
      {{ "argument": "One sentence courtroom argument.", "legalHook": "Section or case" }}
    ],
    "prosecutionCounters": ["Counter 1", "Counter 2", "Counter 3"],
    "evidenceRequired": ["Item 1", "Item 2", "Item 3"],
    "proceduralMoves": ["Move 1", "Move 2"]
  }},
  "possibleOutcomes": [
    {{ "type": "favorable", "outcome": "Brief outcome.", "likelihood": 65, "basis": "Legal basis." }},
    {{ "type": "adverse",   "outcome": "Brief outcome.", "likelihood": 25, "basis": "Legal basis." }},
    {{ "type": "neutral",   "outcome": "Brief outcome.", "likelihood": 50, "basis": "Legal basis." }}
  ],
  "litigationStrategy": ["Step 1", "Step 2", "Step 3", "Step 4"],
  "immediateActions": ["Action 1", "Action 2", "Action 3"],
  "keyRisks": ["Risk 1", "Risk 2", "Risk 3"]
}}

RULES:
- Client perspective: {client_side}
- Provide 3-4 applicable laws, 4-5 sections, 3-4 case laws
- All citations must be real, accurate {jurisdiction} law
- Pillar strength = integer 0-100
- Return ONLY the JSON object — nothing else"""


def _build_user_prompt(content: str, jurisdiction: str, legal_area: str, source_type: str) -> str:
    return (
        f"Jurisdiction: {jurisdiction}\n"
        f"Legal Area: {legal_area}\n"
        f"Source: {source_type}\n\n"
        f"{'CASE FILE CONTENT' if source_type == 'file' else 'SCENARIO'}:\n"
        f"{content[:settings.MAX_TEXT_CHARS]}"
    )


# ─────────────────────────────────────────────────────────────
#  LLM Service
# ─────────────────────────────────────────────────────────────

class LLMAnalysisResult:
    __slots__ = ("raw_result", "token_usage", "processing_time_ms", "llm_calls")

    def __init__(
        self,
        raw_result: dict[str, Any],
        token_usage: dict[str, int],
        processing_time_ms: int,
        llm_calls: int = 1,
    ) -> None:
        self.raw_result         = raw_result
        self.token_usage        = token_usage
        self.processing_time_ms = processing_time_ms
        self.llm_calls          = llm_calls


class LLMService:
    """Orchestrates calls to Claude and handles response parsing."""

    def __init__(self) -> None:
        self._client = get_anthropic_client()

    async def analyse(
        self,
        content: str,
        jurisdiction: str,
        legal_area: str,
        client_side: str,
        source_type: str,
    ) -> LLMAnalysisResult:
        """
        Call Claude, parse the JSON response, and return a structured result.
        Raises AnalysisFailedException on unrecoverable errors.
        """
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            jurisdiction=jurisdiction,
            source_type=source_type,
            client_side=client_side,
        )
        user_prompt = _build_user_prompt(content, jurisdiction, legal_area, source_type)

        start_time = time.perf_counter()

        try:
            message = await self._call_with_retry(system_prompt, user_prompt)
        except anthropic.APIConnectionError as e:
            raise AnthropicAPIException(f"Connection error: {e}") from e
        except anthropic.RateLimitError as e:
            raise AnthropicAPIException("Anthropic rate limit reached. Retry shortly.") from e
        except anthropic.APIStatusError as e:
            raise AnthropicAPIException(f"API error {e.status_code}: {e.message}") from e

        processing_time_ms = int((time.perf_counter() - start_time) * 1000)

        raw_text = "".join(
            block.text for block in message.content if hasattr(block, "text")
        )

        token_usage = {
            "input_tokens":  message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
            "total_tokens":  message.usage.input_tokens + message.usage.output_tokens,
        }

        logger.info(
            "LLM call completed",
            processing_ms=processing_time_ms,
            tokens=token_usage["total_tokens"],
            stop_reason=message.stop_reason,
        )

        parsed = self._robust_parse(raw_text)
        if parsed is None:
            raise AnalysisFailedException("Could not parse AI response after all repair attempts.")

        return LLMAnalysisResult(
            raw_result=parsed,
            token_usage=token_usage,
            processing_time_ms=processing_time_ms,
        )

    @retry(
        retry=retry_if_exception_type((anthropic.APIConnectionError, anthropic.InternalServerError)),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _call_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> anthropic.types.Message:
        return await self._client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=settings.ANTHROPIC_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

    # ── JSON Repair (4-layer) ────────────────────────────────

    def _robust_parse(self, raw: str) -> dict[str, Any] | None:
        if not raw:
            return None

        # Strip markdown fences
        s = re.sub(r"^```json\s*", "", raw, flags=re.IGNORECASE)
        s = re.sub(r"^```\s*",    "", s)
        s = re.sub(r"```\s*$",    "", s).strip()

        start = s.find("{")
        if start < 0:
            logger.warning("No JSON object found in LLM response")
            return None
        s = s[start:]

        # Layer 1 — direct parse
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass

        # Layer 2 — truncate to last valid closing brace
        depth, last_valid = 0, -1
        for i, ch in enumerate(s):
            if ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
                if depth == 0:
                    last_valid = i
        if last_valid > 0:
            try:
                return json.loads(s[: last_valid + 1])
            except json.JSONDecodeError:
                pass

        # Layer 3 — aggressive repair
        repaired = s
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)   # trailing commas
        if (repaired.count('"') % 2) != 0:
            repaired += '"'                                    # close open string

        stack: list[str] = []
        for ch in repaired:
            if ch in "{[":
                stack.append(ch)
            elif ch in "}]" and stack:
                stack.pop()
        while stack:
            repaired += "}" if stack.pop() == "{" else "]"
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)

        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        # Layer 4 — regex fallback (partial result)
        logger.warning("JSON repair exhausted — using regex field extraction")
        return self._extract_fields_fallback(raw)

    @staticmethod
    def _extract_fields_fallback(raw: str) -> dict[str, Any]:
        def get_str(key: str) -> str:
            m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', raw, re.IGNORECASE)
            return m.group(1) if m else ""

        def get_arr(key: str) -> list[str]:
            m = re.search(rf'"{key}"\s*:\s*\[([^\]]*?)\]', raw, re.IGNORECASE | re.DOTALL)
            if not m:
                return []
            return [x.group(1) for x in re.finditer(r'"([^"]*)"', m.group(1))]

        return {
            "caseTitle":        get_str("caseTitle") or "Legal Analysis",
            "legalAreas":       get_arr("legalAreas"),
            "scenarioSummary":  get_str("scenarioSummary") or "Partial analysis — please retry.",
            "jurisdiction":     get_str("jurisdiction"),
            "sourceType":       get_str("sourceType"),
            "applicableLaws":    [],
            "applicableSections": [],
            "relevantCaseLaws":  [],
            "smartDefence": {
                "overview":            "Retry for complete defence strategy.",
                "pillars":             [],
                "keyArguments":        [],
                "prosecutionCounters": [],
                "evidenceRequired":    [],
                "proceduralMoves":     [],
            },
            "possibleOutcomes":   [],
            "litigationStrategy": get_arr("litigationStrategy"),
            "immediateActions":   get_arr("immediateActions"),
            "keyRisks":           get_arr("keyRisks"),
        }
