class StrategyRouter:
    def __init__(self, scalpel, trapx, defcon6, rawstrike):
        self.modules = {
            "scalpel": scalpel,
            "trapx": trapx,
            "defcon6": defcon6,
            "rawstrike": rawstrike
        }
        self.fallback_order = ["scalpel", "trapx", "defcon6", "rawstrike"]

    def route(self, signal_payload):
        for name in self.fallback_order:
            module = self.modules.get(name)
            if module is None:
                continue
            try:
                result = module.evaluate(signal_payload)
                if result.get("valid", False):
                    return {
                        "selected": name,
                        "result": result
                    }
            except Exception as e:
                continue
        return {
            "selected": None,
            "result": {"valid": False, "reason": "No module accepted the signal"}
        }

    def override_module(self, name, module_obj):
        self.modules[name] = module_obj