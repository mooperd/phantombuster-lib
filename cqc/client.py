"""A typed Python client for the CQC Syndication API (public v1).

Covers every endpoint in ``cqc/syndication.yaml``: single provider/location lookups,
their assessment-service-groups and inspection-areas, the paginated ``providers`` /
``locations`` / ``changes`` list endpoints (with auto-paging iterators), the global
inspection-areas taxonomy, and inspection report downloads (PDF / text).

Auth is a subscription key sent as the ``Ocp-Apim-Subscription-Key`` header.

    from cqc import CQC
    cqc = CQC("your-subscription-key")
    provider = cqc.get_provider("1-116865921")
    for p in cqc.iter_providers(region="London", overallRating="Outstanding"):
        ...
"""

from __future__ import annotations

from typing import Any, Iterator

import requests

DEFAULT_BASE_URL = "https://api.service.cqc.org.uk/public/v1"


class CQCError(Exception):
    """Raised when the CQC API returns a non-2xx response."""

    def __init__(self, message: str, *, status: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status = status
        self.url = url


class CQC:
    """Client for the CQC Syndication API.

    Args:
        subscription_key: Your CQC API subscription (primary or secondary) key.
        base_url: Override the API base URL.
        partner_code: Optional partner code sent as the ``User-Agent`` (CQC asks
            integrators to identify themselves).
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        subscription_key: str,
        base_url: str = DEFAULT_BASE_URL,
        partner_code: str | None = None,
        timeout: float = 30.0,
    ):
        if not subscription_key:
            raise ValueError("subscription_key is required")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Ocp-Apim-Subscription-Key": subscription_key,
                "accept": "application/json",
            }
        )
        if partner_code:
            self._session.headers["User-Agent"] = partner_code

    # ------------------------------------------------------------------ #
    # Low-level HTTP
    # ------------------------------------------------------------------ #
    def _get(self, path: str, params: dict | None = None, accept: str | None = None) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {"accept": accept} if accept else None
        resp = self._session.get(
            url, params=_clean_params(params), headers=headers, timeout=self.timeout
        )
        if not resp.ok:
            message = f"CQC API {resp.status_code} for {path}"
            try:
                body = resp.json()
                message = f"{message}: {body.get('message', body)}"
            except ValueError:
                pass
            raise CQCError(message, status=resp.status_code, url=resp.url)
        return resp

    def _get_json(self, path: str, params: dict | None = None) -> Any:
        return self._get(path, params).json()

    # ------------------------------------------------------------------ #
    # Providers
    # ------------------------------------------------------------------ #
    def get_provider(self, provider_id: str) -> dict:
        """GET /providers/{id} — full provider (parent organisation) detail."""
        return self._get_json(f"providers/{provider_id}")

    def get_provider_locations(self, provider_id: str) -> dict:
        """GET /providers/{id}/locations — the sites operated by this provider."""
        return self._get_json(f"providers/{provider_id}/locations")

    def get_provider_assessment_service_groups(self, provider_id: str) -> dict:
        """GET /providers/{id}/assessment-service-groups."""
        return self._get_json(f"providers/{provider_id}/assessment-service-groups")

    def get_provider_inspection_areas(self, provider_id: str) -> dict:
        """GET /providers/{id}/inspection-areas — inspection areas at provider level."""
        return self._get_json(f"providers/{provider_id}/inspection-areas")

    def providers(self, page: int = 1, per_page: int = 50, **filters) -> dict:
        """GET /providers — one page of the provider list.

        Filters (each may be a string or list of strings, OR-ed within a filter and
        AND-ed across filters): constituency, localAuthority, inspectionDirectorate,
        overallRating, region, regulatedActivity, reportType,
        primaryInspectionCategoryCode/Name, nonPrimaryInspectionCategoryCode/Name.
        """
        params = {"page": page, "perPage": per_page, **filters}
        return self._get_json("providers", params)

    def iter_providers(self, per_page: int = 50, **filters) -> Iterator[dict]:
        """Iterate over every provider stub across all pages of /providers."""
        yield from self._paginate("providers", "providers", per_page, filters)

    # ------------------------------------------------------------------ #
    # Locations
    # ------------------------------------------------------------------ #
    def get_location(self, location_id: str) -> dict:
        """GET /locations/{id} — full location (site) detail."""
        return self._get_json(f"locations/{location_id}")

    def get_location_assessment_service_groups(self, location_id: str) -> dict:
        """GET /locations/{id}/assessment-service-groups."""
        return self._get_json(f"locations/{location_id}/assessment-service-groups")

    def get_location_inspection_areas(self, location_id: str) -> dict:
        """GET /locations/{id}/inspection-areas."""
        return self._get_json(f"locations/{location_id}/inspection-areas")

    def get_location_provider_inspection_areas(self, location_id: str) -> dict:
        """GET /locations/{id}/provider-inspection-areas."""
        return self._get_json(f"locations/{location_id}/provider-inspection-areas")

    def locations(self, page: int = 1, per_page: int = 50, **filters) -> dict:
        """GET /locations — one page of the location list.

        Filters include: careHome (Y/N), region, overallRating, localAuthority,
        onspdCcgCode/Name, odsCcgCode/Name, and the same category/activity filters
        as :meth:`providers`.
        """
        params = {"page": page, "perPage": per_page, **filters}
        return self._get_json("locations", params)

    def iter_locations(self, per_page: int = 50, **filters) -> Iterator[dict]:
        """Iterate over every location stub across all pages of /locations."""
        yield from self._paginate("locations", "locations", per_page, filters)

    # ------------------------------------------------------------------ #
    # Changes
    # ------------------------------------------------------------------ #
    def changes(
        self,
        organisation_type: str,
        start_timestamp: str,
        end_timestamp: str,
        page: int = 1,
        per_page: int = 50,
    ) -> dict:
        """GET /changes/{organisationType} — ids changed in an ISO-8601 window.

        ``organisation_type`` is "provider" or "location". The window is inclusive of
        start and exclusive of end; for successive polls set the next ``start`` to the
        previous ``end``.
        """
        params = {
            "startTimestamp": start_timestamp,
            "endTimestamp": end_timestamp,
            "page": page,
            "perPage": per_page,
        }
        return self._get_json(f"changes/{organisation_type}", params)

    def iter_changes(
        self,
        organisation_type: str,
        start_timestamp: str,
        end_timestamp: str,
        per_page: int = 50,
    ) -> Iterator[str]:
        """Iterate over every changed organisation id across all pages of /changes."""
        params = {"startTimestamp": start_timestamp, "endTimestamp": end_timestamp}
        yield from self._paginate(
            f"changes/{organisation_type}", "changes", per_page, params
        )

    # ------------------------------------------------------------------ #
    # Taxonomy & reports
    # ------------------------------------------------------------------ #
    def inspection_areas(self) -> dict:
        """GET /inspection-areas — the global CQC inspection-area taxonomy."""
        return self._get_json("inspection-areas")

    def get_report(
        self,
        inspection_report_link_id: str,
        related_document_type: str | None = None,
        as_text: bool = False,
    ) -> bytes | str:
        """GET /reports/{id}[/{related_document_type}] — an inspection report.

        Returns PDF bytes by default, or the extracted plain text when ``as_text`` is
        True. ``related_document_type`` (e.g. "Use of Resources") comes from a report's
        ``relatedDocuments``; omit it for the main report.
        """
        path = f"reports/{inspection_report_link_id}"
        if related_document_type:
            path = f"{path}/{related_document_type}"
        accept = "text/plain" if as_text else "application/pdf"
        resp = self._get(path, accept=accept)
        return resp.text if as_text else resp.content

    # ------------------------------------------------------------------ #
    # Pagination helper
    # ------------------------------------------------------------------ #
    def _paginate(
        self, path: str, items_key: str, per_page: int, params: dict
    ) -> Iterator[Any]:
        page = 1
        while True:
            body = self._get_json(path, {**params, "page": page, "perPage": per_page})
            items = body.get(items_key) or []
            for item in items:
                yield item
            total_pages = body.get("totalPages")
            if total_pages is not None:
                if page >= total_pages:
                    break
            elif not body.get("nextPageUri"):
                break
            page += 1


def _clean_params(params: dict | None) -> dict | None:
    """Drop None values; requests already repeats list-valued params correctly."""
    if not params:
        return params
    return {k: v for k, v in params.items() if v is not None}
