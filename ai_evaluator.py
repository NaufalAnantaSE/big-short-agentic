"""AI Evaluator Module integrating with 9Router (OpenAI-compatible gateway)."""

import re
import json
import time
import httpx
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, model_validator

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


def compact_candidate_summary(cand: Dict[str, Any], default_direction: str = "SHORT") -> Dict[str, Any]:
    if not isinstance(cand, dict):
        return {}
    sym = str(cand.get("symbol", "")).strip().upper()
    allowed_dirs = cand.get("allowed_directions")
    if not allowed_dirs:
        dir_upper = default_direction.upper()
        allowed_dirs = [dir_upper] if dir_upper in ("LONG", "SHORT") else ["LONG", "SHORT"]

    essential_keys = (
        "current_price",
        "price_change_24h",
        "spread_pct",
        "atr_pct",
        "rsi_15m",
        "funding_rate",
        "volume_sma_ratio",
        "fib_zone",
        "playbook_matched",
        "price",
        "change_24h",
        "rsi",
        "vol_ratio",
        "funding",
        "playbook",
    )
    compacted: Dict[str, Any] = {
        "symbol": sym,
        "allowed_directions": allowed_dirs,
    }
    for k in essential_keys:
        if k in cand and cand[k] is not None:
            compacted[k] = cand[k]

    return compacted


