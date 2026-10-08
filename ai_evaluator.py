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
        "LONG": "ENTER_LONG",
        "BUY": "ENTER_LONG",
        "ENTER_LONG": "ENTER_LONG",
    }
    decision = decision_map.get(decision, decision)
    if decision not in {"ENTER_SHORT", "ENTER_LONG", "WAIT", "SKIP"}:
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


def estimate_batch_budget(candidate_count: int, deep_candidate_count: int = 2) -> Dict[str, int]:
    triage = max(0, min(candidate_count, 12))
    deep = max(0, min(deep_candidate_count, 3))
    return {"max_calls": 1 + deep, "deep_candidate_count": deep, "estimated_total_tokens": 500 + triage * 80 + deep * 800}


def build_snapshot_prompt(candidates: list[Dict[str, Any]]) -> str:
    return "Return strict JSON. Evaluate short thesis versus squeeze risk using funding_rate, open interest, depth and multi-timeframe data. " + json.dumps(candidates, separators=(",", ":"))


def build_batch_triage_prompt(candidate_summaries: list[Dict[str, Any]], direction: str = "SHORT") -> str:
    direction_upper = direction.upper()
    return (
        f"You are an institutional crypto quantitative analyst performing rapid comparative triage across multiple screened candidates.\n"
        f"Strategy Target: {direction_upper} setups among recently pumped or volatile tokens.\n\n"
        f"Available Actions per candidate:\n"
        f"- DEEP_ANALYZE: Strongest immediate setups showing top exhaustion, buyer dry-up, or clean breakdown. (Cap: select at most 2 finalists).\n"
        f"- WATCH: High-quality setup that is currently premature (e.g. still ascending into resistance, needs further reversal/wick confirmation before entry).\n"
        f"- SKIP: Weak setup, high squeeze danger, low volume, or poor risk:reward.\n\n"
        f"Screened Candidates:\n{json.dumps(candidate_summaries, separators=(',', ':'))}\n\n"
        f"Output REQUIREMENT: You MUST respond ONLY with a raw JSON object (no markdown, no code blocks, no prose):\n"
        f'{{"ranked_candidates": [{{"symbol": "<symbol>", "rank": 1, "action": "DEEP_ANALYZE" | "WATCH" | "SKIP", '
        f'"conviction_score": <int 0-100>, "triage_reason": "<short comparative reason>"}}], '
        f'"selected_finalists": ["<symbol>"]}}'
    )


def normalize_batch_triage_payload(parsed: Dict[str, Any]) -> Dict[str, Any]:
    raw_list = parsed.get("ranked_candidates", [])
    if not isinstance(raw_list, list):
        if isinstance(parsed, list):
            raw_list = parsed
        else:
            raw_list = []

    action_map = {
        "DEEP": "DEEP_ANALYZE",
        "DEEP_ANALYZE": "DEEP_ANALYZE",
        "ANALYZE": "DEEP_ANALYZE",
        "ENTER": "DEEP_ANALYZE",
        "ENTER_SHORT": "DEEP_ANALYZE",
        "ENTER_LONG": "DEEP_ANALYZE",
        "WATCH": "WATCH",
        "WAIT": "WATCH",
        "MONITOR": "WATCH",
        "WATCHLIST": "WATCH",
        "SKIP": "SKIP",
        "PASS": "SKIP",
        "REJECT": "SKIP",
        "NO_TRADE": "SKIP",
    }

    normalized_candidates = []
    for idx, item in enumerate(raw_list):
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol", "")).strip().upper()
        if not sym:
            continue
        raw_act = str(item.get("action", item.get("decision", "SKIP"))).strip().upper()
        act = action_map.get(raw_act, "SKIP")

        raw_score = item.get("conviction_score", item.get("confidence", item.get("score", 50)))
        score_val = 50
        try:
            score_val = int(raw_score)
        except Exception:
            try:
                score_val = int(float(str(raw_score).replace("%", "")))
            except Exception:
                score_val = 50
        score_val = max(0, min(100, score_val))

        normalized_candidates.append({
            "symbol": sym,
            "rank": int(item.get("rank", idx + 1)),
            "action": act,
            "conviction_score": score_val,
            "triage_reason": str(item.get("triage_reason", item.get("reason", ""))).strip(),
        })

    normalized_candidates.sort(key=lambda x: x["rank"])

    raw_finalists = parsed.get("selected_finalists", [])
    finalists: list[str] = []
    if isinstance(raw_finalists, list):
        for f in raw_finalists:
            fsym = str(f).strip().upper()
            if fsym and fsym not in finalists:
                finalists.append(fsym)

    if not finalists:
        for c in normalized_candidates:
            if c["action"] == "DEEP_ANALYZE":
                finalists.append(c["symbol"])
                if len(finalists) >= 2:
                    break

    finalists = finalists[:2]

    return {
        "ranked_candidates": normalized_candidates,
        "selected_finalists": finalists
    }


