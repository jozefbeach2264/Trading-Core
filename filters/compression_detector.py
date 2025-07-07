import logging
import os
import json
from typing import Dict, Any, Set
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

def setup_compression_logger(
    config: Config
) -> logging.Logger:
    log_path = config.compression_detector_log_path
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(
        log_dir
    ):
        os.makedirs(log_dir)
    logger = logging.getLogger(
        'CompressionDetectorLogger'
    )
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(
            log_path
        )
        formatter = logging.Formatter(
            '%(asctime)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

class CompressionDetector:
    def __init__(self, config: Config):
        self.config = config
        self.logger = (
            setup_compression_logger(config)
        )
        self.lookback_period = (
            config.compression_lookback_period
        )
        self.range_ratio = (
            config.compression_range_ratio
        )
        self.allowed_hours = (
            self._parse_trade_windows(
                config.trade_windows
            )
        )
        self.logger.info(json.dumps({
            "level": "INIT",
            "msg": "CompressionDetector Ready",
            "lookback": self.lookback_period,
            "range_ratio": self.range_ratio
        }))

    def _parse_trade_windows(
        self, window_str: str
    ) -> Set[int]:
        allowed = set()
        try:
            for part in window_str.split(','):
                if '-' in part:
                    start, end = map(
                        int, part.split('-')
                    )
                    for h in range(start, end + 1):
                        allowed.add(h)
                else:
                    allowed.add(int(part))
        except ValueError as e:
            logging.getLogger(__name__).error(
                f"Invalid trade_windows: '{window_str}'"
            )
        return allowed

    def _is_within_trade_window(self) -> bool:
        return datetime.utcnow().hour in (
            self.allowed_hours
        )

    async def generate_report(
        self, market_state: MarketState
    ) -> Dict[str, Any]:
        report = {
            "filter_name": "CompressionDetector",
            "compression_detected": False,
            "compression_score": 0.0,
            "notes": "Not in trade window or off."
        }
        if (
            not self.config.autonomous_mode_enabled
            or not self._is_within_trade_window()
        ):
            return report

        klines = list(market_state.klines)
        if len(klines) < (
            self.lookback_period + 1
        ):
            report["notes"] = (
                f"Not enough klines "
                f"({len(klines)}/"
                f"{self.lookback_period + 1})"
            )
            return report

        lookback_klines = klines[
            -(self.lookback_period + 1):-1
        ]
        ranges = [
            float(k[2]) - float(k[3])
            for k in lookback_klines
        ]
        avg_range = (
            sum(ranges) / len(ranges)
            if ranges else 0
        )

        last_candle = klines[-1]
        h, l = float(last_candle[2]), float(last_candle[3])
        cur_range = h - l

        # --- FIX ---
        # If the current candle has no range, it's a dead market or bad data.
        # Treat this as a non-event, not as compression.
        if cur_range <= 0:
            report["notes"] = (
                f"Current candle has zero or negative range ({cur_range:.4f}). Ignoring."
            )
            return report
        # --- END FIX ---

        if avg_range == 0:
            report["notes"] = (
                "Avg range is zero. Invalid."
            )
            return report

        is_compressed = (
            cur_range < avg_range * self.range_ratio
        )

        self.logger.info(json.dumps({
            "level": "DEBUG",
            "avg_range": round(avg_range, 4),
            "current_range": round(cur_range, 4),
            "threshold": round(
                avg_range * self.range_ratio, 4
            ),
            "compressed": is_compressed
        }))

        if is_compressed:
            score = 1.0 - (cur_range / avg_range)
            report.update({
                "compression_detected": True,
                "compression_score": round(score, 4),
                "notes": (
                    f"Compression detected. "
                    f"Cur={cur_range:.4f} "
                    f"vs Avg={avg_range:.4f}"
                )
            })
            self.logger.info(json.dumps({
                "timestamp": (
                    datetime.utcnow()
                    .isoformat() + "Z"
                ),
                "compression_score": round(score, 4),
                "cur_range": round(cur_range, 4),
                "avg_range": round(avg_range, 4),
                "lookback": self.lookback_period,
                "ratio": self.range_ratio,
                "result": True
            }))

        return report
