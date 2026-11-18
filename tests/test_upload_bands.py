"""Upload goes to the uploader's own band, never to a band chosen by someone outside it.

Creates a throwaway second band (like U3) and its members, then cleans them up.
Needs the running stack (database), e.g. inside the web container:
    docker compose exec web python -m pytest tests/test_upload_bands.py
Skipped when DATABASE_URL is not set.
"""

import io
import os
import re
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

BASE = "https://localhost"


@pytest.fixture(scope="module")
def env():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set (run inside the web container)")
    from app import create_app
    from app.extensions import db
    from app.models import Band, ContentItem, Label, Membership, User

    app = create_app()
    app.config["RATELIMIT_ENABLED"] = False
    tag = uuid.uuid4().hex[:8]

    # No app context stays open during the requests: Flask-Login caches the
    # current user on it, so every request would see the first user.
    with app.app_context():
        label = Label.query.filter_by(slug="snap-records").first()
        snap = Band.query.filter_by(slug="snap").first()
        other = Band(label_id=label.id, name=f"U3 test {tag}", slug=f"u3-test-{tag}")
        db.session.add(other)
        db.session.flush()

        def member(name, *bands):
            # professional accounts are sent to 2FA setup until TOTP is on
            u = User(label_id=label.id, display_name=name, account_type="professional",
                     status="active", email_verified=True, totp_enabled=True)
            u.email = f"{name}-{tag}@example.test"
            db.session.add(u)
            db.session.flush()
            for b in bands:
                db.session.add(Membership(user_id=u.id, band_id=b.id, role="band_member"))
            return u.id

        e = SimpleNamespace(
            app=app,
            snap_id=snap.id,
            other_id=other.id,
            other_name=other.name,
            u3=member("u3-member", other),
            both=member("two-band-member", snap, other),
            fan=User.find_by_email("fan@example.com").id,
        )
        db.session.commit()

    yield e

    with app.app_context():
        for item in ContentItem.query.filter_by(band_id=e.other_id).all():
            shutil.rmtree(Path(app.config["UPLOAD_FOLDER"]) / item.id, ignore_errors=True)
            db.session.delete(item)
        for uid in (e.u3, e.both):
            Membership.query.filter_by(user_id=uid).delete()
            db.session.delete(db.session.get(User, uid))
        db.session.delete(db.session.get(Band, e.other_id))
        db.session.commit()


def _client(e, user_id):
    c = e.app.test_client()
    with c.session_transaction(base_url=BASE) as s:
        s["_user_id"] = user_id
        s["_fresh"] = True
    return c


def _form(c):
    r = c.get("/content/upload", base_url=BASE)
    token = re.search(r'name="csrf_token" value="([^"]+)"', r.get_data(as_text=True))
    return r, token.group(1) if token else None


def _post(c, token, band_id, title):
    from app.models import AUDIENCE_LEVELS, CATEGORIES

    return c.post(
        "/content/upload",
        base_url=BASE,
        headers={"Referer": BASE + "/content/upload"},
        data={
            "csrf_token": token,
            "band_id": band_id,
            "title": title,
            "category": CATEGORIES[0],
            "audience_level": AUDIENCE_LEVELS[0],
            "file": (io.BytesIO(b"rider v1"), "rider.txt"),
        },
        content_type="multipart/form-data",
    )


def _items(e, title):
    from app.models import ContentItem

    with e.app.app_context():
        return [i.band_id for i in ContentItem.query.filter_by(title=title).all()]


def test_member_of_other_band_can_open_upload(env):
    r, token = _form(_client(env, env.u3))
    page = r.get_data(as_text=True)
    assert r.status_code == 200 and token
    assert env.other_name in page and env.snap_id not in page


def test_upload_lands_in_own_band(env):
    c = _client(env, env.u3)
    _r, token = _form(c)
    r = _post(c, token, env.other_id, "u3 rider")
    assert r.status_code == 302 and "/content/" in r.headers["Location"]
    assert _items(env, "u3 rider") == [env.other_id]


def test_cannot_upload_to_a_band_you_are_not_in(env):
    c = _client(env, env.u3)
    _r, token = _form(c)
    r = _post(c, token, env.snap_id, "forged band id")
    assert r.status_code == 403
    assert _items(env, "forged band id") == []


def test_member_of_two_bands_picks_one(env):
    r, _token = _form(_client(env, env.both))
    page = r.get_data(as_text=True)
    assert '<select name="band_id"' in page
    assert env.snap_id in page and env.other_id in page


def test_non_member_gets_403(env):
    r = _client(env, env.fan).get("/content/upload", base_url=BASE)
    assert r.status_code == 403
