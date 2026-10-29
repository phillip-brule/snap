import uuid
from datetime import datetime, timezone

from flask_login import UserMixin
from argon2.exceptions import InvalidHashError, VerificationError

from app.extensions import db
from app.security import ph


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
    email_enc = db.Column(db.LargeBinary, nullable=False)
    email_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    display_name = db.Column(db.Text, nullable=False)
    account_type = db.Column(db.Text, nullable=False)  # professional | fan
    status = db.Column(db.Text, nullable=False, default="active")  # pending | active | disabled
    password_hash = db.Column(db.Text)
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    last_login_at = db.Column(db.DateTime(timezone=True))
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime(timezone=True))
    totp_secret_enc = db.Column(db.LargeBinary)
    totp_enabled = db.Column(db.Boolean, nullable=False, default=False)
    contact_details_enc = db.Column(db.LargeBinary)

    label = db.relationship("Label", back_populates="users")
    memberships = db.relationship("Membership", back_populates="user", cascade="all, delete-orphan")

    @property
    def email(self):
        from app.crypto import decrypt_field

        if not self.email_enc:
            return None
        return decrypt_field(self.email_enc).decode("utf-8")

    @email.setter
    def email(self, value):
        from app.crypto import blind_index, encrypt_field

        norm = (value or "").strip().lower()
        self.email_enc = encrypt_field(norm.encode("utf-8"))
        self.email_hash = blind_index(norm)

    @property
    def totp_secret(self):
        from app.crypto import decrypt_field

        if not self.totp_secret_enc:
            return None
        return decrypt_field(self.totp_secret_enc).decode("utf-8")

    @totp_secret.setter
    def totp_secret(self, value):
        from app.crypto import encrypt_field

        if value is None:
            self.totp_secret_enc = None
        else:
            self.totp_secret_enc = encrypt_field(value.encode("utf-8"))

    @property
    def contact_details(self):
        from app.crypto import decrypt_field

        if not self.contact_details_enc:
            return None
        return decrypt_field(self.contact_details_enc).decode("utf-8")

    @contact_details.setter
    def contact_details(self, value):
        from app.crypto import encrypt_field

        text = (value or "").strip()
        if not text:
            self.contact_details_enc = None
        else:
            self.contact_details_enc = encrypt_field(text.encode("utf-8"))

    @classmethod
    def find_by_email(cls, email):
        from app.crypto import blind_index

        norm = (email or "").strip().lower()
        return User.query.filter_by(email_hash=blind_index(norm)).first()

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
    email_enc = db.Column(db.LargeBinary, nullable=False)
    intended_role = db.Column(db.Text, nullable=False)
    band_id = db.Column(db.String(36), db.ForeignKey("bands.id"), nullable=True)
    token_hash = db.Column(db.Text, nullable=False, unique=True)
    status = db.Column(db.Text, nullable=False, default="pending")
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    accepted_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    @property
    def email(self):
        from app.crypto import decrypt_field

        if not self.email_enc:
            return None
        return decrypt_field(self.email_enc).decode("utf-8")

    @email.setter
    def email(self, value):
        from app.crypto import encrypt_field

        norm = (value or "").strip().lower()
        self.email_enc = encrypt_field(norm.encode("utf-8"))


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
    contract_amount_enc = db.Column(db.LargeBinary)
    rider_fee_enc = db.Column(db.LargeBinary)
    available_from_press = db.Column(db.DateTime(timezone=True))
    available_from_fans = db.Column(db.DateTime(timezone=True))
    is_public = db.Column(db.Boolean, nullable=False, default=False)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    band = db.relationship("Band", back_populates="content_items")
    uploader = db.relationship("User", foreign_keys=[uploaded_by_user_id])
    grants = db.relationship("ContentGrant", back_populates="content_item", cascade="all, delete-orphan")

    @property
    def contract_amount(self):
        from app.crypto import decrypt_field

        if not self.contract_amount_enc:
            return None
        return decrypt_field(self.contract_amount_enc).decode("utf-8")

    @contract_amount.setter
    def contract_amount(self, value):
        from app.crypto import encrypt_field

        text = (value or "").strip()
        if not text:
            self.contract_amount_enc = None
        else:
            self.contract_amount_enc = encrypt_field(text.encode("utf-8"))

    @property
    def rider_fee(self):
        from app.crypto import decrypt_field

        if not self.rider_fee_enc:
            return None
        return decrypt_field(self.rider_fee_enc).decode("utf-8")

    @rider_fee.setter
    def rider_fee(self, value):
        from app.crypto import encrypt_field

        text = (value or "").strip()
        if not text:
            self.rider_fee_enc = None
        else:
            self.rider_fee_enc = encrypt_field(text.encode("utf-8"))


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
    ip_enc = db.Column(db.LargeBinary)
    user_agent = db.Column(db.Text)
    deny_reason = db.Column(db.Text)
    at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    content_item = db.relationship("ContentItem")
    user = db.relationship("User")

    @property
    def ip_address(self):
        from app.crypto import decrypt_field

        if not self.ip_enc:
            return None
        return decrypt_field(self.ip_enc).decode("utf-8")

    @ip_address.setter
    def ip_address(self, value):
        from app.crypto import encrypt_field

        if value is None:
            self.ip_enc = None
        else:
            self.ip_enc = encrypt_field(str(value).encode("utf-8"))


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
# ============================================================
# Google OAuth 2.0 / OpenID Connect Identity
# ============================================================

class OAuthIdentity(db.Model):
    __tablename__ = "oauth_identities"

    id = db.Column(
        db.String(36),
        primary_key=True,
        default=_uuid,
    )

    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    provider = db.Column(
        db.String(30),
        nullable=False,
    )

    subject = db.Column(
        db.Text,
        nullable=False,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_now,
    )

    __table_args__ = (
        db.UniqueConstraint(
            "provider",
            "subject",
            name="uq_oauth_provider_subject",
        ),
    )

    user = db.relationship(
        "User",
        backref="oauth_identities",
    )

class WatermarkDownload(db.Model):
    __tablename__ = "watermark_downloads"

    download_id = db.Column(
        db.String(36),
        primary_key=True,
    )

    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    content_id = db.Column(
        db.String(36),
        db.ForeignKey("content_items.id"),
        nullable=False,
        index=True,
    )

    watermark_type = db.Column(
        db.String(50),
        nullable=False,
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=_now,
    )
