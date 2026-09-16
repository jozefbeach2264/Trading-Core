# TradingCore code review - 2026-07-31 (PARTIAL)

**Document generated:** 2026-07-31 13:04:18 EDT  
**Workflow run:** `wf_be625050-356`, launched 2026-07-31 01:05, stopped 01:34, resumed 01:37, completed 2026-07-31 01:46 (partial — spend cap).  
**Status as of 2026-07-31 13:05:** DEFERRED at user request; grow-automation is the active focus.

**Scope:** `~/trading_core_project/TradingCore`, uncommitted diff vs HEAD (27 files; `logs/`, `poetry.lock` excluded).

**Run:** workflow `wf_be625050-356`, high effort. **STATUS: PARTIAL** - 21 of 45 agents (including the
synthesis stage and ~20 verifiers) died on the monthly spend limit. The findings below each passed an
independent adversarial verifier (`CONFIRMED`), but there was no dedup/ranking synthesis pass and
coverage of the diff is incomplete.


**Status: DEFERRED** - to be worked later; grow-automation is the current focus.


**Resume:** `Workflow({scriptPath: '~/.claude/projects/-home-HighTech-Redneck/d4d4ef3b-4636-4310-8dc5-bd603a9d7894/workflows/scripts/code-review-wf_be625050-356.js', resumeFromRunId: 'wf_be625050-356'})`
- completed agents replay from cache, so only the ~21 killed agents re-run.


---

## Verified findings (10)


### 1. `strategy/ai_strategy.py:117` - correctness / CONFIRMED

**Defect:** context_packet reads `reversal_likelihood_score` from the forecast, but rolling5_engine.py was renamed in this same diff to emit `reversal_zone_strength`, so the reversal-risk input is hardcoded 0.0 on every cycle.


**Failure scenario:** Rolling5Engine.generate_forecast returns {"reversal_zone_strength": 0.94, ...} for a market sitting at a strong reversal zone. `forecast.get("reversal_likelihood_score", 0.0)` misses and yields 0.0, so the packet sent to Grok says the reversal probability is zero — while the system prompt explicitly tells the model "Reversal Likelihood Score: Probability of a price reversal". The model returns Execute with high confidence and the bot opens a 200x leveraged position directly into the reversal it was built to avoid. `grep -rn reversal_likelihood_score` shows only ai_strategy.py:117, ai_client.py and parse_ai_strategy_log.py read the old name; rolling5_engine.py:129/195 are the only writers and they only write the new name, so the value is 0.0 100% of the time — the whole reversal signal is silently dead.


### 2. `ai_client.py:202` - correctness / CONFIRMED

**Defect:** `elapsed_ms` is assigned only after `await self.client.post(...)` returns, but four exception handlers call `round(elapsed_ms, 2)`; any exception raised by the POST itself hits an unbound local.


**Failure scenario:** AI_CLIENT_TIMEOUT was just cut 20s -> 5s (config/config.py:23), so grok-4-fast-reasoning exceeding 5s is now routine. On timeout, control enters `except httpx.TimeoutException:` (line 195), which evaluates `round(elapsed_ms, 2)` at line 202 — `elapsed_ms` was never bound because line 83 is downstream of the POST. UnboundLocalError is raised inside the handler, so no sibling `except` catches it and it escapes get_ai_verdict entirely. The carefully-built `{"action": "Reanalyze", "reasoning": "AI request timed out."}` verdict is never returned and the `{"type": "timeout"}` NDJSON record is never written to ai_model.log, so parse_ai_strategy_log.py reports zero timeouts no matter how many occur. ai_strategy.py:130 swallows it and logs the misleading `AI Client Error: cannot access local variable 'elapsed_ms'`, making every network failure look like an internal Python bug. Identical unbound reference at lines 182 (HTTPStatusError, reachable if raise_for_status is skipped by a transport-layer status error), 192 and 211 — the generic `except Exception` at 204 covers httpx.ConnectError/DNS failures, which also occur before line 83.


### 3. `data_managers/orderbook_parser.py:70` - correctness / CONFIRMED

**Defect:** The new "always return a wall" fallback fabricates a wall from the largest ordinary book level, which feeds analyze_thinning_and_spoofing and turns normal top-of-book churn into a permanent spoofing block.