def build_batch_triage_prompt(candidate_summaries: list[Dict[str, Any]], direction: str = "SHORT") -> str:
    direction_upper = direction.upper()
    strategy_target = f"{direction_upper} setups" if direction_upper != "BOTH" else "BOTH (evaluating both LONG and SHORT setups)"
    compact_candidates = [
        compact_candidate_summary(c, default_direction=direction)
        for c in candidate_summaries
        if isinstance(c, dict) and c.get("symbol")
    ]
    return (
        f"You are an institutional crypto quantitative analyst performing rapid comparative triage across multiple screened candidates.\n"
        f"Strategy Target: {strategy_target} among recently pumped or volatile tokens.\n\n"
        f"Available Actions per candidate:\n"
        f"- DEEP_ANALYZE: Strongest immediate setups showing top exhaustion, buyer dry-up, or clean breakdown/bounce. (Cap: select at most 2 finalists).\n"
        f"- WATCH: High-quality setup that is currently premature (e.g. still ascending into resistance or basing into support, needs further reversal/wick confirmation before entry).\n"
        f"- SKIP: Weak setup, high squeeze danger, low volume, or poor risk:reward.\n\n"
        f"Rules:\n"
        f"1. suggested_direction MUST be one of candidate's allowed_directions (UNKNOWN is permitted ONLY for SKIP).\n"
        f"2. selected_finalists must contain at most 2 candidates (Cap 2) and each finalist MUST have action DEEP_ANALYZE.\n\n"
        f"Screened Candidates:\n{json.dumps(compact_candidates, separators=(',', ':'))}\n\n"
        f"Output REQUIREMENT: You MUST respond ONLY with a raw JSON object (no markdown, no code blocks, no prose):\n"
        f'{{"ranked_candidates": [{{"symbol": "<symbol>", "rank": 1, "action": "DEEP_ANALYZE" | "WATCH" | "SKIP", '
        f'"suggested_direction": "LONG" | "SHORT" | "UNKNOWN", '
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

        raw_sugg = str(item.get("suggested_direction", item.get("direction", "UNKNOWN"))).strip().upper()
        if raw_sugg in ("LONG", "SHORT"):
            suggested_dir = raw_sugg
        else:
            suggested_dir = "UNKNOWN"

        normalized_candidates.append({
            "symbol": sym,
            "rank": int(item.get("rank", idx + 1)),
            "action": act,
            "suggested_direction": suggested_dir,
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


def validate_batch_triage_payload(
    candidate_summaries: list[Dict[str, Any]],
    normalized: Dict[str, Any],
    direction: str = "SHORT"
) -> tuple[bool, Optional[str]]:
    """
    Validates normalized batch triage payload against input candidate summaries:
    - Empty response to nonempty input fails closed.
    - Unknown symbols (not present in candidate_summaries) fail closed.
    - Duplicate symbols in ranked_candidates or selected_finalists fail closed.
    - Finalists not correctly ranked DEEP_ANALYZE fail closed.
    - Disallowed directions fail closed (UNKNOWN permitted only for SKIP).
    """
    ranked = normalized.get("ranked_candidates", [])
    if candidate_summaries and not ranked:
        return False, "Malformed empty triage response for nonempty candidate input"

    cand_map: Dict[str, list[str]] = {}
    default_allowed = [direction.upper()] if direction.upper() in ("LONG", "SHORT") else ["LONG", "SHORT"]
    for c in candidate_summaries:
        if isinstance(c, dict):
            sym = str(c.get("symbol", "")).strip().upper()
            if sym:
                dirs = c.get("allowed_directions") or default_allowed
                if isinstance(dirs, str):
                    dirs = [dirs]
                elif not isinstance(dirs, (list, tuple, set)):
                    dirs = default_allowed
                cand_map[sym] = [str(d).strip().upper() for d in dirs]

    seen_symbols = set()
    symbol_to_action: Dict[str, str] = {}
    for cand in ranked:
        sym = cand.get("symbol", "")
        if sym not in cand_map:
            return False, f"Unknown symbol in triage response: {sym}"
        if sym in seen_symbols:
            return False, f"Duplicate symbol in triage response: {sym}"
        seen_symbols.add(sym)
        act = cand.get("action", "SKIP")
        symbol_to_action[sym] = act

        sugg_dir = str(cand.get("suggested_direction", "UNKNOWN")).strip().upper()
        allowed = cand_map[sym]
        if act == "SKIP":
            if sugg_dir != "UNKNOWN" and sugg_dir not in allowed:
                return False, f"Disallowed direction {sugg_dir} for SKIP symbol {sym} (allowed: {allowed})"
        else:
            if sugg_dir not in allowed:
                return False, f"Disallowed direction {sugg_dir} for {act} symbol {sym} (allowed: {allowed})"

    finalists = normalized.get("selected_finalists", [])
    seen_finalists = set()
    for f in finalists:
        fsym = str(f).strip().upper()
        if fsym not in cand_map:
            return False, f"Unknown symbol in selected_finalists: {fsym}"
        if fsym in seen_finalists:
            return False, f"Duplicate symbol in selected_finalists: {fsym}"
        seen_finalists.add(fsym)

        act = symbol_to_action.get(fsym)
        if act != "DEEP_ANALYZE":
            return False, f"Finalist {fsym} is not correctly ranked DEEP_ANALYZE (action: {act})"

    return True, None


def build_structured_deep_prompt(candidate: Dict[str, Any], direction: str = "SHORT") -> str:
    symbol = candidate.get("symbol", "UNKNOWN")
    dir_target = direction.upper()
    if dir_target == "BOTH":
        target_str = "evaluating both LONG and SHORT"
        synthesis_auth = (
            "Authorize ENTER_LONG for valid long setups OR ENTER_SHORT for valid short setups "
            "ONLY if evidence shows clear exhaustion / structural edge with confidence >= 70."
        )
    elif dir_target == "LONG":
        target_str = "LONG"
        synthesis_auth = "Authorize ENTER_LONG ONLY if evidence shows clear exhaustion / structural edge with confidence >= 70."
    else:
        target_str = "SHORT"
        synthesis_auth = "Authorize ENTER_SHORT ONLY if evidence shows clear exhaustion / structural edge with confidence >= 70."

    return (
        f"You are the Lead Quantitative Risk Arbiter for an automated perpetual futures strategy targeting {target_str} setups.\n"
        f"Perform a dual-thesis dialectical evaluation for this screened finalist before entry authorization.\n\n"
        f"Candidate Detailed Setup:\n{json.dumps(candidate, separators=(',', ':'))}\n\n"
        f"Evaluation Directives:\n"
        f"1. Bull Thesis (Squeeze Defender): Identify buyer momentum, breakout risks, negative funding squeeze traps, or lack of clear rejection.\n"
        f"2. Bear Thesis (Short Hunter): Identify buyer dry-up, upper wick rejections, volume divergence, or resistance breaks.\n"
        f"3. Synthesis Decision:\n"
        f"   - {synthesis_auth}\n"
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
    suggested_direction: str = Field(default="UNKNOWN", description="LONG, SHORT, or UNKNOWN")
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
    error_type: Optional[str] = None
    attempts: int = 1

    @model_validator(mode="before")
    @classmethod
    def _handle_attempt_alias(cls, values: Any) -> Any:
        if isinstance(values, dict) and "attempt" in values and "attempts" not in values:
            values["attempts"] = values.pop("attempt")
        return values

    @property
    def attempt(self) -> int:
        return self.attempts


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
        max_tokens: int = 650,
        timeout: Optional[Any] = None,
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
        post_kwargs: Dict[str, Any] = {"json": payload}
        if timeout is not None:
            post_kwargs["timeout"] = timeout
        resp = self.client.post(self.url, **post_kwargs)
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
        batch_timeout = httpx.Timeout(60.0, connect=10.0, read=60.0)
        t0 = time.perf_counter()
        try:
            parsed, usage, dt = self._chat_call_raw(prompt, max_tokens=650, timeout=batch_timeout)
            normalized = normalize_batch_triage_payload(parsed)
            is_valid, val_err = validate_batch_triage_payload(candidate_summaries, normalized, direction=direction)
            if not is_valid:
                return BatchTriageResult(
                    ranked_candidates=[],
                    selected_finalists=[],
                    raw_response=json.dumps(parsed),
                    is_valid=False,
                    error_message=f"batch_triage_validation_error: {val_err}",
                    error_type="VALIDATION_ERROR",
                    usage=usage,
                    latency_ms=dt,
                    attempts=1
                )
            candidates = [TriageCandidate(**c) for c in normalized["ranked_candidates"]]
            return BatchTriageResult(
                ranked_candidates=candidates,
                selected_finalists=normalized["selected_finalists"],
                raw_response=json.dumps(parsed),
                is_valid=True,
                usage=usage,
                latency_ms=dt,
                attempts=1,
                error_type=None
            )
        except httpx.ConnectTimeout as exc:
            dt = (time.perf_counter() - t0) * 1000
            return BatchTriageResult(
                ranked_candidates=[],
                selected_finalists=[],
                error_message=f"batch_triage_error: Connect timeout ({str(exc)})",
                error_type="CONNECT_TIMEOUT",
                is_valid=False,
                latency_ms=dt,
                attempts=1
            )
        except httpx.ReadTimeout as exc:
            dt = (time.perf_counter() - t0) * 1000
            return BatchTriageResult(
                ranked_candidates=[],
                selected_finalists=[],
                error_message=f"batch_triage_error: Read timeout ({str(exc)})",
                error_type="READ_TIMEOUT",
                is_valid=False,
                latency_ms=dt,
                attempts=1
            )
        except httpx.TimeoutException as exc:
            dt = (time.perf_counter() - t0) * 1000
            return BatchTriageResult(
                ranked_candidates=[],
                selected_finalists=[],
                error_message=f"batch_triage_error: Request timed out ({str(exc)})",
                error_type="TIMEOUT",
                is_valid=False,
                latency_ms=dt,
                attempts=1
            )
        except Exception as exc:
            dt = (time.perf_counter() - t0) * 1000
            err_str = str(exc)
            if "HTTP " in err_str:
                err_type = "HTTP_ERROR"
            elif isinstance(exc, (json.JSONDecodeError, ValueError)) and ("Could not parse" in err_str or "JSON" in err_str):
                err_type = "PARSE_ERROR"
            else:
                err_type = "API_ERROR"
            return BatchTriageResult(
                ranked_candidates=[],
                selected_finalists=[],
                error_message=f"batch_triage_error: {err_str}",
                error_type=err_type,
                is_valid=False,
                latency_ms=dt,
                attempts=1
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
        market_features: Optional[Dict[str, Any]] = None,
        direction: str = "SHORT"
    ) -> AIEvaluationResult:
        """
        Sends structured market setup to 9Router.
        Fails closed (returns SKIP/WAIT) on timeout, network error, or invalid JSON.
        """
        dir_norm = direction.upper() if direction else "SHORT"
        strategy_desc = (
            "Short-Only and Long Perpetual setups" if dir_norm == "BOTH"
            else ("Long Perpetual setups" if dir_norm == "LONG" else "Short-Only Perpetual setups")
        )
        prompt = (
            f"You are a quantitative crypto trading analyst specializing in {strategy_desc}.\n"
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
            f"- If price shows signs of buyer emergence, seller exhaustion, or oversold bounce / support hold, recommend ENTER_LONG with realistic confidence (60-95).\n"
            f"- If momentum is still strongly upward without rejection, recommend WAIT.\n"
            f"- If market is too illiquid or high risk, recommend SKIP.\n\n"
            f"Output REQUIREMENT: You MUST respond ONLY with a raw JSON object (no markdown, no code blocks, no prose):\n"
            f'{{"symbol": "{symbol}", "decision": "ENTER_SHORT" | "ENTER_LONG" | "WAIT" | "SKIP", "confidence": <int 0-100>, '
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
