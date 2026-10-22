import hashlib
from datetime import datetime, timedelta, timezone

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db, limiter
from app.models import Invitation, Label, Membership, User
from app.security import (
    LOCKOUT_MINUTES,
    MAX_FAILED_LOGINS,
    new_totp_secret,
    totp_qr_data_uri,
    validate_password,
    verify_dummy_password,
    verify_totp,
)

bp = Blueprint("auth", __name__)

GENERIC_LOGIN_ERROR = "Invalid email or password."


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(dt):
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _safe_next(target):
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("dashboard.index")


def _register_failure(user, now):
    user.failed_attempts = (user.failed_attempts or 0) + 1
    if user.failed_attempts >= MAX_FAILED_LOGINS:
        user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
        user.failed_attempts = 0
    db.session.commit()


def _finish_login(user):
    if user.account_type == "professional" and user.totp_enabled:
        session["pending_2fa_user_id"] = user.id
        session["post_login_next"] = _safe_next(request.args.get("next"))
        return redirect(url_for("auth.verify_2fa"))

    user.last_login_at = datetime.now(timezone.utc)
    db.session.commit()
    login_user(user)
    if user.account_type == "professional" and not user.totp_enabled:
        flash("Set up two-factor authentication to continue.", "ok")
        return redirect(url_for("auth.setup_2fa"))
    return redirect(_safe_next(request.args.get("next")))


@bp.before_app_request
def _force_professional_2fa():
    if not current_user.is_authenticated:
        return
    if getattr(current_user, "account_type", None) != "professional":
        return
    if current_user.totp_enabled:
        return
    if request.endpoint in ("auth.setup_2fa", "auth.logout", "static"):
        return
    return redirect(url_for("auth.setup_2fa"))


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute;50 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()
        now = datetime.now(timezone.utc)

        if not user:
            verify_dummy_password(password)
            flash(GENERIC_LOGIN_ERROR, "error")
        elif user.locked_until and _aware(user.locked_until) > now:
            verify_dummy_password(password)
            flash(GENERIC_LOGIN_ERROR, "error")
        elif not user.check_password(password):
            _register_failure(user, now)
            flash(GENERIC_LOGIN_ERROR, "error")
        elif user.status != "active":
            flash("Account is not active.", "error")
        else:
            user.failed_attempts = 0
            user.locked_until = None
            db.session.commit()
            return _finish_login(user)
    return render_template("auth/login.html")


@bp.route("/login/2fa", methods=["GET", "POST"])
@limiter.limit("10 per minute;50 per hour", methods=["POST"])
def verify_2fa():
    user_id = session.get("pending_2fa_user_id")
    if not user_id:
        return redirect(url_for("auth.login"))
    user = db.session.get(User, user_id)
    if not user or not user.totp_enabled:
        session.pop("pending_2fa_user_id", None)
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        code = request.form.get("code") or ""
        if verify_totp(user.totp_secret, code):
            session.pop("pending_2fa_user_id", None)
            nxt = session.pop("post_login_next", None)
            user.last_login_at = datetime.now(timezone.utc)
            db.session.commit()
            login_user(user)
            return redirect(_safe_next(nxt))
        flash("Invalid authenticator code.", "error")
    return render_template("auth/verify_2fa.html")


@bp.route("/account/2fa", methods=["GET", "POST"])
@login_required
def setup_2fa():
    if current_user.account_type != "professional":
        return redirect(url_for("dashboard.index"))
    if current_user.totp_enabled:
        flash("Two-factor authentication is already enabled.", "ok")
        return redirect(url_for("dashboard.index"))

    if not current_user.totp_secret:
        current_user.totp_secret = new_totp_secret()
        db.session.commit()

    if request.method == "POST":
        code = request.form.get("code") or ""
        if verify_totp(current_user.totp_secret, code):
            current_user.totp_enabled = True
            db.session.commit()
            flash("Two-factor authentication enabled.", "ok")
            return redirect(url_for("dashboard.index"))
        flash("Invalid authenticator code. Scan the QR again and retry.", "error")

    qr = totp_qr_data_uri(current_user.email, current_user.totp_secret)
    return render_template(
        "auth/setup_2fa.html",
        qr_data_uri=qr,
        secret=current_user.totp_secret,
    )


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        display_name = (request.form.get("display_name") or "").strip()
        password = request.form.get("password") or ""
        pw_error = validate_password(password) if password else None
        if not email or not display_name or not password:
            flash("All fields are required.", "error")
        elif pw_error:
            flash(pw_error, "error")
        elif User.query.filter_by(email=email).first():
            flash("Email already registered.", "error")
        else:
            label = Label.query.filter_by(slug="snap-records").first()
            user = User(
                label_id=label.id,
                email=email,
                display_name=display_name,
                account_type="fan",
                status="active",
                email_verified=False,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            from app.models import Band

            band = Band.query.filter_by(slug="snap").first()
            db.session.add(
                Membership(user_id=user.id, band_id=band.id, role="registered")
            )
            db.session.commit()
            login_user(user)
            flash("Welcome to SNAP Records.", "ok")
            return redirect(url_for("dashboard.index"))
    return render_template("auth/register.html")


@bp.route("/invite/<token>", methods=["GET", "POST"])
def accept_invite(token):
    inv = Invitation.query.filter_by(token_hash=_hash_token(token), status="pending").first()
    if not inv:
        flash("Invitation invalid or already used.", "error")
        return redirect(url_for("auth.login"))
    expires = inv.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        inv.status = "expired"
        db.session.commit()
        flash("Invitation expired.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        display_name = (request.form.get("display_name") or "").strip()
        password = request.form.get("password") or ""
        pw_error = validate_password(password) if password else None
        if not display_name or not password:
            flash("Name and password required.", "error")
        elif pw_error:
            flash(pw_error, "error")
        else:
            existing = User.query.filter_by(email=inv.email.lower()).first()
            if existing:
                flash("Account already exists — log in.", "error")
                return redirect(url_for("auth.login"))
            user = User(
                label_id=inv.label_id,
                email=inv.email.lower(),
                display_name=display_name,
                account_type="professional",
                status="active",
                email_verified=True,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            db.session.add(
                Membership(
                    user_id=user.id,
                    band_id=inv.band_id if inv.intended_role != "administrator" else None,
                    role=inv.intended_role,
                )
            )
            inv.status = "accepted"
            inv.accepted_at = datetime.now(timezone.utc)
            db.session.commit()
            login_user(user)
            flash("Account created. Set up two-factor authentication.", "ok")
            return redirect(url_for("auth.setup_2fa"))

    return render_template("auth/invite.html", invitation=inv)


@bp.route("/logout")
@login_required
def logout():
    session.pop("pending_2fa_user_id", None)
    session.pop("post_login_next", None)
    logout_user()
    return redirect(url_for("auth.login"))