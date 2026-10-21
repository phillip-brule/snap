
import hashlib
import secrets
from datetime import datetime, timezone

from authlib.integrations.base_client.errors import OAuthError
from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import (
    current_user,
    login_required,
    login_user,
    logout_user,
)
from sqlalchemy.exc import IntegrityError

from app import oauth
from app.extensions import db
from app.models import (
    Band,
    Invitation,
    Label,
    Membership,
    OAuthIdentity,
    User,
)


bp = Blueprint("auth", __name__)


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


# ============================================================
# Standard Login
# ============================================================

@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        user = User.query.filter_by(email=email).first()

        if not user or not user.check_password(password):
            flash("Invalid email or password.", "error")

        elif user.status != "active":
            flash("Account is not active.", "error")

        else:
            user.last_login_at = datetime.now(timezone.utc)
            db.session.commit()

            login_user(user)

            next_url = request.args.get("next")
            if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
                next_url = url_for("dashboard.index")

            return redirect(next_url)

    return render_template("auth/login.html")


# ============================================================
# Google OAuth Login
# ============================================================

@bp.route("/auth/google/login")
def google_login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    redirect_uri = url_for(
        "auth.google_callback",
        _external=True,
    )

    return oauth.google.authorize_redirect(redirect_uri)


# ============================================================
# Google OAuth Callback
# ============================================================

@bp.route("/auth/google/callback")
def google_callback():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    try:
        token = oauth.google.authorize_access_token()

        # Authlib validates the OIDC ID token.
        userinfo = token.get("userinfo")

        if not userinfo:
            raise ValueError("Missing verified user information")

    except (OAuthError, ValueError, KeyError):
        flash("Google authentication failed.", "error")
        return redirect(url_for("auth.login"))

    google_id = userinfo.get("sub")
    email = (userinfo.get("email") or "").strip().lower()
    email_verified = userinfo.get("email_verified") in (True, "true")

    if not google_id or not email or not email_verified:
        flash("Google account verification failed.", "error")
        return redirect(url_for("auth.login"))

    # Look for an existing linked Google identity.
    identity = OAuthIdentity.query.filter_by(
        provider="google",
        subject=google_id,
    ).first()

    if identity:
        user = db.session.get(User, identity.user_id)

        if not user or user.status != "active":
            flash("Account is not active.", "error")
            return redirect(url_for("auth.login"))

    else:
        # Never automatically take over an existing SNAP
        # account based on a matching email address.
        existing = User.query.filter_by(email=email).first()

        if existing:
            flash(
                "An account with this email already exists. "
                "Please sign in with your password.",
                "error",
            )
            return redirect(url_for("auth.login"))

        label = Label.query.filter_by(
            slug="snap-records"
        ).first()

        band = Band.query.filter_by(
            slug="snap"
        ).first()

        if not label or not band:
            flash("SNAP is not initialized.", "error")
            return redirect(url_for("auth.login"))

        # Create a new fan account with public-only access.
        user = User(
            label_id=label.id,
            email=email,
            display_name=userinfo.get("name") or email,
            account_type="fan",
            status="active",
            email_verified=True,
        )

        # No local password for Google-only accounts.
        db.session.add(user)
        db.session.flush()

        # Link SNAP user to Google identity.
        db.session.add(
            OAuthIdentity(
                user_id=user.id,
                provider="google",
                subject=google_id,
            )
        )

        # Assign the least-privileged membership.
        db.session.add(
            Membership(
                user_id=user.id,
                band_id=band.id,
                role="registered",
            )
        )

    user.last_login_at = datetime.now(timezone.utc)

    try:
        db.session.commit()

    except IntegrityError:
        db.session.rollback()

        flash(
            "Unable to complete Google sign-in.",
            "error",
        )
        return redirect(url_for("auth.login"))

    login_user(user)

    flash("Successfully signed in with Google!", "ok")

    return redirect(url_for("dashboard.index"))


# ============================================================
# Standard Registration
# ============================================================

@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        display_name = (request.form.get("display_name") or "").strip()
        password = request.form.get("password") or ""

        if not email or not display_name or not password:
            flash("All fields are required.", "error")

        elif User.query.filter_by(email=email).first():
            flash("Email already registered.", "error")

        else:
            label = Label.query.filter_by(
                slug="snap-records"
            ).first()

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

            band = Band.query.filter_by(
                slug="snap"
            ).first()

            db.session.add(
                Membership(
                    user_id=user.id,
                    band_id=band.id,
                    role="registered",
                )
            )

            db.session.commit()
            login_user(user)

            flash("Welcome to SNAP Records.", "ok")
            return redirect(url_for("dashboard.index"))

    return render_template("auth/register.html")


# ============================================================
# Invitation Registration
# ============================================================

@bp.route("/invite/<token>", methods=["GET", "POST"])
def accept_invite(token):
    inv = Invitation.query.filter_by(
        token_hash=_hash_token(token),
        status="pending",
    ).first()

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
        display_name = (
            request.form.get("display_name") or ""
        ).strip()

        password = request.form.get("password") or ""

        if not display_name or not password:
            flash("Name and password required.", "error")

        else:
            existing = User.query.filter_by(
                email=inv.email.lower()
            ).first()

            if existing:
                flash(
                    "Account already exists — log in.",
                    "error",
                )
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
                    band_id=(
                        inv.band_id
                        if inv.intended_role != "administrator"
                        else None
                    ),
                    role=inv.intended_role,
                )
            )

            inv.status = "accepted"
            inv.accepted_at = datetime.now(timezone.utc)

            db.session.commit()
            login_user(user)

            flash("Account created.", "ok")
            return redirect(url_for("dashboard.index"))

    return render_template(
        "auth/invite.html",
        invitation=inv,
    )


# ============================================================
# Logout
# ============================================================

@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
