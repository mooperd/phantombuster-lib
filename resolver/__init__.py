"""CQC provider -> LinkedIn company-id resolver.

Consolidates what used to be duplicated across ``webapp/resolver.py`` and
``examples/cqc_to_linkedin.py``. Ships the canonical resolver phantom as package
data (:data:`PHANTOM_PATH`) and exposes both the managed and ephemeral launch paths.
"""

from .core import (
    PHANTOM_PATH,
    RESOLVER_NAME,
    SOURCE_AGENT,
    gather_cqc,
    get_or_create_resolver,
    launch_resolution,
    linkedin_session_cookie,
    resolve_ephemeral,
    search_term,
)

__all__ = [
    "PHANTOM_PATH",
    "RESOLVER_NAME",
    "SOURCE_AGENT",
    "gather_cqc",
    "get_or_create_resolver",
    "launch_resolution",
    "linkedin_session_cookie",
    "resolve_ephemeral",
    "search_term",
]

__version__ = "0.1.0"
