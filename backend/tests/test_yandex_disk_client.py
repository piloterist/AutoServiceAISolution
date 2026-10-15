"""Tests for services/yandex_disk_client.py's ensure_path - specifically the
2026-10-14 hardening after a real incident (disk:/Leads never existed on
the account, so every lead photo archive attempt silently failed for about
two weeks - see lead_photos_service.py's own module docstring). No real
network calls: httpx.Client.put is monkeypatched, same approach as
test_lead_photos_service.py.
"""

import httpx

from app.services import yandex_disk_client


def _request(url: str) -> httpx.Request:
    return httpx.Request("PUT", url)


def test_ensure_path_creates_base_folder_first(monkeypatch) -> None:
    """Before this fix, ensure_path assumed `base` already existed and only
    ever created the segments after it - exactly the assumption that broke
    silently when disk:/Leads itself didn't exist."""
    put_paths: list[str] = []

    def fake_put(self, url, **kwargs):  # noqa: ANN001
        params = kwargs.get("params") or {}
        put_paths.append(params.get("path"))
        return httpx.Response(201, request=_request(url))

    monkeypatch.setattr(httpx.Client, "put", fake_put)

    with yandex_disk_client.new_client() as client:
        created = yandex_disk_client.ensure_path(client, "token", "disk:/Leads", "lead-123")

    assert put_paths == ["disk:/Leads", "disk:/Leads/lead-123"]
    assert created is True


def test_ensure_path_succeeds_even_if_base_already_existed(monkeypatch) -> None:
    """ensure_folder's own 409 handling makes the extra base-creation call
    a safe no-op for every caller whose base already exists (e.g.
    call_recording_service's disk:/1c-export, which does)."""

    def fake_put(self, url, **kwargs):  # noqa: ANN001
        params = kwargs.get("params") or {}
        # The base already exists (409, generic conflict - not the
        # "parent doesn't exist" case), the new leaf doesn't (201).
        if params.get("path") == "disk:/1c-export":
            return httpx.Response(409, json={"error": "DiskPathPointsToExistentDirectoryError"})
        return httpx.Response(201, request=_request(url))

    monkeypatch.setattr(httpx.Client, "put", fake_put)

    with yandex_disk_client.new_client() as client:
        created = yandex_disk_client.ensure_path(client, "token", "disk:/1c-export", "20261014")

    assert created is True


def test_ensure_folder_still_raises_when_a_deeper_parent_is_missing(monkeypatch) -> None:
    """Sanity check that the underlying error (a real structural problem
    one level further down) still surfaces normally - this hardening only
    covers the TOP-level `base`, not arbitrarily missing ancestors."""

    def fake_put(self, url, **kwargs):  # noqa: ANN001
        return httpx.Response(
            409, json={"error": "DiskPathDoesntExistsError"}, request=_request(url)
        )

    monkeypatch.setattr(httpx.Client, "put", fake_put)

    with yandex_disk_client.new_client() as client:
        try:
            yandex_disk_client.ensure_folder(client, "token", "disk:/Leads/missing/deep")
        except yandex_disk_client.YaDiskError as exc:
            assert "parent folder doesn't exist" in str(exc)
        else:
            raise AssertionError("expected YaDiskError")