**Failure scenario:** analyze_thinning_and_spoofing (line 95-102) calls find_wall_clusters on both the previous and current book. Before this change, a book with no 10x wall returned bid_walls=[] on both sides, so prev_bid_wall_qty was 0, wall_delta_pct fell to the `else 0` branch, and spoof_thin_rate stayed 0.0. Now every snapshot yields exactly one synthetic wall = max qty of the visible levels, so wall_delta_pct becomes the tick-to-tick percent change of a single ordinary level. Compounding it, the WS subscription in this same diff moved from `books` (400 levels) to `books5` (5 levels) at 100 ms, and market_data_manager._maybe_emit_orderbook_events forces ensure_order_book_metrics_are_current on every one of those messages. A 5-level book whose largest level shrinks 30% between two 100ms frames — completely routine — produces spoof_thin_rate=30. SpoofFilter's dynamic_block is max(10.0, median*2) and median is 0 most of the time (delta>0 clamps the rate to 0.0), so 30 > 10 trips a block; `sustained_block = sum(self._recent_blocks) >= 2` over a 5-deep window then latches it. The post-signal gate rejects with `Rejected - Post-Signal: SPOOFING` on essentially every cycle and the bot never trades, while logs/failed_signals.json fills with false SPOOFING_DETECTED entries.


### 4. `filters/cts_filter.py:137` - correctness / CONFIRMED

**Defect:** The rewritten scoring floors CtsFilter's score at 0.55, making the `❌ Block` branch unreachable — the primary-gate compression-trap sensor can no longer block, and the streak/cooldown code added in the same hunk is dead.


**Failure scenario:** The three score branches are 1.0 (not compressed), 0.8 (expansion evidence), and `max(0.55, grind_ratio*0.7)` (line 137) — the minimum possible score is 0.55. The flag ladder at 142-150 is `>=0.75 Hard Pass / >=0.50 Soft Flag / else Block`, so `else` at line 148 can never execute, `self._low_score_streak += 1` at line 150 never runs, and the `_low_score_streak >= 5` cooldown added at line 153 never fires. CtsFilter is one of only two primary_gate_filters (validator_stack.py:27-30), so in a genuinely compressed, no-expansion chop market — the exact trap the Compression Trap Sensor exists to detect — the filter reports score 0.55 / "⚠️ Soft Flag", the primary gate records hard_blocks=0, and the pipeline proceeds to signal generation and a live 200x entry. The pre-change code returned score 0.0 there and hard-blocked. The dead code is self-evidence of the mistake: 20 lines of streak+cooldown state were added that can never be reached.


### 5. `filters/compression_detector.py:72` - correctness / CONFIRMED

**Defect:** Thresholds are derived from the same rolling window the current sample was just appended to, so by construction the bottom ~20% of samples hard-block regardless of whether any real compression exists.


**Failure scenario:** compression_ratio is appended to self._recent_ratios at line 61 before p20/median/p80 are computed from that same list. soft_threshold = max(range_ratio*0.5, p20_ratio) = max(0.4, p20) and hard_threshold = max(0.8, median, p80*0.8). Take a perfectly healthy market where current_range tracks avg_range so every compression_ratio lands in 0.95-1.05: after 5 samples p20 settles near 0.96 and median near 1.00, so any cycle whose ratio is 0.95 falls below soft_threshold and gets `❌ Block` / "HEAVY_PRICE_COMPRESSION" — while price action is entirely normal. Because the thresholds chase the data, this is permanent: roughly one cycle in five is hard-blocked forever, and roughly half fail hard_threshold and degrade to Soft Flag. CompressionDetector is a post_signal_filter (validator_stack.py:37), so each of those becomes `Rejected - Post-Signal: COMPRESSION`, discarding ~20% of otherwise-valid signals at random. Conversely, during a genuine multi-hour volatility collapse every sample compresses together, the median collapses with them, and hard_threshold floors out at range_ratio=0.8 — but ratios near 1.0 relative to an already-crushed average still pass, so real compression stops being detected.


### 6. `ai_client.py:227` - correctness / CONFIRMED

**Defect:** `min(a + b + c, 1.0) / 3.0` clamps the sum before dividing, capping fallback confidence at 0.333 — below the 0.7 gate — so the fallback heuristic's Execute verdict can never take effect.


