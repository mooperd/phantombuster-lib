from flask import Blueprint, flash, redirect, render_template, request, url_for

from phantombuster import PhantombusterError, parse_json_field
from webapp.clients import pb

bp = Blueprint("agents", __name__, url_prefix="/agents")


@bp.route("/")
def index():
    return render_template("agents.html", agents=pb.list_agents(), active="agents")


@bp.route("/<agent_id>")
def detail(agent_id):
    agent = pb.get_agent(agent_id)
    argument = parse_json_field(agent.get("argument"))
    if argument is not None:  # parse so redact() can mask secrets inside it
        agent["argument"] = argument
    return render_template(
        "agent_detail.html", agent=agent, argument=argument,
        containers=pb.list_containers(agent_id), active="agents",
    )


@bp.route("/<agent_id>/launch", methods=["POST"])
def launch(agent_id):
    bonus = None
    cap = request.form.get("cap")
    if cap:
        try:
            n = int(cap)
            bonus = {"numberOfResultsPerLaunch": n, "numberOfResultsPerSearch": n, "numberOfLinesPerLaunch": n}
        except ValueError:
            pass
    try:
        container_id = pb.launch(agent_id, bonus_argument=bonus)
        flash(f"Launched — container {container_id}", "success")
        return redirect(url_for("containers.detail", container_id=container_id))
    except PhantombusterError as err:
        flash(f"Launch failed: {err}", "danger")
        return redirect(url_for("agents.detail", agent_id=agent_id))


@bp.route("/<agent_id>/abort", methods=["POST"])
def abort(agent_id):
    try:
        pb.abort_agent(agent_id)
        flash("Abort requested.", "warning")
    except PhantombusterError as err:
        flash(f"Abort failed: {err}", "danger")
    return redirect(url_for("agents.detail", agent_id=agent_id))
