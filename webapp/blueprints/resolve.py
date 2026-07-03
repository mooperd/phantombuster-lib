"""CQC id -> LinkedIn resolution API (stateless; the Phantombuster containerId is the job handle)."""

from flask import Blueprint, jsonify, render_template, request

import resolver

from phantombuster import PhantombusterError
from webapp.clients import cqc, pb

bp = Blueprint("resolve", __name__)


@bp.route("/resolve")
def page():
    return render_template("resolve.html", active="resolve")


@bp.route("/api/resolve", methods=["POST"])
def create():
    """Fetch CQC data (sync), launch the LinkedIn resolver (async), return the job handle."""
    payload = request.get_json(silent=True) or request.form
    cqc_id = (payload.get("cqc_id") or "").strip()
    if not cqc_id:
        return jsonify({"error": "cqc_id is required"}), 400

    bundle = resolver.gather_cqc(cqc, cqc_id)  # raises CQCError -> 502 on a bad id
    provider = bundle["provider"]

    # Deregistered providers no longer trade — skip the (costly) LinkedIn lookup.
    if provider.get("registrationStatus") == "Deregistered":
        return jsonify({
            "job_id": None,
            "skipped": True,
            "reason": f"provider deregistered ({provider.get('deregistrationDate') or 'date unknown'})",
            "cqc": bundle,
        }), 200

    term = resolver.search_term(provider)
    container_id = resolver.launch_resolution(pb, term)

    return jsonify({
        "job_id": container_id,
        "search_term": term,
        "cqc": bundle,
        "job_url": f"/api/jobs/{container_id}",
    }), 202


@bp.route("/api/jobs/<container_id>")
def job(container_id):
    """Report job state straight from Phantombuster; expose the full container + result."""
    try:
        container = pb.get_container(container_id)
        output = pb.get_output(container_id)
        result = pb.get_result(container_id)
    except PhantombusterError as err:
        return jsonify({"error": str(err)}), 502

    status = container.get("status")
    exit_code = container.get("exitCode")
    if status == "finished":
        state = "finished" if exit_code == 0 else "error"
    elif status in (None, "running", "starting"):
        state = "running"
    else:
        state = status

    return jsonify({
        "job_id": container_id,
        "state": state,
        "container": container,               # every container attribute
        "progress": output.get("progress"),
        "console": output.get("output"),
        "linkedin": result[0] if result else None,
        "results": result,                    # full result rows
    })
