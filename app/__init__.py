import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from flask_login import LoginManager

from app.extensions import db, limiter
from app.models import User
from app.crypto import set_kek

load_dotenv()

login_manager = LoginManager()
login_manager.login_view = "auth.login"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, user_id)


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://snap:snap@localhost:5432/snap_records",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    upload = Path(os.getenv("UPLOAD_FOLDER", "/tmp/snap_uploads"))
    upload.mkdir(parents=True, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = str(upload)
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
    app.config["CONTENT_KEK_PATH"] = os.getenv("CONTENT_KEK_PATH", "/run/secrets/content_kek")
    set_kek(app.config["CONTENT_KEK_PATH"])

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "0") == "1",
        RATELIMIT_STORAGE_URI="memory://",
    )

    db.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)

    from app.routes.auth import bp as auth_bp
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.content import bp as content_bp
    from app.routes.admin import bp as admin_bp
    from app.routes.logs import bp as logs_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(content_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(logs_bp)

    @app.errorhandler(403)
    def forbidden(_e):
        from flask import render_template

        return render_template("errors/403.html"), 403

    @app.errorhandler(429)
    def too_many(_e):
        return "429 - Too many requests. Please wait a minute and try again.", 429

    with app.app_context():
        db.create_all()

    return app
