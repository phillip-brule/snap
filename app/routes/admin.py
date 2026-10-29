import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Band, Invitation, Label, Membership, ROLES, User
from app.policy import can_admin

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _require_admin():
    if not can_admin(current_user):
        abort(403)


@bp.route("/")
@login_required
def index():
    _require_admin()
    label = Label.query.filter_by(slug="snap-records").first()
    bands = Band.query.order_by(Band.name).all()
    users = User.query.order_by(User.created_at.desc()).all()
    invites = Invitation.query.order_by(Invitation.created_at.desc()).limit(50).all()
    return render_template(
        "admin/index.html",
        label=label,
        bands=bands,
        users=users,
        invites=invites,
        roles=ROLES,
    )


@bp.route("/bands", methods=["POST"])
@login_required
def create_band():
    _require_admin()
    name = (request.form.get("name") or "").strip()
    slug = (request.form.get("slug") or "").strip().lower().replace(" ", "-")
    if not name or not slug:
        flash("Name and slug required.", "error")
    elif Band.query.filter_by(slug=slug).first():
        flash("Slug already exists.", "error")
    else:
        label = Label.query.filter_by(slug="snap-records").first()
        db.session.add(
            Band(label_id=label.id, name=name, slug=slug, bio=request.form.get("bio") or None)
        )
        db.session.commit()
        flash(f"Band {name} created.", "ok")
    return redirect(url_for("admin.index"))


@bp.route("/invite", methods=["POST"])
@login_required
def invite():
    _require_admin()
    email = (request.form.get("email") or "").strip().lower()
    role = request.form.get("role")
    band_id = request.form.get("band_id") or None
    if role == "administrator":
        band_id = None
    if not email or role not in ROLES:
        flash("Email and role required.", "error")
    elif role != "administrator" and not band_id:
        flash("Band required for non-admin roles.", "error")
    else:
        token = secrets.token_urlsafe(32)
        label = Label.query.filter_by(slug="snap-records").first()
        inv = Invitation(
            label_id=label.id,
            invited_by_user_id=current_user.id,
            intended_role=role,
            band_id=band_id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        inv.email = email
        db.session.add(inv)
        db.session.commit()
        link = url_for("auth.accept_invite", token=token, _external=True)
        flash(f"Invite created for {email}. Link: {link}", "ok")
    return redirect(url_for("admin.index"))


@bp.route("/users/<user_id>", methods=["POST"])
@login_required
def update_user(user_id):
    _require_admin()
    user = db.session.get(User, user_id) or abort(404)
    status = request.form.get("status")
    if status in ("active", "disabled", "pending"):
        user.status = status
    if request.form.get("verify"):
        user.email_verified = True
    if "contact_details" in request.form:
        user.contact_details = request.form.get("contact_details")

    role = request.form.get("add_role")
    band_id = request.form.get("band_id") or None
    if role in ROLES:
        if role == "administrator":
            band_id = None
        exists = Membership.query.filter_by(user_id=user.id, band_id=band_id, role=role).first()
        if not exists:
            db.session.add(Membership(user_id=user.id, band_id=band_id, role=role))

    remove_mid = request.form.get("remove_membership")
    if remove_mid:
        m = db.session.get(Membership, remove_mid)
        if m and m.user_id == user.id:
            db.session.delete(m)

    db.session.commit()
    flash("User updated.", "ok")
    return redirect(url_for("admin.index"))
