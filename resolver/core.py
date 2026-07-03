"""CQC provider -> LinkedIn numeric company id resolution.

The single home for the resolver logic that used to live in both ``webapp/resolver.py``
and ``examples/cqc_to_linkedin.py`` (with two divergent ``.js`` phantoms). It ships the
canonical resolver phantom as package data and exposes both launch strategies:

* :func:`launch_resolution` — fire one container on a *managed*, persistent resolver
  agent (``get_or_create_resolver``) and return the ``containerId`` job handle. The
  caller polls Phantombuster; no job state is held here. Used by the webapp.
* :func:`resolve_ephemeral` — a one-shot create->run->wait->delete via
  ``Phantombuster.run_ephemeral``; returns the ``RunResult`` directly. Used by the
  CLI examples.

Both drive the same ``resolver_phantom.js`` (UK-HQ geo facet + company About-page
scrape), so the two paths can no longer diverge.
"""

from __future__ import annotations

import os
import secrets

from cqc import CQCError
from phantombuster import parse_json_field

RESOLVER_NAME = "linkedin-resolver (managed)"
PHANTOM_PATH = os.path.join(os.path.dirname(__file__), "resolver_phantom.js")
# Agent whose stored identity (li_at cookie) we borrow when env doesn't supply one.
SOURCE_AGENT = os.environ.get("PB_SOURCE_AGENT", "474380569535162")


def linkedin_session_cookie(pb) -> str:
    """The li_at cookie: from ``LINKEDIN_SESSION_COOKIE`` if set, else borrowed from
    the identity stored on the ``SOURCE_AGENT`` agent."""
    cookie = os.environ.get("LINKEDIN_SESSION_COOKIE")
    if cookie:
        return cookie
    arg = parse_json_field(pb.get_agent(SOURCE_AGENT)["argument"])
    return arg["identities"][0]["sessionCookie"]


def get_or_create_resolver(pb) -> str:
    """Find the managed resolver agent by name, creating it once if absent."""
    for agent in pb.list_agents():
        if agent.get("name") == RESOLVER_NAME:
            return agent["id"]
    with open(PHANTOM_PATH) as fh:
        code = fh.read()
    script_name = f"linkedin-resolver-{secrets.token_hex(3)}.js"
    pb.create_script(script_name, code, branch="master")
    return pb.create_agent(
        RESOLVER_NAME,
        script=script_name,
        branch="master",
        environment="staging",
        max_parallelism=5,
    )


def gather_cqc(cqc, provider_id: str) -> dict:
    """Pull as much CQC data as possible for a provider (sub-resources best-effort)."""
    bundle = {"provider": cqc.get_provider(provider_id)}  # 404 here => bad id, let it raise

    def optional(key, fn):
        try:
            bundle[key] = fn()
        except CQCError:
            bundle[key] = None

    optional("locations", lambda: cqc.get_provider_locations(provider_id))
    optional("inspectionAreas", lambda: cqc.get_provider_inspection_areas(provider_id))
    optional("assessmentServiceGroups", lambda: cqc.get_provider_assessment_service_groups(provider_id))
    return bundle


def search_term(provider: dict) -> str:
    """LinkedIn lists trading brands, not legal names; prefer brandName."""
    brand = (provider.get("brandName") or "").replace("BRAND ", "").strip()
    return brand or provider.get("name") or ""


def launch_resolution(pb, keywords: str) -> str:
    """Launch a resolution container on the managed agent; returns the containerId."""
    agent_id = get_or_create_resolver(pb)
    # Pass the argument directly (not bonusArgument): the agent has no saved base
    # argument to merge into, and each request needs its own cookie + keywords.
    return pb.launch(
        agent_id,
        argument={"sessionCookie": linkedin_session_cookie(pb), "keywords": keywords},
    )


def resolve_ephemeral(pb, keywords: str, *, cookie: str | None = None, timeout: int = 280, poll: int = 6):
    """Resolve in one shot via an ephemeral phantom (create->run->wait->delete).

    Returns the phantombuster ``RunResult``; ``RunResult.result[0]`` is the match
    (``companyId``, ``vanity``, ``name``, plus About-page fields), if any.
    """
    with open(PHANTOM_PATH) as fh:
        code = fh.read()
    return pb.run_ephemeral(
        name="cqc-to-linkedin",
        code=code,
        argument={"sessionCookie": cookie or linkedin_session_cookie(pb), "keywords": keywords},
        timeout=timeout,
        poll=poll,
    )
