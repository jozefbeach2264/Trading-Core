import logging
import os
import json
from typing import Dict, Any, Set
from datetime import datetime

from config.config import Config
from data_managers.market_state import MarketState

def setup_low_volume_logger(config: Config) -> logging.Logger:
    log_path = config.low_volume_guard_log_path
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger('LowVolumeGuardLogger')
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path)
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger

class LowVolumeGuard:
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_low_volume_logger(self.config)
        self.lookback = self.config.low_volume_lookback
        self.volume_ratio = self.config.low_volume_ratio
        self.allowed_hours = self._parse_trade_windows(config.trade_windows)

    def _parse_trade_windows(self, window_str: str) -> Set[int]:
        allowed_hours = set()
        try:
            parts = window_str.split(',')
            for part in parts:
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    for hour in range(start, end + 1):
                        allowed_hours.add(hour)
                else:
                    allowed_hours.add(int(part))
        except ValueError as e:
            logging.getLogger(__name__).error(f"Invalid trade_windows format: '{window_str}'. Error: {e}")
        return allowed_hours

    def _is_within_trade_window(self) -> bool:
        return datetime.utcnow().hour in self.allowed_hours

    async def generate_report(self, market_state: MarketState) -> Dict[str, Any]:
        report = {
            "filter_name": "LowVolumeGuard",
            "low_volume_detected": False,
            "volume_ratio": 0.0,
            "notes": "Not in trade window or not autonomous."
        }
        
        if not self.config.autonomous_mode_enabled or not self._is_within_trade_window():
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "result": False,
                "denial_reason": "Not in trade window or autonomous mode off"
            }))
            return report

        klines = list(market_state.klines)
        if len(klines) < self.lookback + 1:
            report["notes"] = f"Not enough kline data ({len(klines)}/{self.lookback + 1})."
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "result": False,
                "denial_reason": "Insufficient kline data",
                "klines_available": len(klines),
                "klines_required": self.lookback + 1
            }))
            return report

        lookback_klines = klines[-(self.lookback + 1):-1]
        volumes = [float(k[5]) for k in lookback_klines]
        average_volume = sum(volumes) / len(volumes) if volumes else 0
        current_volume = float(klines[-1][5])

        if average_volume == 0:
            report["notes"] = "Average volume is zero, cannot calculate ratio."
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "result": False,
                "denial_reason": "Zero average volume"
            }))
            return report

        is_low_volume = current_volume < (average_volume * self.volume_ratio)
        calculated_ratio = current_volume / average_volume

        if is_low_volume:
            report.update({
                "low_volume_detected": True,
                "volume_ratio": round(calculated_ratio, 4),
                "notes": f"Low volume detected. Current volume {current_volume:.2f} is below threshold of average {average_volume:.2f}."
            })
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "result": True,
                "low_volume": True,
                "current_volume": round(current_volume, 2),
                "average_volume": round(average_volume, 2),
                "threshold_ratio": self.volume_ratio,
                "actual_ratio": round(calculated_ratio, 4)
            }))
        else:
            report.update({
                "volume_ratio": round(calculated_ratio, 4),
                "notes": f"Volume acceptable. Ratio {round(calculated_ratio, 4)}"
            })
            self.logger.info(json.dumps({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "result": False,
                "low_volume": False,
                "current_volume": round(current_volume, 2),
                "average_volume": round(average_volume, 2),
                "threshold_ratio": self.volume_ratio,
                "actual_ratio": round(calculated_ratio, 4),
                "denial_reason": "Volume above threshold"
            }))

        return report