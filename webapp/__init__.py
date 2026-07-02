"""Flask application factory. All routes live in blueprints (see webapp/blueprints).

Shared concerns — Jinja filters, badge helpers, error handlers, context — live here so
each blueprint contains only its routes.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template

from cqc import CQCError
from phantombuster import PhantombusterError, parse_json_field, redact


def _register_jinja(app: Flask) -> None:
    @app.template_filter("ms")
    def ms_to_datetime(value):
        if value in (None, ""):
            return "—"
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
        except (ValueError, TypeError, OSError):
            return str(value)

    @app.template_filter("duration")
    def ms_to_duration(value):
        if value in (None, ""):
            return "—"
        try:
            total = int(value) // 1000
        except (ValueError, TypeError):
            return str(value)
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        parts = []
        if h:
            parts.append(f"{h}h")
        if h or m:
            parts.append(f"{m}m")
        parts.append(f"{s:02d}s")
        return " ".join(parts)

    def status_badge(status):
        return {
            "finished": "bg-success", "running": "bg-primary",
            "starting": "bg-info text-dark", "launch error": "bg-danger",
            "error": "bg-danger",
        }.get(status, "bg-secondary")

    def exit_badge(code):
        if code is None:
            return "bg-secondary"
        return "bg-success" if int(code) == 0 else "bg-danger"

    app.jinja_env.globals.update(status_badge=status_badge, exit_badge=exit_badge)
    app.context_processor(lambda: {"parse_json": parse_json_field, "redact": redact})


def _register_errors(app: Flask) -> None:
    @app.errorhandler(PhantombusterError)
    def _pb_error(err):
        return render_template("error.html", error=err), 502

    @app.errorhandler(CQCError)
    def _cqc_error(err):
        return jsonify({"error": str(err), "status": getattr(err, "status", None)}), 502


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "phantombuster-demo")

    _register_jinja(app)
    _register_errors(app)

    from .blueprints.dashboard import bp as dashboard_bp
    from .blueprints.agents import bp as agents_bp
    from .blueprints.containers import bp as containers_bp
    from .blueprints.resolve import bp as resolve_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(containers_bp)
    app.register_blueprint(resolve_bp)

    return app
