import traceback

class ErrorReporter:
    def __init__(self, log_handler=None):
        self.log_handler = log_handler

    def capture(self, exception, context=""):
        error_info = {
            "error": str(exception),
            "trace": traceback.format_exc(),
            "context": context
        }
        print(f"[ERROR] {error_info}")
        if self.log_handler:
            self.log_handler.log({"type": "error", "details": error_info})