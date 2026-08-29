from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
LAUNCHERS = (ROOT / "start_app.sh", ROOT / "tools" / "run_dashboard.sh")


def test_dashboard_launchers_have_valid_bash_syntax():
    for launcher in LAUNCHERS:
        subprocess.run(["bash", "-n", str(launcher)], check=True)


def test_dashboard_launchers_require_current_flow_contract_and_reuse_vite():
    for launcher in LAUNCHERS:
        source = launcher.read_text()
        assert '"flow_feed_contract":"market-wide-v1"' in source
        assert '"suggestion_contract":"paper-candidate-contract-v9"' in source
        assert '"gamma_regime_contract":"gamma-regime-v1"' in source
        assert "frontend_is_current" in source
        assert "'/@vite/client'" in source
        assert "'/src/main.ts'" in source


def test_launchers_match_health_contract_without_assuming_json_spacing():
    """`/api/health` is dumped with `separators=(",", ":")`.

    A launcher that greps for `"key": "value"` spacing can never match, so it
    classifies the backend it just started as stale and restarts it forever.
    Each launcher must strip spaces before matching.
    """
    for launcher in LAUNCHERS:
        source = launcher.read_text()
        assert "${health// /}" in source, f"{launcher.name} matches raw health JSON"
        assert '"flow_feed_contract": "market-wide-v1"' not in source
        assert '"suggestion_contract": "paper-candidate-contract-v9"' not in source
        assert '"gamma_regime_contract": "gamma-regime-v1"' not in source


def test_documented_launcher_executes_node_version_probe_instead_of_quoting_it():
    source = (ROOT / "tools" / "run_dashboard.sh").read_text()
    assert 'node -p \\"' not in source
    assert 'node -p "Number(process.versions.node.split' in source
