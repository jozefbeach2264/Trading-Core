class ValidatorStack: def init(self): self.validators = [ self._validate_spoof_and_compression, self._validate_apex_alignment, self._validate_liquidation_guard ]

def run_all(self, signal_context):
    for validator in self.validators:
        result = validator(signal_context)
        if not result["pass"]:
            return {"pass": False, "reason": result["reason"]}
    return {"pass": True, "reason": "All validators passed."}

def _validate_spoof_and_compression(self, ctx):
    if ctx.get("spoof_thinning", 0) < 9:
        return {"pass": False, "reason": "Spoof thinning too low."}
    if ctx.get("compression_candles", 0) > 3:
        return {"pass": False, "reason": "Too many compression candles."}
    return {"pass": True, "reason": "Passed spoof/compression."}

def _validate_apex_alignment(self, ctx):
    if not ctx.get("apex_confirmed", False):
        return {"pass": False, "reason": "Apex not confirmed."}
    return {"pass": True, "reason": "Apex aligned."}

def _validate_liquidation_guard(self, ctx):
    if ctx.get("liquidation_buffer", 0) < 10.00:
        return {"pass": False, "reason": "Insufficient liquidation buffer."}
    return {"pass": True, "reason": "Buffer clear."}