**Failure scenario:** The parenthesization should be min(sum/3, 1.0); as written the sum is clamped to 1.0 first, so confidence can never exceed 0.3333 no matter the inputs. The Execute branches at lines 229 and 248 require reversal_likelihood_score > 0.8 AND cts_score > 0.8 AND orderbook_score > 0.8, which sums to >2.4 -> clamped to 1.0 -> confidence exactly 0.3333. ai_strategy.py:143 then rejects anything under config.ai_confidence_threshold (0.7) with `Rejected - AI CONFIDENCE LOW (0.33/0.7)`. So when xAI returns empty content or malformed JSON (the exact scenario _fallback_from_context exists to cover), the heuristic's strongest possible Execute is unconditionally discarded and the bot stops trading entirely rather than degrading — while the operator-facing log blames low AI confidence rather than the dead API. The mirror-image hazard: an operator who lowers AI_CONFIDENCE_THRESHOLD to 0.3 to "fix" the flood of low-confidence rejections instantly enables every fallback Execute, including ones driven by the permanently-zero reversal_likelihood_score from ai_strategy.py:117.


### 7. `/home/HighTech_Redneck/trading_core_project/TradingCore/filters/cts_filter.py:137` - correctness / CONFIRMED

**Defect:** The CtsFilter hard block was deleted — the compressed-with-no-wick-rejection branch that used to leave score at 0.0 ("❌ Block") now floors the score at 0.55, so the filter can never hard-block again, and CtsFilter is one of only two filters in the primary gate.


**Failure scenario:** During flat chop the live candle range is < 0.8 × the 15-candle average, body_ratio < 0.5, current_range < 0.8 × average_range and wick_signal == "none". Old code: score 0.0 → flag "❌ Block" → run_primary_gate returns hard_blocks=1 → AIStrategy.generate_signal returns "Rejected - Primary Gate: NO_TRAP_SIGNAL" and no trade is generated. New code: score = max(0.55, grind_ratio*0.7) ≥ 0.55 → "⚠️ Soft Flag" → hard_blocks=0 → the gate passes, the strategy router generates a signal and the bot opens a 200x-leverage ETH position inside a dead compressed range that the CTS gate existed specifically to refuse. Every other scoring path yields 1.0 or 0.8, so score < 0.50 is now unreachable and the "❌ Block" branch (plus the new _low_score_streak cooldown that depends on it) is dead code.


### 8. `/home/HighTech_Redneck/trading_core_project/TradingCore/filters/cts_filter.py:137` - correctness / CONFIRMED

**Defect:** CtsFilter's new score floor of 0.55 means the primary-gate filter can no longer hard-block a compressed market, and the 0.8 "EXP_IMPULSE_CONFIRMED" score is reported to the AI as strong trend confirmation.


**Failure scenario:** CtsFilter is one of only two primary_gate_filters (validator_stack.py:27-30) and is the gate that used to stop the pipeline in a dead, compressed tape. Previously a compressed candle with no wick signal scored 0.0 -> flag "❌ Block" -> ai_strategy returns at the primary gate without ever calling the AI. Now the else branch sets score = max(0.55, grind_ratio * 0.7), which is >= 0.50 by construction, so the flag is at worst "⚠️ Soft Flag" and hard_blocks stays 0 — the only remaining way CtsFilter can block is the 3-second churn cooldown. Worse, the expansion_evidence test at line 121 passes if ANY of body_ratio >= 0.5, current_range >= average_range * 0.8, or wick_signal != "none" holds, which is true for most candles, giving score = 0.8. ai_strategy.py:118 forwards that as context_packet["cts_score"] = 0.8, and the ai_client prompt states "CTS Score: Compression Trap Sensor. High score (>0.8) indicates strong trend confirmation" — so a flat, compressed, trendless market is presented to grok as strong trend confirmation, and every cycle now reaches the AI decision core and burns an xAI call instead of being rejected at the gate.


### 9. `/home/HighTech_Redneck/trading_core_project/TradingCore/strategy/ai_strategy.py:117` - correctness / CONFIRMED

**Defect:** rolling5_engine.py renamed its output key from `reversal_likelihood_score` to `reversal_zone_strength`, but ai_strategy.py still reads the old key, so the reversal-risk input to the AI is hard-wired to 0.0.


