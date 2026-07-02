from flask import Blueprint, jsonify, render_template

from phantombuster import PhantombusterError
from webapp.clients import pb

bp = Blueprint("containers", __name__)


@bp.route("/containers/<container_id>")
def detail(container_id):
    container = pb.get_container(container_id)
    output = pb.get_output(container_id)
    result = pb.get_result(container_id)
    columns = []
    for row in result:
        for key in row:
            if key not in columns:
                columns.append(key)
    return render_template(
        "container.html", container=container, output=output,
        result=result, columns=columns, active="agents",
    )


@bp.route("/api/containers/<container_id>/output")
def output_json(container_id):
    """JSON proxy so the browser can poll live console output (no API key exposed)."""
    try:
        container = pb.get_container(container_id)
        output = pb.get_output(container_id)
        return jsonify({
            "status": container.get("status"), "exitCode": container.get("exitCode"),
            "output": output.get("output"), "progress": output.get("progress"),
        })
    except PhantombusterError as err:
        return jsonify({"error": str(err)}), 502
