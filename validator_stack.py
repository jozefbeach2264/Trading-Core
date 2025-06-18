from trap_signature import TrapSignature
from spoof_filter import SpoofFilter
from apex_detector import ApexDetector

class ValidatorStack:
    def __init__(self):
        self.trap = TrapSignature()
        self.spoof = SpoofFilter()
        self.apex = ApexDetector()

    def run_all(self, signal):
        if signal.get("volume", 0) < 15000:
            return {"pass": False, "reason": "Low volume"}

        if abs(signal.get("high", 0) - signal.get("low", 0)) < 1.0:
            return {"pass": False, "reason": "Compression detected"}

        if not self.trap.detect(signal):
            return {"pass": False, "reason": "No trap signature"}

        if not self.apex.is_apex([signal]):
            return {"pass": False, "reason": "Apex not confirmed"}

        return {"pass": True, "reason": "All validators passed"}