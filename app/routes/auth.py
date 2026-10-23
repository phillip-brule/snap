import hashlib
import secrets
from datetime import datetime, timezone

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.models import Invitation, Label, Membership, User

bp = Blueprint("auth", __name__)


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.find_by_email(email)
        if not user or not user.check_password(password):
            flash("Invalid email or password.", "error")
        elif user.status != "active":
            flash("Account is not active.", "error")
        else:
            user.last_login_at = datetime.now(timezone.utc)
            db.session.commit()
            login_user(user)
            next_url = request.args.get("next") or url_for("dashboard.index")
            return redirect(next_url)
    return render_template("auth/login.html")


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
        elif User.find_by_email(email):
            flash("Email already registered.", "error")
        else:
            label = Label.query.filter_by(slug="snap-records").first()
            user = User(
                label_id=label.id,
                display_name=display_name,
                account_type="fan",
                status="active",
                email_verified=False,
            )
            user.email = email
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            current_app.logger.info(
                "register: plain_email=%s email_hash=%s",
                email,
                user.email_hash,
            )
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
        if not display_name or not password:
            flash("Name and password required.", "error")
        else:
            existing = User.find_by_email(inv.email.lower())
            if existing:
                flash("Account already exists — log in.", "error")
                return redirect(url_for("auth.login"))
            user = User(
                label_id=inv.label_id,
                display_name=display_name,
                account_type="professional",
                status="active",
                email_verified=True,
            )
            user.email = inv.email.lower()
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
            flash("Account created.", "ok")
            return redirect(url_for("dashboard.index"))

    return render_template("auth/invite.html", invitation=inv)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
