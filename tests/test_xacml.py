"""XACML 3.0 access control: request building, response parsing, and policy parity.

The parity test needs a running AuthzForce server:
    AUTHZFORCE_URL=http://authzforce:8080 pytest tests/test_xacml.py
Without AUTHZFORCE_URL it is skipped.
"""

import itertools
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import xacml
from app.policy import _xacml_attributes, local_can_access

NOW = datetime.now(timezone.utc)
PAST = NOW - timedelta(days=2)
FUTURE = NOW + timedelta(days=2)


def _user(roles, status="active", band_id="band-1"):
    memberships = [
        SimpleNamespace(role=r, band_id=None if r == "administrator" else band_id) for r in roles
    ]
    return SimpleNamespace(id="u1", status=status, memberships=memberships)


def _item(**kwargs):
    defaults = dict(
        id="c1",
        band_id="band-1",
        is_deleted=False,
        is_public=False,
        audience_level="band",
        category="new_music",
        available_from_press=None,
        available_from_fans=None,
        grants=[],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _grant(action, valid_from=None, valid_until=None, revoked=False):
    return SimpleNamespace(
        user_id="u1", action=action, revoked=revoked, valid_from=valid_from, valid_until=valid_until
    )


# ============================================================
# Offline: request / response handling
# ============================================================

def test_build_request_contains_all_categories_and_escapes_values():
    user = _user(["press"])
    item = _item(id='c1"><evil/>', audience_level="press", available_from_press=FUTURE)
    subject, resource = _xacml_attributes(user, item, NOW)
    body = xacml.build_request(subject, resource, "download", NOW)

    root = ET.fromstring(body)  # still well-formed: values are escaped, not injected
    ns = {"x": xacml.XACML_NS}
    cats = {a.get("Category") for a in root.findall("x:Attributes", ns)}
    assert cats == {xacml.CAT_SUBJECT, xacml.CAT_RESOURCE, xacml.CAT_ACTION, xacml.CAT_ENV}
    ids = {a.get("AttributeId"): [v.text for v in a] for a in root.iter(f"{{{xacml.XACML_NS}}}Attribute")}
    assert ids["urn:oasis:names:tc:xacml:1.0:resource:resource-id"] == ['c1"><evil/>']
    assert ids["urn:oasis:names:tc:xacml:2.0:subject:role"] == ["press"]
    assert ids["urn:oasis:names:tc:xacml:1.0:action:action-id"] == ["download"]
    assert "urn:snap:resource:available-from-fans" not in ids  # absent -> empty bag


def test_parse_response_reads_decision_and_deny_reason():
    body = f"""<Response xmlns="{xacml.XACML_NS}"><Result><Decision>Deny</Decision>
      <AssociatedAdvice><Advice AdviceId="urn:snap:advice:deny">
        <AttributeAssignment AttributeId="{xacml.DENY_REASON_ID}"
          DataType="http://www.w3.org/2001/XMLSchema#string">embargo</AttributeAssignment>
      </Advice></AssociatedAdvice></Result></Response>"""
    assert xacml.parse_response(body) == ("Deny", "embargo")


def test_evaluate_fails_closed_without_pdp(monkeypatch):
    monkeypatch.setattr(xacml, "_domain_id", None)
    subject, resource = _xacml_attributes(_user(["band_member"]), _item(), NOW)
    assert xacml.evaluate(subject, resource, "view", NOW) == (False, "pdp_unavailable")


def test_evaluate_fails_closed_on_unreachable_pdp(monkeypatch):
    monkeypatch.setattr(xacml, "_domain_id", "dom")
    monkeypatch.setattr(xacml, "_base_url", "http://127.0.0.1:9")
    subject, resource = _xacml_attributes(_user(["band_member"]), _item(), NOW)
    assert xacml.evaluate(subject, resource, "view", NOW) == (False, "pdp_unavailable")


# ============================================================
# Online: AuthzForce decisions == documented rules
# ============================================================

ROLE_SETS = [
    [], ["registered"], ["fan_club"], ["press"], ["crew"], ["band_member"],
    ["administrator"], ["administrator", "band_member"],
]
AUDIENCES = ["public", "fan_club", "press", "crew", "band", "restricted"]
ACTIONS = ["view", "stream", "download", "manage"]
WINDOWS = [None, PAST, FUTURE]
GRANTS = [
    [],
    [_grant("download")],
    [_grant("view", valid_until=PAST)],      # expired
    [_grant("view", revoked=True)],          # revoked
    [_grant("view", valid_from=FUTURE)],     # not yet valid
]


@pytest.fixture(scope="module")
def pdp():
    url = os.getenv("AUTHZFORCE_URL")
    if not url:
        pytest.skip("AUTHZFORCE_URL not set")
    xacml.init_pdp(url, retries=5)
    yield
    xacml._domain_id = None


def _cases():
    for roles, audience, action, window, grants in itertools.product(
        ROLE_SETS, AUDIENCES, ACTIONS, WINDOWS, GRANTS
    ):
        yield _user(roles), _item(
            audience_level=audience,
            is_public=audience == "public",
            available_from_press=window,
            available_from_fans=window,
            grants=grants,
        ), action
    # deleted items and inactive accounts
    for roles in ROLE_SETS:
        yield _user(roles), _item(is_deleted=True, grants=[_grant("view")]), "view"
        yield _user(roles, status="disabled"), _item(audience_level="public", is_public=True), "view"


def test_authzforce_matches_documented_rules(pdp):
    mismatches = []
    n = 0
    for user, item, action in _cases():
        n += 1
        subject, resource = _xacml_attributes(user, item, NOW)
        got = xacml.evaluate(subject, resource, action, NOW)
        expected = local_can_access(user, item, action)
        if got != expected:
            mismatches.append((subject["roles"], item.audience_level, action,
                               item.available_from_press, item.grants, expected, got))
    assert not mismatches, f"{len(mismatches)}/{n} mismatches, first: {mismatches[:3]}"
    assert n > 1000
