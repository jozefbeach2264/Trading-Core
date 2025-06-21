# TradingCore/trading_engine.py (Updated)
import asyncio

from sensors.apex_detector import ApexDetector
from sensors.compression_trap_sensor import CompressionTrapSensor
from filters.time_of_day_filter import TimeOfDayFilter
from filters.low_volume_guard import LowVolumeGuard
from filters.multi_candle_trend_confirmation import MultiCandleTrendConfirmation
from tuning.rolling_extension_module import RollingExtensionModule # New
from execution_module import ExecutionModule

class TradingEngine:
    def __init__(self, market_state, execution_module):
        self.market_state = market_state
        self.execution_module = execution_module
        self.running = False
        
        # --- Initialize all components ---
        self.sensors = {
            "apex": ApexDetector(),
            "compression": CompressionTrapSensor()
        }
        self.filters = {
            "time": TimeOfDayFilter(),
            "volume": LowVolumeGuard(),
            "trend": MultiCandleTrendConfirmation()
        }
        self.tuning_modules = {
            "rolling_extension": RollingExtensionModule() # New
        }
        
        print("TradingEngine Initialized with Tuning & Control.")

    async def start_main_loop(self):
        self.running = True
        print("TradingEngine main analysis loop started.")
        
        while self.running:
            # --- 1. Run Sensors ---
            klines_history_placeholder = []
            apex_signal = self.sensors["apex"].analyze(self.market_state)
            compression_signal = self.sensors["compression"].analyze(klines_history_placeholder)

            preliminary_signal = None
            if apex_signal.get("is_apex"):
                preliminary_signal = {"source": "ApexDetector", "side": "SELL", "details": apex_signal}
            elif compression_signal.get("is_compressed"):
                 preliminary_signal = {"source": "CompressionTrapSensor", "side": "BUY", "details": compression_signal}

            # --- 2. Run Filters ---
            if preliminary_signal:
                print(f"\n[Engine Cycle] Preliminary signal found: {preliminary_signal['source']}")
                
                filter_results = {
                    "TimeOfDay": self.filters["time"].check(),
                    "LowVolume": self.filters["volume"].check(self.market_state),
                    "Trend": self.filters["trend"].check(klines_history_placeholder, preliminary_signal['side'])
                }

                if all(filter_results.values()):
                    print(f"[Engine Cycle] ✅ Signal VALIDATED by all filters.")
                    
                    # --- 3. Tune Signal ---
                    tuned_signal = self.tuning_modules["rolling_extension"].adjust_signal(
                        preliminary_signal, self.market_state
                    )
                    
                    # --- 4. Execute Trade ---
                    await self.execution_module.place_market_order(
                        symbol="ETHUSDT",
                        side=tuned_signal['side'],
                        quantity=0.01
                    )
                else:
                    failed_filters = [name for name, passed in filter_results.items() if not passed]
                    print(f"[Engine Cycle] ❌ Signal REJECTED by filters: {failed_filters}")
            
            await asyncio.sleep(5)
            
        print("TradingEngine main loop stopped.")

    async def stop(self):
        self.running = False