def build_structured_deep_prompt(candidate: Dict[str, Any], direction: str = "SHORT") -> str:
    symbol = candidate.get("symbol", "UNKNOWN")
    dir_target = direction.upper()
    return (
        f"You are the Lead Quantitative Risk Arbiter for an automated perpetual futures strategy targeting {dir_target} setups.\n"
        f"Perform a dual-thesis dialectical evaluation for this screened finalist before entry authorization.\n\n"
        f"Candidate Detailed Setup:\n{json.dumps(candidate, separators=(',', ':'))}\n\n"
        f"Evaluation Directives:\n"
        f"1. Bull Thesis (Squeeze Defender): Identify buyer momentum, breakout risks, negative funding squeeze traps, or lack of clear rejection.\n"
        f"2. Bear Thesis (Short Hunter): Identify buyer dry-up, upper wick rejections, volume divergence, or resistance breaks.\n"
        f"3. Synthesis Decision:\n"
        f"   - Authorize ENTER_{dir_target} ONLY if evidence shows clear exhaustion / structural edge with confidence >= 70.\n"
        f"   - If setup is promising but needs further price action, return WAIT.\n"
        f"   - If continuation or squeeze risk dominates, return SKIP.\n\n"
        f"Output REQUIREMENT: You MUST respond ONLY with a raw JSON object (no markdown, no code blocks, no prose):\n"
        f'{{"symbol": "{symbol}", "decision": "ENTER_SHORT" | "ENTER_LONG" | "WAIT" | "SKIP", "confidence": <int 0-100>, '
        f'"setup_type": "PUMP_EXHAUSTION" | "BREAKDOWN_RETEST" | "MOMENTUM_PULLBACK" | "NONE", '
        f'"bull_thesis": "<squeeze defender argument>", '
        f'"bear_thesis": "<short hunter argument>", '
        f'"key_evidence": "<synthesized decisive reason>", '
        f'"risk_factors": "<dominant risks>"}}'
    )


class TriageCandidate(BaseModel):
    symbol: str
    rank: int = 1
    action: str = Field(default="SKIP", description="DEEP_ANALYZE, WATCH, or SKIP")
    conviction_score: int = Field(default=0, ge=0, le=100)
    triage_reason: str = ""


class BatchTriageResult(BaseModel):
    ranked_candidates: list[TriageCandidate] = Field(default_factory=list)
    selected_finalists: list[str] = Field(default_factory=list)
    raw_response: str = ""
    is_valid: bool = False
    error_message: str = ""
    usage: Dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0


