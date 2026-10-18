"""A bad update must not evict the last usable strategy version."""
import pytest
from flinttrade_engine.strategy_hot_reload import StrategyHotReloader

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("source", ["class Strategy(: pass", "class Strategy: pass\nraise ValueError('failed')", "class Strategy: pass\nStrategy = 42"])
def test_bad_reload_retains_incumbent_without_stopping_it(tmp_path, source):
    path = tmp_path / "candidate.py"
    path.write_text("class Strategy:\n    version = 1\n")
    stops = []
    reloader = StrategyHotReloader(tmp_path, stop_callback=stops.append)
    incumbent = reloader.load("candidate")
    path.write_text(source)
    assert reloader.reload("candidate")[0] is False
    assert reloader.load("candidate") is incumbent
    assert stops == []


def test_same_size_same_timestamp_reload_executes_changed_source_not_cached_pyc(tmp_path):
    import os
    path = tmp_path / "candidate.py"
    path.write_text("class Strategy:\n    version = 1\n")
    stamp = path.stat().st_mtime_ns
    import py_compile
    py_compile.compile(str(path), doraise=True)
    reloader = StrategyHotReloader(tmp_path)
    reloader.load("candidate")
    path.write_text("class Strategy:\n    version = 2\n")
    os.utime(path, ns=(stamp, stamp))
    assert reloader.reload("candidate")[0] is True
    assert reloader.load("candidate").version == 2


def test_stop_callback_failure_does_not_publish_candidate(tmp_path):
    path = tmp_path / "candidate.py"
    path.write_text("class Strategy:\n    version = 1\n")
    def stop(name):
        raise RuntimeError("handover refused")
    reloader = StrategyHotReloader(tmp_path, stop_callback=stop)
    old = reloader.load("candidate")
    path.write_text("class Strategy:\n    version = 2\n")
    assert reloader.reload("candidate")[0] is False
    assert reloader.load("candidate") is old