**Failure scenario:** Rolling5Engine computes reversal_zone_strength = 0.95 (imminent reversal). forecast.get("reversal_likelihood_score", 0.0) returns the default 0.0, so the context packet sent to grok-4-fast-reasoning says "reversal_likelihood_score: 0.0" while the system prompt tells the model that field is "Probability of a price reversal". The model sees zero reversal risk, returns Execute with confidence > 0.7, and the engine opens a position directly into the forecasted reversal. The old prompt rule "A high 'reversal_likelihood_score' is a major red flag" is now unenforceable because the signal never arrives non-zero. The same dead key gates the Execute branch of ai_client._fallback_from_context (ai_client.py:229/248, requires > 0.8) and parse_ai_strategy_log.py:42, which will always report None.


### 10. `/home/HighTech_Redneck/trading_core_project/TradingCore/strategy/ai_strategy.py:117` - correctness / CONFIRMED

**Defect:** rolling5_engine renamed its output key to `reversal_zone_strength`, but the only consumer (ai_strategy) still reads `forecast.get("reversal_likelihood_score", 0.0)`, so the AI is now told reversal risk is 0.0 on every single trade.


**Failure scenario:** Rolling5Engine.generate_forecast computes reversal_score = 0.95 and returns {"reversal_zone_strength": 0.95, ...} (rolling5_engine.py:129/195). ai_strategy.py:117 looks up the old key, gets the default 0.0, and builds context_packet = {..., "reversal_likelihood_score": 0.0}. ai_client's system prompt tells grok "Reversal Likelihood Score: Probability of a price reversal" — the model therefore sees zero reversal probability for a setup the forecaster rated 0.95 and returns "Execute". normalize_ai_action turns that into "✅ Execute", engine.py:102 calls trade_executor.execute_trade, and the bot opens a leveraged position directly into the reversal the forecaster predicted. The same 0.0 also propagates into AIClient._fallback_from_context (ai_client.py:222), whose Execute branch requires reversal_likelihood_score > 0.8, so the offline heuristic is permanently dead as well.

---

## FIXED — 2026-09-15 13:08 EDT (session 862ab770, branch `fix/review-2026-07-31`)

All 10 findings (6 distinct defects) are fixed and covered by tests (`tests/`, 46 passing, run with
`.venv/bin/python -m pytest`). One additional defect found while fixing (G) and one perf pass (P).
Baseline commit `ad5b99e` = the exact working tree this review examined.

| Findings | Defect | Fix commit | Where |
|---|---|---|---|
| 1, 9, 10 | dead `reversal_likelihood_score` key (AI saw 0.0) | `c6d2d1f` | rolling5_engine.py emits the canonical `reversal_likelihood_score`; ai_strategy.py reads it and passes the trade direction |
| 2 | `elapsed_ms` unbound in four handlers | `40f6fe3` | ai_client.py: start time bound before the try; every failure → Reanalyze, never raises |
| 6 | fallback confidence capped at 0.333 | `40f6fe3` | ai_client.py: mean of the three gate scores (reversal inverted); Execute needs LOW reversal risk |
| 4, 7, 8 | CtsFilter floor 0.55 → block unreachable | `88567fc` | filters/cts_filter.py: 1.0 / 0.6+wick bonus / **0.0 block**; cooldown reachable |
| 5 | CompressionDetector thresholds chase the data | `88567fc` | filters/compression_detector.py: config-anchored thresholds; prior-window stats = diagnostics only |
| 3 | fabricated orderbook walls → permanent SPOOFING | `88567fc` | data_managers/orderbook_parser.py: fallback removed |
| **G** (new) | reversal score saturated at 1.0 every cycle (mark_price_factor ≈ 1.0) — Grok aborted every trade | `c6d2d1f` | rolling5_engine.py: direction-aware 0.5·trend + 0.3·pressure + 0.2·sentiment, each in [0,1] |
| **P** (perf) | 9 fsync'd SQLite commits + ~20 sync log writes per 0.2 s cycle on the event loop | `06c3fb7` | log_utils.py queue-backed loggers; memory_tracker.py WAL + batched to_thread writes, filter history off by default; keep-alive exchange socket |

**Grok → local model (approved 2026-09-15):** `40f6fe3` — AIClient targets any OpenAI-compatible endpoint, default
`http://127.0.0.1:8081/v1` (llm-serve). `.env` updated (backup `.env.bak-2026-09-15`), XAI key commented out.

**Review completion:** the original workflow script (`code-review-wf_be625050-356.js`) no longer exists on disk (old
username path), so the 2026-07-31 run cannot be resumed. Replacement: workflow `wf_596d910c-07a` (2026-09-15 13:08 EDT) — adversarial
verification of every fix (2 lenses each) + a 7-dimension bug hunt + completeness critic + 2-refuter confirmation + perf
audit. Results are appended below when it completes.

