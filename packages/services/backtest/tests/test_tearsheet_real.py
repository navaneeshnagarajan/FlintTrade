"""Real QuantStats rendering with synthetic returns and no network access."""

import socket
import tempfile
from functools import partial
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import pytest

matplotlib.use("Agg")

from flinttrade_backtest import tearsheet  # noqa: E402


@pytest.fixture
def offline_render(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Keep temporary reports observable and reject accidental data downloads."""
    def deny_network(*_args, **_kwargs):
        raise AssertionError("Tearsheet tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    monkeypatch.setattr(
        tearsheet, "TemporaryDirectory", partial(tempfile.TemporaryDirectory, dir=tmp_path),
    )
    assert tearsheet._QS_AVAILABLE, "The declared QuantStats dependency must be installed"
    return tmp_path


@pytest.mark.parametrize("with_benchmark", [False, True])
def test_full_tearsheet_renders_real_report_and_removes_temporary_files(
    offline_render: Path, with_benchmark: bool,
) -> None:
    rng = np.random.default_rng(8123)
    dates = pd.bdate_range("2021-01-04", periods=756)
    returns = pd.Series(rng.normal(0.0005, 0.012, len(dates)), index=dates, name="Synthetic strategy")
    benchmark = returns.shift(2).fillna(0) * 0.6 if with_benchmark else None

    title = "Offline report — ₹"
    html = tearsheet.generate_tearsheet(returns, benchmark_returns=benchmark, title=title)

    assert "Tearsheet Unavailable" not in html
    assert "Tearsheet generation failed" not in html
    assert html.count(title) >= 2  # QuantStats output and the injected brand header.
    assert "FlintTrade" in html
    assert "CAGR" in html
    assert "Sharpe" in html
    assert "<svg" in html or "data:image" in html
    assert len(html) > 10000
    assert list(offline_render.iterdir()) == []


def test_failed_render_removes_partial_report_and_returns_error_stub(
    offline_render: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_after_write(_returns, *, output, **_kwargs):
        Path(output).write_text("partial report", encoding="utf-8")
        raise RuntimeError("synthetic rendering failure")

    monkeypatch.setattr(tearsheet.qs.reports, "html", fail_after_write)
    html = tearsheet.generate_tearsheet(pd.Series(dtype=float), title="Failed report")

    assert "Tearsheet Unavailable" in html
    assert "Tearsheet generation failed: synthetic rendering failure" in html
    assert "partial report" not in html
    assert list(offline_render.iterdir()) == []
