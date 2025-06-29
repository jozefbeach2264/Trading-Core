# TradingCore/test_startup.py
import logging
import traceback

print("--- Starting Startup Test ---")

try:
    print("[1/8] Importing core libraries (FastAPI, etc.)...")
    from fastapi import FastAPI
    from contextlib import asynccontextmanager
    print("      ✅ SUCCESS")

    print("[2/8] Importing market_state...")
    from market_state import MarketState
    print("      ✅ SUCCESS")

    print("[3/8] Importing validator_stack...")
    from validator_stack import ValidatorStack
    print("      ✅ SUCCESS")

    print("[4/8] Importing strategy_router...")
    from strategy_router import StrategyRouter
    print("      ✅ SUCCESS")

    print("[5/8] Importing trade_lifecycle_manager...")
    from trade_lifecycle_manager import TradeLifecycleManager
    print("      ✅ SUCCESS")

    print("[6/8] Importing exchange_client...")
    from exchange_client import ExchangeClient
    print("      ✅ SUCCESS")

    print("--- All imports successful. Now testing instantiation... ---")

    print("[7/8] Instantiating MarketState...")
    market_state = MarketState(symbol="ETHUSDT")
    print("      ✅ SUCCESS")
    
    print("[8/8] Instantiating core services (ValidatorStack, Router, LifecycleManager)...")
    validator = ValidatorStack()
    router = StrategyRouter()
    lifecycle_manager = TradeLifecycleManager(market_state)
    print("      ✅ SUCCESS")

    print("\n--- ✅ ALL STARTUP TESTS PASSED ---")

except Exception as e:
    print(f"\n--- ❌ TEST FAILED ---")
    print(f"The error occurred at the last step attempted.")
    print(f"ERROR TYPE: {type(e).__name__}")
    print(f"ERROR DETAILS: {e}")
    traceback.print_exc()

