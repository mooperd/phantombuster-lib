"""A thin, typed Python client for the Phantombuster API (v2).

Everything here maps directly onto the endpoints documented in ``API-guidence.md``.
The client keeps full fidelity of the API responses (returns raw dicts/lists) so a
frontend can surface *every* attribute, while adding a few convenience helpers for the
parts of the API that hand you JSON encoded as strings (``argument`` / ``resultObject``)
and for the launch -> poll -> results lifecycle.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from typing import Any

import requests

DEFAULT_BASE_URL = "https://api.phantombuster.com/api/v2"

# Keys whose values are secrets and should be masked before display.
SECRET_KEYS = {"sessionCookie", "sessionCookies", "apiKey", "password", "token"}


class PhantombusterError(Exception):
    """Raised when the API returns an ``{"status": "error", ...}`` body."""

    def __init__(self, message: str, *, endpoint: str | None = None, payload: Any = None):
        super().__init__(message)
        self.endpoint = endpoint
        self.payload = payload


class RunResult:
    """Outcome of :meth:`Phantombuster.run_and_wait`."""

    def __init__(self, container: dict, output: str | None, result: list[dict] | None):
        self.container = container
        self.output = output
        self.result = result

    @property
    def container_id(self) -> str:
        return str(self.container.get("id"))

    @property
    def exit_code(self) -> int | None:
        code = self.container.get("exitCode")
        return int(code) if code is not None else None

    @property
    def succeeded(self) -> bool:
        return self.container.get("status") == "finished" and self.exit_code == 0

    @property
    def has_results(self) -> bool:
        return bool(self.result)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"RunResult(container_id={self.container_id!r}, "
            f"exit_code={self.exit_code}, rows={len(self.result or [])})"
        )


class Phantombuster:
    """Client for the Phantombuster REST API (v2).

    Args:
        api_key: Your Phantombuster API key. Kept server-side; never expose it.
        base_url: Override the API base URL (defaults to the public v2 endpoint).
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "X-Phantombuster-Key-1": api_key,
                "accept": "application/json",
            }
        )

    # ------------------------------------------------------------------ #
    # Low-level HTTP
    # ------------------------------------------------------------------ #
    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        resp = self._session.request(method, url, timeout=self.timeout, **kwargs)
        # Some write endpoints (e.g. scripts/delete) return an empty or non-JSON
        # 200 body on success. The API returns HTTP 200 even for logical errors,
        # so we still parse when we can.
        if not resp.content:
            resp.raise_for_status()
            return {}
        try:
            data = resp.json()
        except ValueError:
            if resp.ok:
                return {"raw": resp.text}
            raise PhantombusterError(
                f"Non-JSON error response from {path} (HTTP {resp.status_code})",
                endpoint=path,
                payload=resp.text,
            )
        if isinstance(data, dict) and data.get("status") == "error":
            raise PhantombusterError(
                data.get("error", "Unknown API error"), endpoint=path, payload=data
            )
        resp.raise_for_status()
        return data

    def _get(self, path: str, **params) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        return self._request("GET", path, params=params)

    def _post(self, path: str, **body) -> Any:
        body = {k: v for k, v in body.items() if v is not None}
        return self._request("POST", path, json=body)

    # ------------------------------------------------------------------ #
    # Agents
    # ------------------------------------------------------------------ #
    def list_agents(self) -> list[dict]:
        """GET /agents/fetch-all — every agent (each includes its manifest)."""
        return self._get("agents/fetch-all")

    def get_agent(self, agent_id: str) -> dict:
        """GET /agents/fetch — full detail of one agent (no manifest)."""
        return self._get("agents/fetch", id=agent_id)

    def launch(
        self,
        agent_id: str,
        argument: dict | str | None = None,
        bonus_argument: dict | str | None = None,
        save_argument: bool = False,
        manual_launch: bool = False,
        max_instance_count: int | None = None,
        user_custom_metadata: dict | None = None,
    ) -> str:
        """POST /agents/launch — start a run. Returns the new container id.

        ``argument`` replaces the saved argument for this run; ``bonus_argument`` is
        single-use and merged into the base argument (handy for capping result counts).
        """
        data = self._post(
            "agents/launch",
            id=agent_id,
            argument=argument,
            bonusArgument=bonus_argument,
            saveArgument=save_argument or None,
            manualLaunch=manual_launch or None,
            maxInstanceCount=max_instance_count,
            userCustomMetadata=user_custom_metadata,
        )
        return str(data.get("containerId"))

    def abort_agent(self, agent_id: str) -> dict:
        """POST /agents/abort — stop the agent's running container(s)."""
        return self._post("agents/abort", id=agent_id)

    def create_agent(
        self,
        name: str,
        script: str,
        branch: str = "master",
        launch_type: str = "manually",
        environment: str = "release",
        argument: dict | str | None = None,
        max_parallelism: int | None = None,
    ) -> str:
        """POST /agents/save (no id) — create a new agent. Returns the new agent id.

        ``script`` must be the *name* of a script that exists in your org
        (see :meth:`create_script`); store scripts cannot be instantiated this way.
        ``max_parallelism`` lets several containers of this agent run at once.
        """
        if isinstance(argument, dict):
            argument = json.dumps(argument)
        data = self._post(
            "agents/save",
            name=name,
            script=script,
            branch=branch,
            launchType=launch_type,
            environment=environment,
            argument=argument,
            maxParallelism=max_parallelism,
        )
        return str(data.get("id"))

    def update_agent(self, agent_id: str, **fields) -> dict:
        """POST /agents/save (with id) — update an existing agent."""
        return self._post("agents/save", id=agent_id, **fields)

    def delete_agent(self, agent_id: str) -> dict:
        """POST /agents/delete — delete an agent."""
        return self._post("agents/delete", id=agent_id)

    # ------------------------------------------------------------------ #
    # Scripts
    # ------------------------------------------------------------------ #
    def list_scripts(self) -> list[dict]:
        """GET /scripts/fetch-all — scripts owned by your org."""
        return self._get("scripts/fetch-all")

    def create_script(
        self,
        name: str,
        code: str,
        branch: str = "master",
        markdown: str | None = None,
    ) -> str:
        """POST /scripts/save (no id) — create an org-owned script. Returns its id."""
        data = self._post(
            "scripts/save", name=name, code=code, branch=branch, markdown=markdown
        )
        return str(data.get("id"))

    def delete_script(self, script_id: str) -> dict:
        """POST /scripts/delete — delete an org-owned script."""
        return self._post("scripts/delete", id=script_id)

    # ------------------------------------------------------------------ #
    # Containers
    # ------------------------------------------------------------------ #
    def list_containers(self, agent_id: str) -> list[dict]:
        """GET /containers/fetch-all — run history for an agent."""
        data = self._get("containers/fetch-all", agentId=agent_id)
        return data.get("containers", []) if isinstance(data, dict) else data

    def get_container(self, container_id: str) -> dict:
        """GET /containers/fetch — single container detail."""
        return self._get("containers/fetch", id=container_id)

    def get_output(
        self,
        container_id: str,
        mode: str | None = None,
        from_output_pos: int | None = None,
    ) -> dict:
        """GET /containers/fetch-output — console log + live status/progress.

        Returns the raw dict: ``{status, containerStatus, progress, output, ...}``.
        """
        return self._get(
            "containers/fetch-output",
            id=container_id,
            mode=mode,
            fromOutputPos=from_output_pos,
        )

    def get_result_raw(self, container_id: str) -> dict:
        """GET /containers/fetch-result-object — raw response (resultObject is a string)."""
        return self._get("containers/fetch-result-object", id=container_id)

    def get_result(self, container_id: str) -> list[dict]:
        """Parsed structured results (empty list when the run produced no rows)."""
        raw = self.get_result_raw(container_id)
        return parse_json_field(raw.get("resultObject")) or []

    # ------------------------------------------------------------------ #
    # Org / account
    # ------------------------------------------------------------------ #
    def get_resources(self) -> dict:
        """GET /orgs/fetch-resources — plan details and quota usage."""
        return self._get("orgs/fetch-resources")

    # ------------------------------------------------------------------ #
    # High-level convenience
    # ------------------------------------------------------------------ #
    def run_and_wait(
        self,
        agent_id: str,
        argument: dict | str | None = None,
        bonus_argument: dict | str | None = None,
        timeout: float = 300.0,
        poll: float = 3.0,
    ) -> RunResult:
        """Launch an agent and block until the container finishes, then fetch results."""
        container_id = self.launch(
            agent_id, argument=argument, bonus_argument=bonus_argument
        )
        deadline = time.monotonic() + timeout
        container: dict = {}
        while time.monotonic() < deadline:
            container = self.get_container(container_id)
            if container.get("status") in ("finished", "error"):
                break
            time.sleep(poll)
        else:
            raise PhantombusterError(
                f"Container {container_id} did not finish within {timeout}s",
                endpoint="containers/fetch",
            )
        output = None
        result = None
        try:
            output = self.get_output(container_id).get("output")
            result = self.get_result(container_id)
        except PhantombusterError:
            pass
        return RunResult(container, output, result)

    def run_ephemeral(
        self,
        name: str,
        code: str,
        argument: dict | str | None = None,
        branch: str = "master",
        environment: str = "staging",
        timeout: float = 300.0,
        poll: float = 3.0,
        keep: bool = False,
    ) -> RunResult:
        """Create a throwaway script + agent, run it, then delete both.

        This is the "ephemeral phantom" pattern: nothing persists in your account
        after the call (unless ``keep=True``). A freshly created phantom also has no
        accumulated de-duplication state, so it always scrapes from a clean slate.

        The script must be Node phantom source starting with a config block. For a
        plain Node script (no browser)::

            // Phantombuster configuration {
            "phantombuster command: nodejs"
            "phantombuster package: 5"
            // }

        For a headless browser (Puppeteer bundled, Node 16), use instead::

            // Phantombuster configuration {
            "phantom image: web-node:v1"
            "phantombuster flags: save-folder"
            // }

        Teardown runs even if the launch/poll fails.
        """
        slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "ephemeral"
        script_name = f"{slug}-{secrets.token_hex(4)}.js"
        script_id = self.create_script(script_name, code, branch=branch)
        agent_id = None
        try:
            agent_id = self.create_agent(
                name,
                script=script_name,
                branch=branch,
                environment=environment,
                argument=argument,
            )
            return self.run_and_wait(agent_id, timeout=timeout, poll=poll)
        finally:
            if not keep:
                if agent_id:
                    try:
                        self.delete_agent(agent_id)
                    except PhantombusterError:
                        pass
                try:
                    self.delete_script(script_id)
                except PhantombusterError:
                    pass


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #
def parse_json_field(value: Any) -> Any:
    """Parse a field the API returns as a JSON *string* (argument, resultObject)."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def redact(value: Any, secret_keys: set[str] = SECRET_KEYS) -> Any:
    """Recursively mask secret values (session cookies, tokens) for safe display."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in secret_keys and isinstance(v, str) and v:
                out[k] = _mask(v)
            else:
                out[k] = redact(v, secret_keys)
        return out
    if isinstance(value, list):
        return [redact(v, secret_keys) for v in value]
    return value


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "••••"
    return f"{value[:4]}…{value[-4:]} (redacted, {len(value)} chars)"
