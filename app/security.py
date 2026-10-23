import base64
import io
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
import pyotp
import qrcode

# OWASP Password Storage Cheat Sheet — Argon2id
# Unique salt is generated per hash by argon2-cffi (salt_len=16).
ph = PasswordHasher(
    time_cost=2,
    memory_cost=19456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)

PASSWORD_MIN_LEN = 8
PASSWORD_MAX_LEN = 128
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15
TOTP_ISSUER = "SNAP Records"

# Constant-time-ish dummy verify when the email does not exist.
_DUMMY_HASH = ph.hash("not-a-real-password")


def validate_password(password: str) -> str | None:
    if len(password) < PASSWORD_MIN_LEN:
        return f"Password must be at least {PASSWORD_MIN_LEN} characters."
    if len(password) > PASSWORD_MAX_LEN:
        return f"Password must be at most {PASSWORD_MAX_LEN} characters."
    return None


def verify_dummy_password(password: str) -> None:
    try:
        ph.verify(_DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        pass


def lockout_deadline():
    return datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)


def totp_provisioning_uri(email: str, secret: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=TOTP_ISSUER)


def totp_qr_data_uri(email: str, secret: str) -> str:
    uri = totp_provisioning_uri(email, secret)
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def verify_totp(secret: str, code: str) -> bool:
    token = (code or "").replace(" ", "")
    if not secret or not token:
        return False
    try:
        return pyotp.TOTP(secret).verify(token, valid_window=1)
    except Exception:
        return False


def new_totp_secret() -> str:
    return pyotp.random_base32()
