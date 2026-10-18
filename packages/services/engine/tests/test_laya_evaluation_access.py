"""Benchmark flags are not sealed-test authority."""
import pytest
from flinttrade_engine.laya_benchmark import run_benchmark, BenchmarkCaseError

pytestmark = pytest.mark.unit


def test_claiming_test_once_without_core_access_control_is_refused_before_inference():
    class Forbidden:
        def decide(self, *args):
            pytest.fail("unsealed claim must not infer")
    with pytest.raises(BenchmarkCaseError, match="sealed"):
        run_benchmark([], Forbidden(), split="test", test_scored_once=True)
