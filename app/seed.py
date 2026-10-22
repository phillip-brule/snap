"""Idempotent seed: SNAP Records, SNAP, sample users & content."""

import mimetypes
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import current_app

from app.extensions import db
from app.crypto import encrypt_data
from app.models import Band, ContentItem, Label, Membership, User


SAMPLE_USERS = [
    ("admin@snap.records", "Label Admin", "professional", "administrator", None, "admin123"),
    ("member@snap.band", "Alex SNAP", "professional", "band_member", "snap", "member123"),
    ("crew@snap.band", "Tour Manager", "professional", "crew", "snap", "crew123"),
    ("press@example.com", "Press Partner", "professional", "press", "snap", "press123"),
    ("fanclub@example.com", "Fan Club Member", "fan", "fan_club", "snap", "fanclub123"),
    ("fan@example.com", "Registered Fan", "fan", "registered", "snap", "fan123"),
]

# Old Delivery-01 sample titles → remove so dashboard isn't confusing
LEGACY_SAMPLE_TITLES = [
    "SNAP — Demo reel",
    "Tour EU 2026 rider",
    "SNAP — Album X master",
    "Fan BTS clip #1",
    "Public single artwork",
]

MEDIA_DIR = Path(__file__).resolve().parent / "static" / "inspo" / "media"


def _write_encrypted(folder: Path, name: str, plain: bytes) -> tuple[Path, bytes]:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    ciphertext, wrapped_dek = encrypt_data(plain)
    path.write_bytes(ciphertext)
    return path, wrapped_dek


def _copy_media(folder: Path, media_name: str) -> tuple[Path, bytes] | None:
    src = MEDIA_DIR / media_name
    if not src.is_file():
        print(f"Seed warning: missing media {src}")
        return None
    return _write_encrypted(folder, media_name, src.read_bytes())


def seed():
    label = Label.query.filter_by(slug="snap-records").first()
    if not label:
        label = Label(name="SNAP Records", slug="snap-records")
        db.session.add(label)
        db.session.flush()

    band = Band.query.filter_by(slug="snap").first()
    if not band:
        band = Band(
            label_id=label.id,
            name="SNAP",
            slug="snap",
            bio="SNAP Records roster act.",
        )
        db.session.add(band)
        db.session.flush()

    users_by_email = {}
    for email, name, acct, role, band_slug, password in SAMPLE_USERS:
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(
                label_id=label.id,
                email=email,
                display_name=name,
                account_type=acct,
                status="active",
                email_verified=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            bid = None if role == "administrator" else band.id
            db.session.add(Membership(user_id=user.id, band_id=bid, role=role))
        users_by_email[email] = user

    db.session.commit()

    for title in LEGACY_SAMPLE_TITLES:
        for old in ContentItem.query.filter_by(title=title, band_id=band.id, is_deleted=False).all():
            old.is_deleted = True
    db.session.commit()

    member = users_by_email["member@snap.band"]
    upload_root = Path(current_app.config["UPLOAD_FOLDER"])
    now = datetime.now(timezone.utc)

    samples = [
        {
            "title": "SNAP — Midnight (single)",
            "category": "new_music",
            "audience_level": "public",
            "description": "Public single — stream the video below.",
            "media": "media_6.mp4",
            "is_public": True,
        },
        {
            "title": "SNAP — Album X (press master)",
            "category": "new_music",
            "audience_level": "press",
            "description": "Press master — embargoed until the press window opens.",
            "media": "media_5.mp4",
            "available_from_press": now + timedelta(days=7),
            "is_public": False,
        },
        {
            "title": "SNAP — Studio demo pack",
            "category": "new_music",
            "audience_level": "band",
            "description": "Internal demos for the band only.",
            "media": "media_4.mp4",
            "is_public": False,
        },
        {
            "title": "SNAP logo tee",
            "category": "merch",
            "audience_level": "public",
            "description": "Merch drop — logo tee artwork.",
            "media": "media_1.jpg",
            "is_public": True,
        },
        {
            "title": "Tour hoodie (crew kit)",
            "category": "merch",
            "audience_level": "crew",
            "description": "Crew merch / kit reference photo.",
            "media": "media_2.jpg",
            "is_public": False,
        },
        {
            "title": "About SNAP",
            "category": "band_pages",
            "audience_level": "public",
            "description": "Band bio and links.",
            "filename": "about-snap.txt",
            "body": "SNAP is the flagship act on SNAP Records.\n",
            "is_public": True,
        },
        {
            "title": "EU 2026 tour rider",
            "category": "band_pages",
            "audience_level": "crew",
            "description": "Technical / hospitality rider.",
            "filename": "tour-rider.txt",
            "body": "Technical / hospitality rider (placeholder).\n",
            "is_public": False,
        },
        {
            "title": "Sync license draft",
            "category": "band_pages",
            "audience_level": "restricted",
            "description": "Restricted contract draft.",
            "filename": "sync-license.txt",
            "body": "Restricted contract draft.\n",
            "is_public": False,
        },
        {
            "title": "Tour dates announced",
            "category": "news",
            "audience_level": "public",
            "description": "Public news: tour dates announcement.",
            "media": "media_2.jpg",
            "is_public": True,
        },
        {
            "title": "Fan club BTS drop",
            "category": "news",
            "audience_level": "fan_club",
            "description": "Fan-club early BTS clip.",
            "media": "media_3.mp4",
            "available_from_fans": now - timedelta(days=1),
            "is_public": False,
        },
    ]

    for s in samples:
        existing = ContentItem.query.filter_by(title=s["title"], band_id=band.id).first()
        if existing and existing.is_deleted:
            item = existing
            item.is_deleted = False
        elif existing:
            item = existing
        else:
            item = ContentItem(
                band_id=band.id,
                uploaded_by_user_id=member.id,
                title=s["title"],
                category=s["category"],
                audience_level=s["audience_level"],
                storage_path="pending",
            )
            db.session.add(item)
            db.session.flush()

        item.uploaded_by_user_id = member.id
        item.description = s.get("description") or (s.get("body") or "").strip()
        item.category = s["category"]
        item.audience_level = s["audience_level"]
        item.is_public = s.get("is_public", False)
        item.available_from_press = s.get("available_from_press")
        item.available_from_fans = s.get("available_from_fans")

        folder = upload_root / item.id
        if s.get("media"):
            copied = _copy_media(folder, s["media"])
            if copied:
                path, wrapped_dek = copied
                item.storage_path = str(path)
                item.original_filename = s["media"]
                item.mime_type = mimetypes.guess_type(s["media"])[0] or "application/octet-stream"
                item.size_bytes = path.stat().st_size
                item.wrapped_dek = wrapped_dek
        else:
            fname = s.get("filename") or "note.txt"
            path, wrapped_dek = _write_encrypted(
                folder, fname, (s.get("body") or "").encode()
            )
            item.storage_path = str(path)
            item.original_filename = fname
            item.mime_type = "text/plain"
            item.size_bytes = path.stat().st_size
            item.wrapped_dek = wrapped_dek

    db.session.commit()
    print("Seed complete. Sample logins: admin@snap.records / admin123, member@snap.band / member123, …")


if __name__ == "__main__":
    from app import create_app

    app = create_app()
    with app.app_context():
        seed()
