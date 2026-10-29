"""XACML 3.0 client for the AuthzForce PDP/PAP (REST API).

Flask is the PEP: it gathers subject / resource / action / environment attributes
(acting as PIP), sends an XACML <Request> to AuthzForce and enforces the <Decision>.
Any error, NotApplicable or Indeterminate is treated as Deny (fail closed).
"""

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

XACML_NS = "urn:oasis:names:tc:xacml:3.0:core:schema:wd-17"
AZ_NS = "http://authzforce.github.io/rest-api-model/xmlns/authz/5"
ATOM_NS = "http://www.w3.org/2005/Atom"

CAT_SUBJECT = "urn:oasis:names:tc:xacml:1.0:subject-category:access-subject"
CAT_RESOURCE = "urn:oasis:names:tc:xacml:3.0:attribute-category:resource"
CAT_ACTION = "urn:oasis:names:tc:xacml:3.0:attribute-category:action"
CAT_ENV = "urn:oasis:names:tc:xacml:3.0:attribute-category:environment"

T_STRING = "http://www.w3.org/2001/XMLSchema#string"
T_BOOL = "http://www.w3.org/2001/XMLSchema#boolean"
T_DATETIME = "http://www.w3.org/2001/XMLSchema#dateTime"

DENY_REASON_ID = "urn:snap:advice:deny-reason"

POLICY_FILE = Path(__file__).resolve().parent.parent / "authz" / "snap-policy.xml"
ROOT_POLICY_ID = "snap-root"
DOMAIN_EXTERNAL_ID = "snap-records"
TIMEOUT = 3

_http = requests.Session()
_base_url = None
_domain_id = None


def is_enabled():
    return _domain_id is not None


def _url(path):
    return f"{_base_url}/authzforce-ce{path}"


def _xml(body):
    return body if isinstance(body, bytes) else body.encode("utf-8")


# ============================================================
# PAP bootstrap: domain + policy + root policy reference
# ============================================================

def init_pdp(base_url, retries=30, delay=2):
    """Create (or reuse) the SNAP domain in AuthzForce and load authz/snap-policy.xml.

    Idempotent: safe to call from every process start.
    """
    global _base_url, _domain_id
    _base_url = base_url.rstrip("/")
    for attempt in range(1, retries + 1):
        try:
            _domain_id = _ensure_domain()
            _ensure_policy()
            log.info("AuthzForce PDP ready (domain %s)", _domain_id)
            print(f"authz: XACML PDP at {_base_url}, domain {_domain_id}", flush=True)
            return
        except requests.RequestException as e:
            if attempt == retries:
                raise RuntimeError(f"AuthzForce unreachable at {_base_url}: {e}") from e
            time.sleep(delay)


