"""Provider failures do not grant permission to substitute a source."""
import pytest

from flinttrade_historical.data_provider import ProviderBar, ProviderRegistry, ProviderResult

pytestmark = pytest.mark.unit


def test_registry_default_and_batch_stop_at_selected_source_failure():
    calls = []
    class Source:
        def __init__(self, name, fail):
            self.name, self.fail = name, fail
        def supports(self, exchange):
            return exchange == "TEST"
        def fetch(self, symbol, exchange, interval, start, end):
            calls.append(self.name)
            return ProviderResult(symbol, exchange, interval, provider=self.name,
                                  bars=[] if self.fail else [ProviderBar(timestamp="2026-01-01", close=1)],
                                  error="synthetic unavailable" if self.fail else "")
    registry = ProviderRegistry(extra_providers=[Source("chosen", True), Source("alternative", False)])
    result = registry.fetch("synthetic", "TEST", "1d", "2026-01-01", "2026-01-02")
    assert not result.success and calls == ["chosen"]
    calls.clear()
    results = registry.fetch_batch([{"symbol": "synthetic", "exchange": "TEST"}], "1d", "2026-01-01", "2026-01-02")
    assert not results[0].success and calls == ["chosen"]
    # The explicit caller opt-in remains a separate operation, not a default.
    result = registry.fetch("synthetic", "TEST", "1d", "2026-01-01", "2026-01-02", fallback=True)
    assert result.success and result.provider == "alternative"