### Verification + batch 2 — 2026-09-15 20:05 EDT

**Adversarial verification (wf_596d910c-07a, 16/16 verdicts, two lenses per fix): every fix upheld** on
"does it fix" and "does it break" — one refutation (F: the wall-thinning metric flickered when the top-of-book
quantity changed because walls were re-thresholded per snapshot) and 14 follow-up issues, all applied:

| Commit | What |
|---|---|
| `7376167` | CTS 3 s evaluation cooldown removed (blinded the gate ~75% of the time in compression); COMPRESSION_RANGE_RATIO validated |
| `0f8bf8c` | **OKX ordering bugs (verified live): history klines are newest-first (loader stored them oldest-first for up to 500 min after every start); asks are best-first (parser used the deepest ask as top-of-book)**; per-price wall thinning, both sides, honours SPOOF_LARGE_ORDER_MULTIPLIER / SPOOF_DISTANCE_PERCENT |
| `b5a22b7` | fallback heuristic can no longer open a position unless AI_FALLBACK_CAN_EXECUTE=true; unknown direction → Reanalyze; Abort/Reanalyze verdicts carry an explicit rejection reason; no model call without a forecast; **age-aware compression** (√t expected range, CANDLE_TOO_YOUNG soft flag < 5 s) in CtsFilter + CompressionDetector; CTS_NARROW_RANGE_RATIO validated |
| `12b374d` | live-order transport errors recorded not raised (explicit 5 s order timeout); EXCHANGE_KEEPALIVE_SECONDS validated |
| `94fb692` | reasoning string capped in the JSON grammar (AI_REASONING_MAX_CHARS) |
| `16e6e55` | SQLite errors never escape into the cycle |

Noted, not changed (design/tuning): the reversal trend term saturates once the 10-candle drift exceeds one average
range per horizon (score plateaus at ≈0.15/0.65) and measures momentum alignment, so fade-the-trap TrapX signals
carry a structurally higher reversal score than with-trend Scalpel signals; queue-backed logs can lose the last
records on SIGKILL/OOM (graceful shutdown drains fully); JSON log lines fold tracebacks into `message` instead of
a separate `exc_info` key.

**Local model:** Gemma 4 12B QAT + MTP, thinking off → **434 ms median / 505 ms p95 per verdict, 100% valid JSON**
(profile `~/models/profiles/trading.env`); Grok measured 3.4 s. End-to-end dry run (llama-server + bot, 100 s):
provider detected, OKX feeds live, 0 warnings/errors/tracebacks. Tests: **66 passing**.

**Still open:** the 7-dimension bug hunt + completeness critic + 2 perf-audit agents of wf_596d910c-07a died on
the session usage cap (resets 20:00 EDT); resume with the script path in the workflow output — cached verdicts
replay, only those 10 agents run.

### Bug hunt (wf_596d910c-07a, resumed 2026-09-16 01:02 EDT) — 79 candidates, triaged by hand
The seven dimension hunters + completeness critic completed; the two-refuter confirmation stage (162 agents) and the
two perf auditors died on the session cap twice, so the candidates were triaged against the code directly (each fix
carries a test). Commits `3f53bd8` (safety / live path) and `374278c` (data path).

**The live order path had never worked** — balance was never fetched and the order side was sent as LONG/SHORT, which
the Binance-style API rejects — and that masked the most dangerous defect: with no open-position guard a persisting
Execute verdict re-executed every 0.2 s cycle (three stacked entries 8 s apart are in the old simulation state).

Fixed (bug → commit):
- Order stacking / no position state → one position at a time via the Rolling5 lifecycle (MAX_POSITION_CANDLES), close
  at the end of the horizon (sim realises PnL; live sends a reduce-only MARKET); only fully approved signals execute
  (a low-confidence rejection used to return an Execute action the engine acted on) → `3f53bd8`
- No staleness gate anywhere (feed outage → frozen snapshot traded; verdict acted on after up to 10 s with no
  re-check) → freshness.py: MAX_DATA_STALENESS_S, live-candle-is-current, MAX_DECISION_AGE_S, MAX_ENTRY_DRIFT_PCT
