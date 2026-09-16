"""A crashing safety gate must count as a Block (fail closed), never as a pass."""
from conftest import run, make_market_state
from validator_stack import ValidatorStack


class _Boom:
    async def generate_report(self, _ms):
        raise RuntimeError("kaboom")


class _Pass:
    async def generate_report(self, _ms):
        return {"filter_name": "Pass", "score": 1.0, "flag": "✅ Hard Pass", "metrics": {}}


def test_filter_exception_counts_as_a_hard_block(config):
    stack = ValidatorStack(config)
    stack.primary_gate_filters = [_Boom(), _Pass()]
    report = run(stack.run_primary_gate(make_market_state(config)))
    assert report["hard_blocks"] == 1
    assert report["filters"]["_Boom"]["flag"] == "❌ Block"
    assert report["filters"]["_Boom"]["metrics"]["reason"] == "FILTER_EXCEPTION"
