"""CI check: no route is reachable without logging in, except an explicit public allowlist.

Walks the whole Flask URL map, so a new route added without @login_required fails here.
Needs the running stack (database), e.g. inside the web container:
    docker compose exec web python -m pytest tests/test_exposed_routes.py
Skipped when DATABASE_URL is not set.
"""

import os

import pytest

# Endpoints that are meant to be reachable anonymously.
PUBLIC_ENDPOINTS = {
    "static",
    "auth.login",
    "auth.verify_2fa",       # redirects to login unless a password step is pending
    "auth.register",         # fan self-registration
    "auth.google_login",
    "auth.google_callback",
    "auth.accept_invite",    # protected by the single-use invitation token
}

# Anonymous responses that mean "not exposed".
PROTECTED_STATUS = {401, 403, 404, 405}


@pytest.fixture(scope="module")
def client():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set (run inside the web container)")
    from app import create_app

    app = create_app()
    app.config["RATELIMIT_ENABLED"] = False
    return app.test_client(), app


def _sample_url(app, rule):
    args = {arg: "00000000-0000-0000-0000-000000000000" for arg in rule.arguments}
    with app.test_request_context():
        from flask import url_for

        return url_for(rule.endpoint, **args)


def test_every_non_public_route_requires_login(client):
    c, app = client
    exposed, checked = [], 0
    for rule in app.url_map.iter_rules():
        if rule.endpoint in PUBLIC_ENDPOINTS:
            continue
        url = _sample_url(app, rule)
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            checked += 1
            r = c.open(url, method=method)
            to_login = r.status_code in (301, 302, 303) and "/login" in r.headers.get("Location", "")
            if not (to_login or r.status_code in PROTECTED_STATUS):
                exposed.append(f"{method} {url} ({rule.endpoint}) -> {r.status_code}")
    assert checked > 10
    assert not exposed, "Routes reachable without login:\n" + "\n".join(exposed)


def test_public_allowlist_is_current(client):
    """Fail if an allowlisted endpoint disappears, so the list never silently grows stale."""
    _, app = client
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    assert PUBLIC_ENDPOINTS <= endpoints, PUBLIC_ENDPOINTS - endpoints