- Validator fail-open (a crashing filter = pass) → fail closed
- DRY_RUN_MODE="1"/"yes" silently meant LIVE → strict boolean parsing; ALLOWED_WINDOWS typo silently allowed 24/7 →
  validated at start-up; 23:59:xx outside "00:00-23:59" → minute resolution; ADEX_SYMBOL vs TRADING_SYMBOL cross-check
- Live executor: side enum, /fapi/v2/balance fetch (start + every keep-alive), LOT_SIZE/MIN_NOTIONAL/unknown-filters
  refusal, order record key (`order_data`), non-JSON 2xx, cancellation-shielded POST, EXCHANGE_SET_LEVERAGE opt-in
- Simulation: fee 0.08 applied as a fraction (8%!) → percentage of leveraged notional; exhausted balance refuses; closes
  realise PnL (dry-run results were meaningless before)
- orderbook_score was sign-less (a resistance wall read as confirmation for a LONG) → `orderbook_zone` in the packet,
  prompt + fallback aware; deterministic AI_MAX_REVERSAL_RISK backstop (no model call above it)
- Confidence "85" clamped to a 1.0 Execute → rejected as garbage; truncation / still-thinking logged distinctly;
  verdicts no longer pollute the SQLite trades table
- Units: OKX sizes are contracts (ctVal 0.1 ETH) → volume guard 10x too permissive, CVD/HUD/AI volume 10x → converted
  at ingest; in-progress REST candle stored as closed; partial first candle finalised as a full minute; no re-sync on
  reconnect; REST limit > OKX cap → `374278c`
- Volume guard age-unaware; spoof metric could miss a 100 ms pull and double-count a cached snapshot; Scalpel/HUD
  read the wrong candle after the ordering fix; filter logs unrotated (~1 GB/day) → `374278c`

**Design questions left for the operator (not changed):**
1. Position sizing semantics: live treats RISK_CAP_PERCENT×balance as NOTIONAL (no leverage term); the simulation (and
   the deleted CapitalManager) treat it as MARGIN × LEVERAGE — a 200× difference. With .env values (0.25, 200) the sim
   opens 50× balance in notional per trade. Decide which, then make the other path match.
2. LEVERAGE is only pushed to the exchange with EXCHANGE_SET_LEVERAGE=true; the account's stored leverage governs otherwise.
3. Exits: the live path now closes at the Rolling5 horizon with a reduce-only market order, but TrapX/Scalpel
   stop-loss / take-profit values are still never sent to the exchange. A liquidation-distance check based on an $8
   absolute threshold (MAX_LIQUIDATION_THRESHOLD) does not scale with leverage, price or symbol.
4. Strategy quality: Scalpel's 0.5% "retest" band fires on nearly every cycle; TrapX has no minimum wick size and uses
   the side-agnostic thinning rate; the reversal trend term plateaus at ±1 range/horizon and penalises fade-the-trap
   setups; the reversal-zone detector's distance term ≈ 1 always; CVD is a 1000-trade (~11 s) window compared with a
   20-minute trend; wall detection on the 5-level books5 feed is starved by construction (top level is usually the
   largest). These need a trading decision, not a bug fix.
5. Secrets: `stuff` and `.env.bak-2026-09-15` hold the live keys in plaintext beside `.env`; rotate the Asterdex key.

**End-to-end smoke, 2026-09-16 06:16 EDT** (llama-server `trading` profile + bot, dry run, 100 s): a Scalpel SHORT fired and the
local model answered ~90 verdicts at 540–580 ms each (100% parsed; mostly Reanalyze/Abort at 0.4 confidence on a weak
setup), every gate logged an explicit reason, 0 warnings/errors/tracebacks. The run exposed one regression in the new
approval check (strategy packets carry a descriptive `reason`), fixed in `85eeebc`
with a test. Branch: 14 commits over the baseline `ad5b99e` (wip baseline included = 15), 99 tests.

**2026-09-16 08:30 EDT — merged to main; design question #1 resolved.** Operator: "we shouldn't need to put up more than 10% of the
account" → RISK_CAP_PERCENT = margin fraction, hard-capped at 0.10 in config, live sizing = sim sizing
(`991067e`). Same commit: simulation now exits on stop-loss / take-profit / liquidation via
per-cycle mark-to-market (time horizon as the fallback) and writes run statistics (win rate, net PnL, fees, max
drawdown, closes by reason) — `python sim_stats.py`. Exchange choice still open (US API access); live path stays dormant.
