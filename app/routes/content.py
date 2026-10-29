
import hashlib
import io
import mimetypes
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.crypto import decrypt_data, encrypt_data
from app.extensions import db
from app.models import (
    AUDIENCE_LEVELS,
    CATEGORIES,
    CATEGORY_LABELS,
    ACTIONS,
    Band,
    ContentGrant,
    ContentItem,
    User,
    WatermarkDownload,
)
from app.policy import can_access, can_upload, log_access
from app.watermark import SUPPORTED_TYPES, create_watermarked_copy

bp = Blueprint("content", __name__, url_prefix="/content")


# ============================================================
# Helpers
# ============================================================

def _parse_dt(value):
    if not value:
        return None

    dt = datetime.fromisoformat(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt


def _store_file(file_storage, item_id):
    folder = Path(current_app.config["UPLOAD_FOLDER"]) / item_id
    folder.mkdir(parents=True, exist_ok=True)

    name = secure_filename(file_storage.filename) or "upload.bin"
    path = folder / name
    ciphertext, wrapped_dek = encrypt_data(file_storage.read())
    path.write_bytes(ciphertext)
    checksum = hashlib.sha256(ciphertext).hexdigest()
    mime = (
        file_storage.mimetype
        or mimetypes.guess_type(name)[0]
        or "application/octet-stream"
    )
    return str(path), name, mime, len(ciphertext), checksum, wrapped_dek


def _decrypt_file(storage_path, wrapped_dek):
    with open(storage_path, "rb") as f:
        ciphertext = f.read()
    return decrypt_data(ciphertext, wrapped_dek)


# ============================================================
# Upload
# ============================================================

@bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    band = Band.query.filter_by(slug="snap").first()

    if not band:
        abort(404)

    if not can_upload(current_user, band.id):
        abort(403)

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        category = request.form.get("category")
        audience = request.form.get("audience_level")
        file = request.files.get("file")

        if (
            not title
            or category not in CATEGORIES
            or audience not in AUDIENCE_LEVELS
            or not file
            or not file.filename
        ):
            flash(
                "Title, category, audience, and file are required.",
                "error",
            )
        else:
            item = ContentItem(
                band_id=band.id,
                uploaded_by_user_id=current_user.id,
                title=title,
                description=(
                    request.form.get("description") or ""
                ).strip() or None,
                category=category,
                audience_level=audience,
                available_from_press=_parse_dt(
                    request.form.get("available_from_press")
                ),
                available_from_fans=_parse_dt(
                    request.form.get("available_from_fans")
                ),
                is_public=audience == "public",
                storage_path="pending",
            )

            db.session.add(item)
            db.session.flush()
            path, fname, mime, size, checksum, wrapped_dek = _store_file(file, item.id)
            item.storage_path = path
            item.original_filename = fname
            item.mime_type = mime
            item.size_bytes = size
            item.checksum_sha256 = checksum
            item.wrapped_dek = wrapped_dek

            db.session.commit()

            flash("Uploaded.", "ok")

            return redirect(
                url_for("content.detail", content_id=item.id)
            )

    return render_template(
        "content/upload.html",
        band=band,
        categories=CATEGORIES,
        category_labels=CATEGORY_LABELS,
        audiences=AUDIENCE_LEVELS,
    )


# ============================================================
# Content Details
# ============================================================

@bp.route("/<content_id>")
@login_required
def detail(content_id):
    item = db.session.get(ContentItem, content_id) or abort(404)

    allowed, reason = can_access(
        current_user,
        item,
        "view",
    )

    log_access(
        db,
        current_user,
        item,
        "view",
        allowed,
        reason,
        request,
    )

    if not allowed:
        abort(403)

    caps = {
        action: can_access(current_user, item, action)[0]
        for action in ("view", "stream", "download", "manage")
    }

    is_owner = current_user.is_band_member(item.band_id)

    return render_template(
        "content/detail.html",
        item=item,
        caps=caps,
        is_owner=is_owner,
    )


# ============================================================
# Download with Watermark + PostgreSQL Audit
# ============================================================

@bp.route("/<content_id>/download")
@login_required
def download(content_id):
    item = db.session.get(ContentItem, content_id) or abort(404)

    allowed, reason = can_access(
        current_user,
        item,
        "download",
    )

    log_access(
        db,
        current_user,
        item,
        "download",
        allowed,
        reason,
        request,
    )

    if not allowed:
        abort(403)

    if (
        not item.storage_path
        or not os.path.isfile(item.storage_path)
        or not item.wrapped_dek
    ):
        current_app.logger.warning(
            "Missing encrypted file for content %s",
            content_id,
        )
        abort(404)

    try:
        plaintext = _decrypt_file(item.storage_path, item.wrapped_dek)
    except Exception:
        current_app.logger.exception(
            "Decrypt failed for content %s", content_id
        )
        abort(500)

    # Per-download watermark in RAM (recipient + copy id); no /tmp plaintext
    if item.mime_type in SUPPORTED_TYPES:
        download_id = secrets.token_hex(8)
        try:
            data, mime, extension = create_watermarked_copy(
                data=plaintext,
                mime_type=item.mime_type,
                recipient_id=str(current_user.id),
                download_id=download_id,
            )
        except Exception:
            current_app.logger.exception(
                "Watermark generation failed for content %s",
                content_id,
            )
            abort(500)

        audit = WatermarkDownload(
            download_id=download_id,
            user_id=current_user.id,
            content_id=item.id,
            watermark_type=mime,
        )
        try:
            db.session.add(audit)
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to save watermark audit")
            abort(500)

        original_name = Path(item.original_filename or "download").stem
        filename = f"{original_name}_watermarked{extension}"
        response = send_file(
            data,
            as_attachment=True,
            download_name=filename,
            mimetype=mime,
        )
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    return send_file(
        io.BytesIO(plaintext),
        as_attachment=True,
        download_name=item.original_filename or "download",
        mimetype=item.mime_type,
    )


# ============================================================
# Stream
# ============================================================

@bp.route("/<content_id>/stream")
@login_required
def stream(content_id):
    item = db.session.get(ContentItem, content_id) or abort(404)

    allowed, reason = can_access(
        current_user,
        item,
        "stream",
    )

    log_access(
        db,
        current_user,
        item,
        "stream",
        allowed,
        reason,
        request,
    )

    if not allowed:
        abort(403)

    if (
        not item.storage_path
        or not os.path.isfile(item.storage_path)
        or not item.wrapped_dek
    ):
        abort(404)

    try:
        plaintext = _decrypt_file(item.storage_path, item.wrapped_dek)
    except Exception:
        current_app.logger.exception(
            "Decrypt failed for content %s", content_id
        )
        abort(500)

    return send_file(
        io.BytesIO(plaintext),
        as_attachment=False,
        mimetype=item.mime_type,
    )


# ============================================================
# Edit / Delete
# ============================================================

@bp.route("/<content_id>/edit", methods=["GET", "POST"])
@login_required
def edit(content_id):
    item = db.session.get(ContentItem, content_id) or abort(404)

    allowed, reason = can_access(
        current_user,
        item,
        "manage",
    )

    log_access(
        db,
        current_user,
        item,
        "manage",
        allowed,
        reason,
        request,
    )

    if not allowed:
        abort(403)

    if request.method == "POST":

        if request.form.get("delete"):
            item.is_deleted = True
            item.updated_at = datetime.now(timezone.utc)

            db.session.commit()

            flash("Content soft-deleted.", "ok")

            return redirect(url_for("dashboard.index"))

        title = (request.form.get("title") or "").strip()
        category = request.form.get("category")
        audience = request.form.get("audience_level")

        if (
            not title
            or category not in CATEGORIES
            or audience not in AUDIENCE_LEVELS
        ):
            flash("Invalid fields.", "error")

        else:
            item.title = title
            item.description = (
                request.form.get("description") or ""
            ).strip() or None

            item.category = category
            item.audience_level = audience
            item.available_from_press = _parse_dt(
                request.form.get("available_from_press")
            )
            item.available_from_fans = _parse_dt(
                request.form.get("available_from_fans")
            )
            item.is_public = audience == "public"
            item.updated_at = datetime.now(timezone.utc)

            file = request.files.get("file")

            if file and file.filename:

                if item.storage_path and os.path.isfile(
                    item.storage_path
                ):
                    try:
                        os.remove(item.storage_path)
                    except OSError:
                        pass
                path, fname, mime, size, checksum, wrapped_dek = _store_file(file, item.id)

                item.storage_path = path
                item.original_filename = fname
                item.mime_type = mime
                item.size_bytes = size
                item.checksum_sha256 = checksum
                item.wrapped_dek = wrapped_dek
            db.session.commit()

            flash("Saved.", "ok")

            return redirect(
                url_for("content.detail", content_id=item.id)
            )

    return render_template(
        "content/edit.html",
        item=item,
        categories=CATEGORIES,
        category_labels=CATEGORY_LABELS,
        audiences=AUDIENCE_LEVELS,
    )


# ============================================================
# Permissions
# ============================================================

@bp.route("/<content_id>/permissions", methods=["GET", "POST"])
@login_required
def permissions(content_id):
    item = db.session.get(ContentItem, content_id) or abort(404)

    allowed, reason = can_access(
        current_user,
        item,
        "manage",
    )

    if not allowed:
        log_access(
            db,
            current_user,
            item,
            "manage",
            False,
            reason,
            request,
        )
        abort(403)

    if request.method == "POST":
        action = request.form.get("form_action")

        if action == "update_meta":
            audience = request.form.get("audience_level")

            if audience in AUDIENCE_LEVELS:
                item.audience_level = audience
                item.available_from_press = _parse_dt(
                    request.form.get("available_from_press")
                )
                item.available_from_fans = _parse_dt(
                    request.form.get("available_from_fans")
                )
                item.is_public = audience == "public"
                item.updated_at = datetime.now(timezone.utc)

                db.session.commit()

                flash("Permissions updated.", "ok")

        elif action == "add_grant":
            email = (
                request.form.get("email") or ""
            ).strip().lower()

            grant_action = request.form.get("grant_action")
            user = User.find_by_email(email)
            if not user or grant_action not in ACTIONS:
                flash(
                    "Unknown user or invalid action.",
                    "error",
                )

            else:
                grant = ContentGrant(
                    content_item_id=item.id,
                    user_id=user.id,
                    action=grant_action,
                    valid_from=_parse_dt(
                        request.form.get("valid_from")
                    ),
                    valid_until=_parse_dt(
                        request.form.get("valid_until")
                    ),
                    granted_by_user_id=current_user.id,
                )

                db.session.add(grant)
                db.session.commit()

                flash("Grant added.", "ok")

        elif action == "revoke":
            grant_id = request.form.get("grant_id")
            grant = db.session.get(ContentGrant, grant_id)

            if grant and grant.content_item_id == item.id:
                grant.revoked = True
                db.session.commit()

                flash("Grant revoked.", "ok")

        return redirect(
            url_for(
                "content.permissions",
                content_id=item.id,
            )
        )

    grants = (
        ContentGrant.query
        .filter_by(content_item_id=item.id)
        .order_by(ContentGrant.created_at.desc())
        .all()
    )

    return render_template(
        "content/permissions.html",
        item=item,
        grants=grants,
        audiences=AUDIENCE_LEVELS,
        actions=ACTIONS,
    )
