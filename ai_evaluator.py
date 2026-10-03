"""AI Evaluator Module integrating with 9Router (OpenAI-compatible gateway)."""

import re
import json
import time
import httpx
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from config import AppConfig


def extract_json_from_llm(content: str) -> Dict[str, Any]:
    """Robustly extracts JSON object from LLM output, handling markdown fences or leading/trailing prose."""
    content = content.strip()
    try:
        return json.loads(content)
    except Exception:
        pass

    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass

    m2 = re.search(r"(\{.*\})", content, re.DOTALL)
    if m2:
        try:
            return json.loads(m2.group(1))
        except Exception:
            pass

    raise ValueError(f"Could not parse valid JSON from response: {content[:150]}")


def normalize_ai_payload(parsed: Dict[str, Any]) -> Dict[str, Any]:
    decision = str(parsed.get("decision", "")).upper()
    decision_map = {
        "NO_TRADE": "SKIP",
        "NO-TRADE": "SKIP",
        "NOTRADE": "SKIP",
        "REJECT": "SKIP",
        "REJECTED": "SKIP",
        "PASS": "SKIP",
        "NONE": "SKIP",
        "HOLD": "WAIT",
        "NEUTRAL": "WAIT",
        "SHORT": "ENTER_SHORT",
        "SELL": "ENTER_SHORT",
        "ENTER": "ENTER_SHORT",
    }
    decision = decision_map.get(decision, decision)
    if decision not in {"ENTER_SHORT", "WAIT", "SKIP"}:
        raise ValueError(f"unsupported decision: {decision or 'missing'}")
    raw = parsed.get("confidence", parsed.get("confidence_score", 0))
    if isinstance(raw, str):
        raw_str = raw.strip().lower().replace("%", "")
        text_map = {
            "very high": 90, "high": 80, "moderate": 65, "medium": 65,
            "neutral": 50, "low": 35, "very low": 20
        }
        if raw_str in text_map:
            confidence = text_map[raw_str]
        else:
            try:
                val = float(raw_str)
                if 0 <= val <= 1.0:
                    val *= 100
                confidence = int(round(val))
            except ValueError:
                confidence = 50
    elif isinstance(raw, (int, float)):
        if 0 <= raw <= 1.0:
            raw *= 100
        confidence = int(round(raw))
    else:
        confidence = 50
    confidence = max(0, min(100, confidence))
    key_evidence = str(parsed.get("key_evidence", parsed.get("reasoning", parsed.get("evidence", ""))))
    risk_factors = str(parsed.get("risk_factors", parsed.get("risks", parsed.get("risk_assessment", ""))))
    return {
        **parsed,
        "decision": decision,
        "confidence": confidence,
        "key_evidence": key_evidence,
        "risk_factors": risk_factors
    }


def aggregate_usage(usages: list[Dict[str, Any]]) -> Dict[str, int]:
    return {key: sum(int(item.get(key, 0) or 0) for item in usages) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}


def estimate_batch_budget(candidate_count: int, deep_candidate_count: int = 3) -> Dict[str, int]:
    triage = max(0, min(candidate_count, 12))
    deep = max(0, min(deep_candidate_count, 3))
    return {"max_calls": 1 + (deep * 2) + 1, "deep_candidate_count": deep, "estimated_total_tokens": 7000 + triage * 450 + deep * 4800}


def build_snapshot_prompt(candidates: list[Dict[str, Any]]) -> str:
    return "Return strict JSON. Evaluate short thesis versus squeeze risk using funding_rate, open interest, depth and multi-timeframe data. " + json.dumps(candidates, separators=(",", ":"))


def build_adversarial_prompt(candidate: Dict[str, Any], role: str) -> str:
    symbol = candidate.get("symbol", "UNKNOWN")
    return (
        f"You are the {role} in an automated crypto shorting risk engine.\n"
        f"Evaluate this asset setup for an optimal short entry or whether to wait/skip.\n"
        f"Candidate Setup: {json.dumps(candidate, separators=(',', ':'))}\n\n"
        f"Output REQUIREMENT: You MUST respond ONLY with a raw JSON object (no markdown, no code blocks, no prose):\n"
        f'{{"symbol": "{symbol}", "decision": "ENTER_SHORT" | "WAIT" | "SKIP", "confidence": <int 0-100>, '
        f'"setup_type": "PUMP_EXHAUSTION" | "BREAKDOWN_RETEST" | "NONE", "key_evidence": "<reason>", "risk_factors": "<risks>"}}'
    )


