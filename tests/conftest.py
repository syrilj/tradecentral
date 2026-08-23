"""Repo-wide pytest fixtures: make the default test session hermetic.

Several scan stages (see ``daily_plays/live_activity.py`` and
``daily_plays/adapters/flow.py``) probe ``LSE_API_KEY`` at call time and, when
it is set, dial out to the real ``api.londonstrategicedge.com`` provider with
a genuine network request and a real per-request timeout. If that credential
happens to be present in the process environment (e.g. via a developer's
shell profile or a loaded ``.env`` file), any test that exercises those code
paths without injecting its own fake fetcher silently becomes a live network
test: slow, non-deterministic, and dependent on an external vendor being
reachable.

The autouse fixture below neutralizes that credential for every test by
default, so the default suite never talks to the real provider. Individual
tests that legitimately want to exercise the real-credential branch of that
code (e.g. to assert on the "credential missing" vs. "credential present"
behavior itself) can still do so by calling
``monkeypatch.setenv("LSE_API_KEY", ...)`` themselves -- that call runs after
this fixture's setup and simply overrides it for the duration of that one
test, exactly as it would if this fixture did not exist.
"""
from __future__ import annotations

import pytest


# Provider credentials that must never be live by default in the test
# session. Extend this tuple if another vendor credential gains the same
# "probe env var, dial out if present" pattern.
_PROVIDER_ENV_VARS = ("LSE_API_KEY",)

# Deployment-posture variables that `tools.api_server` loads out of the
# developer's `.env` at import time (see its `load_project_environment` call).
# A workstation `.env` carrying `EDGE_AUTH_MODE=local` makes `_auth_required()`
# return False no matter what a test sets `EDGE_REQUIRE_AUTH` to, so the
# auth-posture tests in `tests/e2e/test_production_server_contract.py` fail on
# a configured machine while passing in CI, where no `.env` exists. Tests must
# exercise the code's own defaults; any test that wants a specific posture
# sets it explicitly with monkeypatch, which runs after this fixture.
_DEPLOYMENT_ENV_VARS = (
    "EDGE_AUTH_MODE",
    "EDGE_REQUIRE_AUTH",
    "EDGE_HOST",
    "EDGE_CORS_ORIGINS",
    "EDGE_ALLOWED_EMAILS",
    "EDGE_ALLOWED_USER_IDS",
    "CLERK_JWT_KEY",
    "CLERK_AUTHORIZED_PARTIES",
)


@pytest.fixture(autouse=True)
def _hermetic_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset live provider credentials so tests cannot silently hit the network.

    This runs for every collected test. ``monkeypatch`` restores the original
    environment automatically at the end of each test, so a test that sets
    the credential back explicitly (to test the "credential present" branch,
    or via an injected ``fetcher``/``flow_fetcher`` seam) is unaffected.
    """
    for name in (*_PROVIDER_ENV_VARS, *_DEPLOYMENT_ENV_VARS):
        monkeypatch.delenv(name, raising=False)
