from flask import Blueprint, render_template

from webapp.clients import pb

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    return render_template(
        "dashboard.html", resources=pb.get_resources(), agents=pb.list_agents(), active="dashboard"
    )
