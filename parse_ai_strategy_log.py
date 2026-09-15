import json
import os
import re
from typing import Dict, List, Any

"""
Unified log parser/flattening for local numeric model training.

Supports:
- ai_strategy.log (context_packet + validator_audit_log; multi-line JSON)
- compression_detector.log
- cts_filter.log
- low_volume_guard.log
- orderbook_reversal.log
- retest_logic.log
- sentiment_filter.log
- spoof_filter.log

Each parser extracts JSON payloads and flattens them into numeric-friendly dicts.
"""

ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(ROOT, "logs", "filters")


def _numeric_bool(val: Any) -> int:
    return 1 if bool(val) else 0


def flatten_ai_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten ai_strategy context + validator audit logs."""
    flattened: Dict[str, Any] = {}
    etype = entry.get("type")
    data = entry.get("data", {})

    if etype == "context_packet":
        flattened["open"] = data.get("open")
        flattened["close"] = data.get("close")
        flattened["volume"] = data.get("volume")
        direction = data.get("direction")
        flattened["direction"] = 1 if direction == "LONG" else (-1 if direction == "SHORT" else 0)
        flattened["reversal_likelihood_score"] = data.get("reversal_likelihood_score")
        flattened["cts_score"] = data.get("cts_score")
        flattened["orderbook_score"] = data.get("orderbook_score")
    elif etype == "validator_audit_log":
        for validator_name, validator_details in data.items():
            flattened[f"{validator_name}_score"] = validator_details.get("score")
            metrics = validator_details.get("metrics", {})
            if validator_name == "CtsFilter":
                flattened[f"{validator_name}_average_range"] = metrics.get("average_range")
                flattened[f"{validator_name}_current_range"] = metrics.get("current_range")
                flattened[f"{validator_name}_grind_ratio"] = metrics.get("grind_ratio")
                flattened[f"{validator_name}_is_compressed"] = _numeric_bool(metrics.get("is_compressed"))
                flattened[f"{validator_name}_wick_strength_ratio"] = metrics.get("wick_strength_ratio")
                flattened[f"{validator_name}_mark_price"] = metrics.get("mark_price")
            elif validator_name == "RetestEntryLogic":
                flattened[f"{validator_name}_historical_level"] = metrics.get("historical_level")
                flattened[f"{validator_name}_live_low"] = metrics.get("live_low")
                flattened[f"{validator_name}_live_high"] = metrics.get("live_high")
                flattened[f"{validator_name}_bounce_confirmed"] = _numeric_bool(metrics.get("bounce_confirmed"))
                flattened[f"{validator_name}_rejection_confirmed"] = _numeric_bool(metrics.get("rejection_confirmed"))
                flattened[f"{validator_name}_retest_strength_pct"] = metrics.get("retest_strength_pct")
                flattened[f"{validator_name}_mark_price"] = metrics.get("mark_price")
            elif validator_name == "OrderBookReversalZoneDetector":
                flattened[f"{validator_name}_detected_zone"] = metrics.get("detected_zone")
                flattened[f"{validator_name}_wall_price"] = metrics.get("wall_price")
                flattened[f"{validator_name}_wall_qty"] = metrics.get("wall_qty")
            elif validator_name == "SpoofFilter":
                flattened[f"{validator_name}_spoof_thin_rate"] = metrics.get("spoof_thin_rate")
                flattened[f"{validator_name}_wall_delta_pct"] = metrics.get("wall_delta_pct")
            elif validator_name == "LowVolumeGuard":
                flattened[f"{validator_name}_candle_volume"] = metrics.get("candle_volume")
                flattened[f"{validator_name}_min_threshold"] = metrics.get("min_threshold")
            elif validator_name == "CompressionDetector":
                flattened[f"{validator_name}_average_range"] = metrics.get("average_range")
                flattened[f"{validator_name}_current_range"] = metrics.get("current_range")
                flattened[f"{validator_name}_compression_ratio"] = metrics.get("compression_ratio")
                flattened[f"{validator_name}_config_threshold_ratio"] = metrics.get("config_threshold_ratio")
            elif validator_name == "SentimentDivergenceFilter":
                flattened[f"{validator_name}_divergence_type"] = metrics.get("divergence_type")
                flattened[f"{validator_name}_price_trend_up"] = _numeric_bool(metrics.get("price_trend_up"))
                flattened[f"{validator_name}_cvd_trend_up"] = _numeric_bool(metrics.get("cvd_trend_up"))
                flattened[f"{validator_name}_net_cvd"] = metrics.get("net_cvd")

    return flattened


def parse_ai_strategy_log(log_file_path: str) -> List[Dict[str, Any]]:
    parsed_data: List[Dict[str, Any]] = []
    with open(log_file_path, 'r') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i]
        if "Context packet for AI:" in line:
            start_index = line.find('{')
            if start_index != -1:
                json_buffer = [line[start_index:].strip()]
                balance = json_buffer[0].count('{') - json_buffer[0].count('}')
                j = i + 1
                while balance != 0 and j < len(lines):
                    current_sub_line = lines[j].strip()
                    json_buffer.append(current_sub_line)
                    balance += current_sub_line.count('{') - current_sub_line.count('}')
                    j += 1
                full_json_str = "".join(json_buffer)
                try:
                    context_packet = json.loads(full_json_str)
                    parsed_data.append({"type": "context_packet", "data": context_packet})
                except json.JSONDecodeError as e:
                    print(f"Error parsing context packet JSON: {e} in string: {full_json_str}")
                i = j - 1
            else:
                print(f"JSON object start not found in context packet line: {line.strip()}")
        elif "Validator audit log:" in line:
            start_index = line.find('{')
            if start_index != -1:
                json_buffer = [line[start_index:].strip()]
                balance = json_buffer[0].count('{') - json_buffer[0].count('}')
                j = i + 1
                while balance != 0 and j < len(lines):
                    current_sub_line = lines[j].strip()
                    json_buffer.append(current_sub_line)
                    balance += current_sub_line.count('{') - current_sub_line.count('}')
                    j += 1
                full_json_str = "".join(json_buffer)
                try:
                    validator_audit_log = json.loads(full_json_str)
                    parsed_data.append({"type": "validator_audit_log", "data": validator_audit_log})
                except json.JSONDecodeError as e:
                    print(f"Error parsing validator audit log JSON: {e} in string: {full_json_str}")
                i = j - 1
            else:
                print(f"JSON object start not found in validator audit log line: {line.strip()}")
        i += 1
    return parsed_data


def _extract_json_from_line(line: str) -> Dict[str, Any]:
    start = line.find('{')
    if start == -1:
        return {}
    try:
        return json.loads(line[start:])
    except json.JSONDecodeError:
        return {}


def parse_single_line_json_log(path: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return entries
    with open(path, 'r') as f:
        for line in f:
            if '{' not in line:
                continue
            payload = _extract_json_from_line(line)
            if payload:
                entries.append(payload)
    return entries


def flatten_filter_payload(filter_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    flat["filter_name"] = filter_name
    flat["score"] = payload.get("score")
    metrics = payload.get("metrics", {})
    flag = payload.get("flag")
    flat["flag"] = flag

    if filter_name == "CompressionDetector":
        flat["average_range"] = metrics.get("average_range")
        flat["current_range"] = metrics.get("current_range")
        flat["compression_ratio"] = metrics.get("compression_ratio")
        flat["config_threshold_ratio"] = metrics.get("config_threshold_ratio")
    elif filter_name == "CtsFilter":
        flat["average_range"] = metrics.get("average_range")
        flat["current_range"] = metrics.get("current_range")
        flat["grind_ratio"] = metrics.get("grind_ratio")
        flat["is_compressed"] = _numeric_bool(metrics.get("is_compressed"))
        flat["wick_strength_ratio"] = metrics.get("wick_strength_ratio")
        flat["mark_price"] = metrics.get("mark_price")
    elif filter_name == "LowVolumeGuard":
        flat["candle_volume"] = metrics.get("candle_volume")
        flat["min_threshold"] = metrics.get("min_threshold")
    elif filter_name == "OrderBookReversalZoneDetector":
        flat["detected_zone"] = metrics.get("detected_zone")
        flat["wall_price"] = metrics.get("wall_price")
        flat["wall_qty"] = metrics.get("wall_qty")
    elif filter_name == "RetestEntryLogic":
        flat["retest_type"] = metrics.get("retest_type")
        flat["historical_level"] = metrics.get("historical_level")
        flat["live_low"] = metrics.get("live_low")
        flat["live_high"] = metrics.get("live_high")
        flat["bounce_confirmed"] = _numeric_bool(metrics.get("bounce_confirmed"))
        flat["rejection_confirmed"] = _numeric_bool(metrics.get("rejection_confirmed"))
        flat["retest_strength_pct"] = metrics.get("retest_strength_pct")
        flat["mark_price"] = metrics.get("mark_price")
    elif filter_name == "SentimentDivergenceFilter":
        flat["divergence_type"] = metrics.get("divergence_type")
        flat["price_trend_up"] = _numeric_bool(metrics.get("price_trend_up"))
        flat["cvd_trend_up"] = _numeric_bool(metrics.get("cvd_trend_up"))
        flat["net_cvd"] = metrics.get("net_cvd")
    elif filter_name == "SpoofFilter":
        flat["spoof_thin_rate"] = metrics.get("spoof_thin_rate")
        flat["wall_delta_pct"] = metrics.get("wall_delta_pct")

    return flat


def collect_all_flattened() -> Dict[str, List[Dict[str, Any]]]:
    output: Dict[str, List[Dict[str, Any]]] = {}

    ai_path = os.path.join(LOG_DIR, "ai_strategy.log")
    ai_entries = parse_ai_strategy_log(ai_path)
    output["ai_strategy"] = [flatten_ai_entry(e) for e in ai_entries]

    single_line_logs = {
        "compression_detector": ("compression_detector.log", "CompressionDetector"),
        "cts_filter": ("cts_filter.log", "CtsFilter"),
        "low_volume_guard": ("low_volume_guard.log", "LowVolumeGuard"),
        "orderbook_reversal": ("orderbook_reversal.log", "OrderBookReversalZoneDetector"),
        "retest_logic": ("retest_logic.log", "RetestEntryLogic"),
        "sentiment_filter": ("sentiment_filter.log", "SentimentDivergenceFilter"),
        "spoof_filter": ("spoof_filter.log", "SpoofFilter"),
    }

    for key, (fname, filter_name) in single_line_logs.items():
        path = os.path.join(LOG_DIR, fname)
        entries = parse_single_line_json_log(path)
        output[key] = [flatten_filter_payload(filter_name, e) for e in entries if e]

    return output


if __name__ == "__main__":
    flattened = collect_all_flattened()
    for section, rows in flattened.items():
        print(f"=== {section} ({len(rows)} rows) ===")
        for row in rows:
            print(json.dumps(row, indent=2))