class AIEvaluationResult(BaseModel):
    symbol: str
    decision: str = Field(description="ENTER_SHORT, WAIT, or SKIP")
    confidence: int = Field(default=0, ge=0, le=100)
    setup_type: str = "NONE"
    key_evidence: str = ""
    risk_factors: str = ""
    raw_response: str = ""
    is_valid: bool = False
    error_message: str = ""
    usage: Dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0

class AIEvaluator:
    def __init__(self, config: AppConfig):
        self.config = config
        self.url = f"{config.ai_gateway_url.rstrip('/')}/chat/completions"
        self.client = httpx.Client(timeout=30.0)

    def _chat_call(self, prompt: str, system_prompt: str = "You are a quantitative trading risk engine. Always output pure valid JSON.") -> tuple[Dict[str, Any], Dict[str, Any], float]:
        payload = {
            "model": self.config.ai_model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 250,
            "stream": False
        }
        t0 = time.perf_counter()
        resp = self.client.post(self.url, json=payload)
        dt = (time.perf_counter() - t0) * 1000
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}: {resp.text}")
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = normalize_ai_payload(extract_json_from_llm(content))
        usage = data.get("usage", {}) if isinstance(data.get("usage", {}), dict) else {}
        return parsed, usage, dt

    def evaluate_adversarial(self, candidate_payload: Dict[str, Any]) -> AIEvaluationResult:
        symbol = str(candidate_payload.get("symbol", "UNKNOWN"))
        roles = [
            "Short Hunter looking for exhaustion, buyer dry-up, and lower highs",
            "Squeeze Defender looking for continuation, crowded short traps, and momentum",
            "Execution Arbiter. Strategy note: in pump exhaustion trading, entries occur at the top during buyer exhaustion / upper wick rejection, NOT after the price has already dumped. If rejection wick and buyer dry-up are visible after a pump or overextension, authorize ENTER_SHORT",
        ]
        usages: list[Dict[str, Any]] = []
        total_latency = 0.0
        last_parsed: Dict[str, Any] = {"decision": "SKIP", "confidence": 0}
        try:
            for role in roles:
                prompt = build_adversarial_prompt(candidate_payload, role)
                parsed, usage, dt = self._chat_call(prompt)
                usages.append(usage)
                total_latency += dt
                last_parsed = parsed
            decision = last_parsed["decision"]
            confidence = int(last_parsed.get("confidence", 0))
            if decision == "ENTER_SHORT" and confidence < 70:
                decision = "WAIT"
            return AIEvaluationResult(
                symbol=symbol,
                decision=decision,
                confidence=confidence,
                setup_type=str(last_parsed.get("setup_type", "NONE")),
                key_evidence=str(last_parsed.get("key_evidence", "")),
                risk_factors=str(last_parsed.get("risk_factors", "")),
                raw_response=json.dumps(last_parsed),
                is_valid=True,
                usage=aggregate_usage(usages),
                latency_ms=total_latency,
            )
        except Exception as exc:
            return AIEvaluationResult(
                symbol=symbol,
                decision="SKIP",
                confidence=0,
                error_message=f"adversarial_error: {str(exc)}",
                is_valid=False,
                usage=aggregate_usage(usages),
                latency_ms=total_latency,
            )

    def evaluate_candidate(
        self,
        symbol: str,
        price_change_24h: float,
        current_price: float,
        klines_summary: list,
        spread_pct: float,
        market_features: Optional[Dict[str, Any]] = None
    ) -> AIEvaluationResult:
        """
        Sends structured market setup to 9Router.
        Fails closed (returns SKIP/WAIT) on timeout, network error, or invalid JSON.
        """
        prompt = (
            f"You are a quantitative crypto trading analyst specializing in Short-Only Perpetual setups.\n"
            f"Evaluate whether the following asset exhibits valid short opportunities such as 'PUMP_EXHAUSTION' (buyer exhaustion, upper rejection wick, drop in buying volume after pump) "
            f"or 'BREAKDOWN_RETEST' suitable for a SHORT entry.\n\n"
            f"Asset Data:\n"
            f"- Symbol: {symbol}\n"
            f"- Current Price: {current_price}\n"
            f"- 24h Price Change: {price_change_24h}%\n"
            f"- Spread: {spread_pct}%\n"
            f"- Recent 15m Closes: {klines_summary[-5:] if klines_summary else 'N/A'}\n"
            f"- Deterministic Market Features (includes Fibonacci levels, impulse wave metrics, and funding sentiment): {json.dumps(market_features or {}, separators=(',', ':'))}\n\n"
            f"Guidance:\n"
            f"- Fibonacci Context: Best short risk-to-reward occurs at PEAK_EXHAUSTION (near swing high, retracement < 0.236) or BLOW_OFF_EXTENSION with upper wick rejection. If retracement > 0.618 or in EXTENDED_DUMP, do NOT short the bottom (recommend WAIT or SKIP).\n"
            f"- Impulse Wave & Volume: Check if impulse_wave shows volume fade or confluent upper wick rejections across 15m/1h.\n"
            f"- Funding Sentiment: EXTREME_LONG_CROWD confirms retail longs are overleveraged, providing strong downward dump fuel.\n"
            f"- If price shows signs of seller emergence, buyer dry-up, or local exhaustion, recommend ENTER_SHORT with realistic confidence (60-95).\n"
            f"- If momentum is still strongly upward without rejection, recommend WAIT.\n"
            f"- If market is too illiquid or high risk, recommend SKIP.\n\n"
            f"Output REQUIREMENT: You MUST respond ONLY with a raw JSON object (no markdown, no code blocks, no prose):\n"
            f'{{"symbol": "{symbol}", "decision": "ENTER_SHORT" | "WAIT" | "SKIP", "confidence": <int 0-100>, '
            f'"setup_type": "PUMP_EXHAUSTION" | "BREAKDOWN_RETEST" | "NONE", "key_evidence": "<short reason>", "risk_factors": "<risks>"}}'
        )

        payload = {
            "model": self.config.ai_model_name,
            "messages": [
                {"role": "system", "content": "You are a quantitative trading risk engine. Always output pure valid JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 250,
            "stream": False
        }

        started = time.perf_counter()
        try:
            resp = self.client.post(self.url, json=payload)
            latency_ms = (time.perf_counter() - started) * 1000
            if resp.status_code != 200:
                return AIEvaluationResult(
                    symbol=symbol,
                    decision="SKIP",
                    confidence=0,
                    error_message=f"9Router returned HTTP {resp.status_code}",
                    raw_response=resp.text,
                    is_valid=False,
                    latency_ms=latency_ms
                )

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = normalize_ai_payload(extract_json_from_llm(content))
            usage = data.get("usage", {}) if isinstance(data.get("usage", {}), dict) else {}
            decision = parsed["decision"]
            confidence = parsed["confidence"]
            # Quality gate: minimum 70% confidence for ENTER_SHORT
            if decision == "ENTER_SHORT" and confidence < 70:
                decision = "WAIT"

            return AIEvaluationResult(
                symbol=symbol,
                decision=decision,
                confidence=confidence,
                setup_type=str(parsed.get("setup_type", "NONE")),
                key_evidence=str(parsed.get("key_evidence", "")),
                risk_factors=str(parsed.get("risk_factors", "")),
                raw_response=content,
                is_valid=True,
                usage=usage,
                latency_ms=latency_ms
            )

        except httpx.TimeoutException:
            # Fail closed on timeout
            return AIEvaluationResult(
                symbol=symbol,
                decision="SKIP",
                confidence=0,
                error_message="9Router request timed out (>8.0s cutoff). Fail-closed to SKIP.",
                is_valid=False
            )
        except Exception as e:
            # Fail closed on parsing or connection error
            return AIEvaluationResult(
                symbol=symbol,
                decision="SKIP",
                confidence=0,
                error_message=f"Failed to parse or connect: {str(e)}",
                is_valid=False
            )
