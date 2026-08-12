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
        assert '"flow_feed_contract": "market-wide-v1"' in source
        assert "frontend_is_current" in source
        assert "'/@vite/client'" in source
        assert "'/src/main.ts'" in source


def test_documented_launcher_executes_node_version_probe_instead_of_quoting_it():
    source = (ROOT / "tools" / "run_dashboard.sh").read_text()
    assert 'node -p \\"' not in source
    assert 'node -p "Number(process.versions.node.split' in source
