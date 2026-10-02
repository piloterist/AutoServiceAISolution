"""Tests for services/lead_photos_service.py - archiving a lead's
pan-motors.ru photo links onto our own Yandex.Disk. No real network calls -
httpx.Client.get/.put are monkeypatched per test, same approach as
test_yandexgpt_client.py.
"""

import uuid

import httpx

from app.services import lead_photos_service
from app.services.yandex_disk_client import API_BASE

LEAD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
PHOTO_URL = "https://pan-motors.ru/tmp_files/438730/img1.jpg"
UPLOAD_HREF = "https://uploader.disk.yandex.net/upload-fake"
UPLOAD_LINK_URL = f"{API_BASE}/resources/upload"


def _request(method: str, url: str) -> httpx.Request:
    return httpx.Request(method, url)


def _ok_photo_response(content_type: str = "image/jpeg") -> httpx.Response:
    return httpx.Response(
        200,
        content=b"fake-bytes",
        headers={"content-type": content_type},
        request=_request("GET", PHOTO_URL),
    )


def test_archive_photos_returns_empty_without_token() -> None:
    assert lead_photos_service.archive_photos([PHOTO_URL], LEAD_ID, None) == []


def test_archive_photos_returns_empty_without_urls() -> None:
    assert lead_photos_service.archive_photos([], LEAD_ID, "a-token") == []


def test_archive_photos_happy_path(monkeypatch) -> None:
    calls = {"put_targets": [], "get_targets": []}

    def fake_get(self, url, **kwargs):  # noqa: ANN001
        calls["get_targets"].append(url)
        if url == PHOTO_URL:
            return _ok_photo_response()
        if url == UPLOAD_LINK_URL:
            return httpx.Response(200, json={"href": UPLOAD_HREF}, request=_request("GET", url))
        raise AssertionError(f"unexpected GET {url}")

    def fake_put(self, url, **kwargs):  # noqa: ANN001
        calls["put_targets"].append(url)
        if url.startswith(f"{API_BASE}/resources") or url == UPLOAD_HREF:
            return httpx.Response(201, request=_request("PUT", url))
        raise AssertionError(f"unexpected PUT {url}")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setattr(httpx.Client, "put", fake_put)

    result = lead_photos_service.archive_photos([PHOTO_URL], LEAD_ID, "a-token")

    assert result == [f"/api/leads/{LEAD_ID}/photos/img1.jpg"]
    assert PHOTO_URL in calls["get_targets"]
    assert UPLOAD_LINK_URL in calls["get_targets"]
    assert any(t == UPLOAD_HREF for t in calls["put_targets"])


def test_archive_photos_accepts_octet_stream(monkeypatch) -> None:
    def fake_get(self, url, **kwargs):  # noqa: ANN001
        if url == PHOTO_URL:
            return _ok_photo_response("application/octet-stream")
        return httpx.Response(200, json={"href": UPLOAD_HREF}, request=_request("GET", url))

    def fake_put(self, url, **kwargs):  # noqa: ANN001
        return httpx.Response(201, request=_request("PUT", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setattr(httpx.Client, "put", fake_put)

    result = lead_photos_service.archive_photos([PHOTO_URL], LEAD_ID, "a-token")

    assert result == [f"/api/leads/{LEAD_ID}/photos/img1.jpg"]


def test_archive_photos_drops_non_image_response(monkeypatch) -> None:
    def fake_get(self, url, **kwargs):  # noqa: ANN001
        return httpx.Response(
            200,
            content=b"<html>gone</html>",
            headers={"content-type": "text/html"},
            request=_request("GET", url),
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = lead_photos_service.archive_photos([PHOTO_URL], LEAD_ID, "a-token")

    assert result == []


def test_archive_photos_drops_fetch_404(monkeypatch) -> None:
    def fake_get(self, url, **kwargs):  # noqa: ANN001
        return httpx.Response(404, request=_request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = lead_photos_service.archive_photos([PHOTO_URL], LEAD_ID, "a-token")

    assert result == []


def test_archive_photos_drops_photo_on_upload_failure(monkeypatch) -> None:
    def fake_get(self, url, **kwargs):  # noqa: ANN001
        if url == PHOTO_URL:
            return _ok_photo_response()
        return httpx.Response(200, json={"href": UPLOAD_HREF}, request=_request("GET", url))

    def fake_put(self, url, **kwargs):  # noqa: ANN001
        if url.startswith(f"{API_BASE}/resources"):
            return httpx.Response(201, request=_request("PUT", url))
        return httpx.Response(500, request=_request("PUT", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setattr(httpx.Client, "put", fake_put)

    result = lead_photos_service.archive_photos([PHOTO_URL], LEAD_ID, "a-token")

    assert result == []


def test_archive_photos_stops_after_folder_creation_fails(monkeypatch) -> None:
    def fake_get(self, url, **kwargs):  # noqa: ANN001
        return _ok_photo_response()

    def fake_put(self, url, **kwargs):  # noqa: ANN001
        return httpx.Response(500, request=_request("PUT", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setattr(httpx.Client, "put", fake_put)

    result = lead_photos_service.archive_photos([PHOTO_URL], LEAD_ID, "a-token")

    assert result == []
