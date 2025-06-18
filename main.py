from chart_reader import ChartReader
from signal_interpreter import SignalInterpreter
from validator_stack import ValidatorStack
from strategy_router import StrategyRouter
from dan1_core import core_logic_dan1
from log_handler import LogHandler
from error_reporter import ErrorReporter

# Optional modules if present
# from trap_signature import TrapSignature
# from spoof_filter import SpoofFilter

def main():
    chart = ChartReader()
    validator = ValidatorStack()
    log = LogHandler()
    error_reporter = ErrorReporter(log)
    interpreter = SignalInterpreter(chart, validator)

    try:
        signal = interpreter.generate_signal()
        if not signal:
            print("[Main] No valid signal generated.")
            return

        # Validate signal
        result = validator.run_all(signal)
        if not result["pass"]:
            print(f"[Main] Signal rejected by validator: {result['reason']}")
            return

        # Process through DAN1 core
        is_valid = core_logic_dan1(signal)
        print(f"[Main] DAN1 decision: {is_valid}")
        log.log({"signal": signal, "accepted": is_valid})

    except Exception as e:
        error_reporter.capture(e, context="main()")

if __name__ == "__main__":
    main()