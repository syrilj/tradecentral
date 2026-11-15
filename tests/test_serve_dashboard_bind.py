"""The legacy dashboard server stays on loopback and does not advertise CORS *."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "tools" / "serve_dashboard.py"
    spec = importlib.util.spec_from_file_location("serve_dashboard_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bind_host_is_loopback_and_wildcard_cors_is_gone():
    module = _load()
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert module.LOOPBACK_HOST == "127.0.0.1"
    assert 'ThreadedHTTPServer((LOOPBACK_HOST, port_candidate)' in source
    assert 'ThreadedHTTPServer(("",' not in source
    assert "Access-Control-Allow-Origin" not in source


def test_cross_origin_trigger_is_refused_and_get_is_not_a_scan():
    module = _load()
    assert module.host_is_loopback("127.0.0.1")
    assert module.host_is_loopback("::1")
    assert not module.host_is_loopback("10.0.0.8")
    assert not module.host_is_loopback("")
    assert module.origin_is_loopback(None)
    assert module.origin_is_loopback("http://127.0.0.1:8080")
    assert module.origin_is_loopback("http://localhost:8080")
    assert not module.origin_is_loopback("https://evil.example")
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "use POST /api/trigger_scan" in source
    assert source.count("generate_dashboard_html()") == 2