def _ensure_domain():
    headers = {"Accept": "application/xml"}
    r = _http.get(_url("/domains"), params={"externalId": DOMAIN_EXTERNAL_ID},
                  headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    link = ET.fromstring(r.content).find(f"{{{ATOM_NS}}}link")
    if link is not None:
        return link.get("href")

    props = ET.Element(f"{{{AZ_NS}}}domainProperties", externalId=DOMAIN_EXTERNAL_ID)
    r = _http.post(_url("/domains"), data=ET.tostring(props, xml_declaration=True, encoding="utf-8"),
                   headers={"Content-Type": "application/xml", **headers}, timeout=TIMEOUT)
    r.raise_for_status()
    return ET.fromstring(r.content).get("href")


def _ensure_policy():
    policy = POLICY_FILE.read_bytes()
    version = ET.fromstring(policy).get("Version")
    headers = {"Content-Type": "application/xml", "Accept": "application/xml"}
    base = f"/domains/{_domain_id}/pap"

    r = _http.get(_url(f"{base}/policies/{ROOT_POLICY_ID}/{version}"),
                  headers={"Accept": "application/xml"}, timeout=TIMEOUT)
    if r.status_code == 404:
        r = _http.post(_url(f"{base}/policies"), data=policy, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
    else:
        r.raise_for_status()

    # Point the PDP at this exact version, so editing the file (and bumping Version) takes effect.
    upd = ET.Element(f"{{{AZ_NS}}}pdpPropertiesUpdate")
    ref = ET.SubElement(upd, f"{{{AZ_NS}}}rootPolicyRefExpression", Version=version)
    ref.text = ROOT_POLICY_ID
    r = _http.put(_url(f"{base}/pdp.properties"),
                  data=ET.tostring(upd, xml_declaration=True, encoding="utf-8"),
                  headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    applied = re.search(rb'rootPolicyRef Version="([^"]+)"', r.content)
    if applied and applied.group(1).decode() != version:
        raise RuntimeError(
            f"AuthzForce applied policy v{applied.group(1).decode()}, expected v{version}"
        )


# ============================================================
# PDP request / response
# ============================================================

def _xs_datetime(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _attr(parent, attr_id, data_type, values):
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    values = [v for v in values if v is not None]
    if not values:
        return  # absent attribute -> empty bag in the policy
    a = ET.SubElement(parent, f"{{{XACML_NS}}}Attribute",
                      AttributeId=attr_id, IncludeInResult="false")
    for v in values:
        if data_type == T_BOOL:
            text = "true" if v else "false"
        elif data_type == T_DATETIME:
            text = _xs_datetime(v)
        else:
            text = str(v)
        av = ET.SubElement(a, f"{{{XACML_NS}}}AttributeValue", DataType=data_type)
        av.text = text


def build_request(subject, resource, action, now=None):
    """Build the XACML 3.0 <Request> XML (bytes). ElementTree escapes every value."""
    now = now or datetime.now(timezone.utc)
    req = ET.Element(f"{{{XACML_NS}}}Request", ReturnPolicyIdList="false", CombinedDecision="false")

    s = ET.SubElement(req, f"{{{XACML_NS}}}Attributes", Category=CAT_SUBJECT)
    _attr(s, "urn:oasis:names:tc:xacml:1.0:subject:subject-id", T_STRING, subject["id"])
    _attr(s, "urn:snap:subject:status", T_STRING, subject["status"])
    _attr(s, "urn:oasis:names:tc:xacml:2.0:subject:role", T_STRING, sorted(subject["roles"]))
    _attr(s, "urn:snap:subject:granted-action", T_STRING, sorted(subject["granted_actions"]))

    r = ET.SubElement(req, f"{{{XACML_NS}}}Attributes", Category=CAT_RESOURCE)
    _attr(r, "urn:oasis:names:tc:xacml:1.0:resource:resource-id", T_STRING, resource["id"])
    _attr(r, "urn:snap:resource:band-id", T_STRING, resource["band_id"])
    _attr(r, "urn:snap:resource:category", T_STRING, resource["category"])
    _attr(r, "urn:snap:resource:audience-level", T_STRING, resource["audience_level"])
    _attr(r, "urn:snap:resource:is-deleted", T_BOOL, bool(resource["is_deleted"]))
    _attr(r, "urn:snap:resource:is-public", T_BOOL, bool(resource["is_public"]))
    _attr(r, "urn:snap:resource:available-from-press", T_DATETIME, resource["available_from_press"])
    _attr(r, "urn:snap:resource:available-from-fans", T_DATETIME, resource["available_from_fans"])

    a = ET.SubElement(req, f"{{{XACML_NS}}}Attributes", Category=CAT_ACTION)
    _attr(a, "urn:oasis:names:tc:xacml:1.0:action:action-id", T_STRING, action)

    e = ET.SubElement(req, f"{{{XACML_NS}}}Attributes", Category=CAT_ENV)
    _attr(e, "urn:oasis:names:tc:xacml:1.0:environment:current-dateTime", T_DATETIME, now)

    return ET.tostring(req, xml_declaration=True, encoding="utf-8")


def parse_response(body):
    """Return (decision, deny_reason) from an XACML <Response>."""
    root = ET.fromstring(body)
    result = root.find(f"{{{XACML_NS}}}Result")
    if result is None:
        return "Indeterminate", None
    decision = (result.findtext(f"{{{XACML_NS}}}Decision") or "Indeterminate").strip()
    reason = None
    for aa in result.iter(f"{{{XACML_NS}}}AttributeAssignment"):
        if aa.get("AttributeId") == DENY_REASON_ID:
            reason = (aa.text or "").strip() or None
            break
    return decision, reason


def evaluate(subject, resource, action, now=None):
    """Ask AuthzForce. Returns (allowed, deny_reason); fails closed."""
    if _domain_id is None:
        return False, "pdp_unavailable"
    try:
        r = _http.post(
            _url(f"/domains/{_domain_id}/pdp"),
            data=build_request(subject, resource, action, now),
            headers={"Content-Type": "application/xml", "Accept": "application/xml"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        decision, reason = parse_response(r.content)
    except (requests.RequestException, ET.ParseError):
        log.exception("XACML PDP request failed")
        return False, "pdp_unavailable"

    if decision == "Permit":
        return True, None
    if decision == "Deny":
        return False, reason or "role"
    log.warning("XACML PDP returned %s for action=%s resource=%s", decision, action, resource["id"])
    return False, "pdp_indeterminate"