class AIEvaluationResult(BaseModel):
    symbol: str
    decision: str = Field(description="ENTER_SHORT, ENTER_LONG, WAIT, or SKIP")
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

    def _chat_call_raw(
        self,
        prompt: str,
        system_prompt: str = "You are a quantitative trading risk engine. Always output pure valid JSON.",
        max_tokens: int = 650
    ) -> tuple[Dict[str, Any], Dict[str, Any], float]:
        payload = {
            "model": self.config.ai_model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "stream": False
        }
        t0 = time.perf_counter()
        resp = self.client.post(self.url, json=payload)
        dt = (time.perf_counter() - t0) * 1000
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}: {resp.text}")
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = extract_json_from_llm(content)
        usage = data.get("usage", {}) if isinstance(data.get("usage", {}), dict) else {}
        return parsed, usage, dt

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

    def evaluate_batch_triage(
        self,
        candidate_summaries: list[Dict[str, Any]],
        direction: str = "SHORT"
    ) -> BatchTriageResult:
        """
        Tier 1: Evaluates multiple screened candidates in a single LLM call for comparative ranking.
        Categorizes each into DEEP_ANALYZE, WATCH, or SKIP, and selects up to 2 finalists.
        """
        if not candidate_summaries:
            return BatchTriageResult(
                ranked_candidates=[],
                selected_finalists=[],
                is_valid=True
            )

        prompt = build_batch_triage_prompt(candidate_summaries, direction=direction)
        try:
            parsed, usage, dt = self._chat_call_raw(prompt, max_tokens=650)
            normalized = normalize_batch_triage_payload(parsed)
            candidates = [TriageCandidate(**c) for c in normalized["ranked_candidates"]]
            return BatchTriageResult(
                ranked_candidates=candidates,
                selected_finalists=normalized["selected_finalists"],
                raw_response=json.dumps(parsed),
                is_valid=True,
                usage=usage,
                latency_ms=dt
            )
        except Exception as exc:
            return BatchTriageResult(
                ranked_candidates=[],
                selected_finalists=[],
                error_message=f"batch_triage_error: {str(exc)}",
                is_valid=False,
                latency_ms=0.0
            )

    def evaluate_deep_candidate(
        self,
        candidate_payload: Dict[str, Any],
        direction: str = "SHORT"
    ) -> AIEvaluationResult:
        """
        Tier 2: Single structured deep call evaluating both Bull (Defender) and Bear (Hunter) theses
        in a unified dialectic prompt. Replaces the 3-call adversarial loop with 1 comprehensive call.
        """
        symbol = str(candidate_payload.get("symbol", "UNKNOWN"))
        prompt = build_structured_deep_prompt(candidate_payload, direction=direction)
        try:
            parsed, usage, dt = self._chat_call_raw(prompt, max_tokens=450)
            normalized = normalize_ai_payload(parsed)
            decision = normalized["decision"]
            confidence = int(normalized.get("confidence", 0))
            if decision in ("ENTER_SHORT", "ENTER_LONG") and confidence < 70:
                decision = "WAIT"

            evidence = normalized.get("key_evidence", "")
            bull_t = parsed.get("bull_thesis", "")
            bear_t = parsed.get("bear_thesis", "")
            if bull_t or bear_t:
                evidence = f"[Dual-Thesis] Bear: {bear_t} | Bull: {bull_t} => {evidence}"

            return AIEvaluationResult(
                symbol=symbol,
                decision=decision,
                confidence=confidence,
                setup_type=str(normalized.get("setup_type", "NONE")),
                key_evidence=evidence[:400],
                risk_factors=str(normalized.get("risk_factors", "")),
                raw_response=json.dumps(parsed),
                is_valid=True,
                usage=usage,
                latency_ms=dt,
            )
        except Exception as exc:
            return AIEvaluationResult(
                symbol=symbol,
                decision="SKIP",
                confidence=0,
                error_message=f"deep_eval_error: {str(exc)}",
                is_valid=False,
                latency_ms=0.0,
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
            f"You are a quantitative crypto trading analyst specializing in Short-Only and Long Perpetual setups.\n"
            f"Evaluate whether the following asset exhibits valid trade opportunities such as 'PUMP_EXHAUSTION' (buyer exhaustion, upper rejection wick, drop in buying volume after pump), "
            f"'BREAKDOWN_RETEST' suitable for a SHORT entry, or healthy pullback bounce suitable for a LONG entry.\n\n"
            f"Asset Data:\n"
            f"- Symbol: {symbol}\n"
            f"- Current Price: {current_price}\n"
            f"- 24h Price Change: {price_change_24h}%\n"
            f"- Spread: {spread_pct}%\n"
            f"- Recent 15m Closes: {klines_summary[-5:] if klines_summary else 'N/A'}\n"
            f"- Deterministic Market Features (includes Fibonacci levels, impulse wave metrics, RSI, Bollinger Bands, EMA trend, and funding sentiment): {json.dumps(market_features or {}, separators=(',', ':'))}\n\n"
            f"Guidance:\n"
            f"- Fibonacci Context: Best short risk-to-reward occurs at PEAK_EXHAUSTION (near swing high, retracement < 0.236) or BLOW_OFF_EXTENSION with upper wick rejection. If retracement > 0.618 or in EXTENDED_DUMP, do NOT short the bottom (recommend WAIT or SKIP).\n"
            f"- RSI & Divergence: BEARISH_DIV (price higher high with RSI lower high) or overbought RSI (>70) strongly confirms SHORT exhaustion. BULLISH_DIV or oversold RSI (<30) confirms LONG bounce.\n"
            f"- Bollinger Bands: percent_b >= 1.0 (price outside upper band) confirms blow-off top overextension for short mean-reversion. percent_b <= 0.0 confirms oversold bounce.\n"
            f"- EMA Trend: Respect macro trend; if STRONG_UPTREND, require strict exhaustion or rejection wick before shorting.\n"
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
            # Quality gate: minimum 70% confidence for ENTER_SHORT and ENTER_LONG
            if decision in ("ENTER_SHORT", "ENTER_LONG") and confidence < 70:
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
