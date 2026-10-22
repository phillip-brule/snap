import uuid
from datetime import datetime, timezone

from flask_login import UserMixin
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.extensions import db

# Argon2id (argon2-cffi default, RFC 9106 parameters) with a random unique salt per hash.
ph = PasswordHasher()


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


class Label(db.Model):
    __tablename__ = "labels"

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    name = db.Column(db.Text, nullable=False, unique=True)
    slug = db.Column(db.Text, nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    bands = db.relationship("Band", back_populates="label")
    users = db.relationship("User", back_populates="label")


class Band(db.Model):
    __tablename__ = "bands"

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    label_id = db.Column(db.String(36), db.ForeignKey("labels.id"), nullable=False, index=True)
    name = db.Column(db.Text, nullable=False)
    slug = db.Column(db.Text, nullable=False, unique=True)
    bio = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    label = db.relationship("Label", back_populates="bands")
    content_items = db.relationship("ContentItem", back_populates="band")
    memberships = db.relationship("Membership", back_populates="band")


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    label_id = db.Column(db.String(36), db.ForeignKey("labels.id"), nullable=False)
    email = db.Column(db.Text, nullable=False, unique=True)
    display_name = db.Column(db.Text, nullable=False)
    account_type = db.Column(db.Text, nullable=False)  # professional | fan
    status = db.Column(db.Text, nullable=False, default="active")  # pending | active | disabled
    password_hash = db.Column(db.Text)
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    last_login_at = db.Column(db.DateTime(timezone=True))
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime(timezone=True))
    totp_secret = db.Column(db.Text)
    totp_enabled = db.Column(db.Boolean, nullable=False, default=False)

    label = db.relationship("Label", back_populates="users")
    memberships = db.relationship("Membership", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = ph.hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        try:
            ph.verify(self.password_hash, password)
        except (VerificationError, InvalidHashError):
            return False
        if ph.check_needs_rehash(self.password_hash):
            self.password_hash = ph.hash(password)
        return True

    def roles_for_band(self, band_id):
        return [m.role for m in self.memberships if m.band_id == band_id]

    def has_role(self, role, band_id=None):
        for m in self.memberships:
            if m.role != role:
                continue
            if role == "administrator" and m.band_id is None:
                return True
            if band_id is None or m.band_id == band_id:
                return True
        return False

    def is_admin(self):
        return self.has_role("administrator")

    def is_band_member(self, band_id):
        return self.has_role("band_member", band_id)


class Membership(db.Model):
    __tablename__ = "memberships"

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    band_id = db.Column(db.String(36), db.ForeignKey("bands.id"), nullable=True, index=True)
    role = db.Column(db.Text, nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    user = db.relationship("User", back_populates="memberships")
    band = db.relationship("Band", back_populates="memberships")


class Invitation(db.Model):
    __tablename__ = "invitations"

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    label_id = db.Column(db.String(36), db.ForeignKey("labels.id"), nullable=False)
    invited_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    email = db.Column(db.Text, nullable=False, index=True)
    intended_role = db.Column(db.Text, nullable=False)
    band_id = db.Column(db.String(36), db.ForeignKey("bands.id"), nullable=True)
    token_hash = db.Column(db.Text, nullable=False, unique=True)
    status = db.Column(db.Text, nullable=False, default="pending")
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    accepted_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)


class ContentItem(db.Model):
    __tablename__ = "content_items"

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    band_id = db.Column(db.String(36), db.ForeignKey("bands.id"), nullable=False, index=True)
    uploaded_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.Text, nullable=False, index=True)
    audience_level = db.Column(db.Text, nullable=False, index=True)
    mime_type = db.Column(db.Text)
    size_bytes = db.Column(db.BigInteger)
    original_filename = db.Column(db.Text)
    storage_path = db.Column(db.Text, nullable=False)
    wrapped_dek = db.Column(db.LargeBinary)  # AES-GCM sealed DEK (nonce|tag|dek)
    checksum_sha256 = db.Column(db.Text)
    available_from_press = db.Column(db.DateTime(timezone=True))
    available_from_fans = db.Column(db.DateTime(timezone=True))
    is_public = db.Column(db.Boolean, nullable=False, default=False)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    band = db.relationship("Band", back_populates="content_items")
    uploader = db.relationship("User", foreign_keys=[uploaded_by_user_id])
    grants = db.relationship("ContentGrant", back_populates="content_item", cascade="all, delete-orphan")


class ContentGrant(db.Model):
    __tablename__ = "content_grants"

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    content_item_id = db.Column(db.String(36), db.ForeignKey("content_items.id"), nullable=False, index=True)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    action = db.Column(db.Text, nullable=False)
    valid_from = db.Column(db.DateTime(timezone=True))
    valid_until = db.Column(db.DateTime(timezone=True))
    granted_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    revoked = db.Column(db.Boolean, nullable=False, default=False, index=True)

    content_item = db.relationship("ContentItem", back_populates="grants")
    user = db.relationship("User", foreign_keys=[user_id])
    granted_by = db.relationship("User", foreign_keys=[granted_by_user_id])


class AccessLog(db.Model):
    __tablename__ = "access_logs"

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    content_item_id = db.Column(db.String(36), db.ForeignKey("content_items.id"), nullable=True, index=True)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=True, index=True)
    action = db.Column(db.Text, nullable=False)
    outcome = db.Column(db.Text, nullable=False)
    ip_address = db.Column(db.Text)
    user_agent = db.Column(db.Text)
    deny_reason = db.Column(db.Text)
    at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    content_item = db.relationship("ContentItem")
    user = db.relationship("User")


# Public-facing label sections (dashboard grouping). Audience still controls who sees each item.
CATEGORIES = ["new_music", "merch", "band_pages", "news"]
CATEGORY_LABELS = {
    "new_music": "New Music",
    "merch": "Merch",
    "band_pages": "Band Pages",
    "news": "News",
}
AUDIENCE_LEVELS = ["public", "fan_club", "press", "crew", "band", "restricted"]
ACTIONS = ["view", "stream", "download", "manage"]
ROLES = ["administrator", "band_member", "crew", "press", "fan_club", "registered"]
# Crew used to key off file-type categories; with section categories they rely on audience_level.
CREW_CATEGORIES = set()
