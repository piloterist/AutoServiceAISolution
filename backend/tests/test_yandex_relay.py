import asyncio

import httpx
from sqlalchemy import select

from app.models.import_batch import ImportBatch
from app.models.work_order import WorkOrder
from app.services import yandex_relay


def test_select_pending_files_excludes_folders() -> None:
    items = [
        {"name": "batch1.json", "type": "file", "path": "disk:/1c-export/batch1.json"},
        {"name": "processed", "type": "dir", "path": "disk:/1c-export/processed"},
        {"name": "batch2.json", "type": "file", "path": "disk:/1c-export/batch2.json"},
    ]

    pending = yandex_relay.select_pending_files(items)

    assert [item["name"] for item in pending] == ["batch1.json", "batch2.json"]


def test_processed_path_moves_under_processed_subfolder() -> None:
    result = yandex_relay._processed_path("/1c-export", "disk:/1c-export/batch1.json")

    assert result == "/1c-export/processed/batch1.json"


SAMPLE_PAYLOAD = b"""{
    "source": "alpha-auto",
    "branch": "kahovka",
    "entity": "work_orders",
    "exported_at": "2026-09-13T10:00:00",
    "batch_id": "yandex-relay-test-1",
    "records": [
        {
            "number": "YAREL-0001",
            "date": "2026-09-12T18:38:09",
            "customer": "Relay Test Customer",
            "car": "TEST CAR",
            "amount": 555
        }
    ]
}"""


def _make_mock_transport(calls: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.host}{request.url.path}")

        if request.url.host == "cloud-api.yandex.net":
            if request.method == "PUT" and request.url.path == "/v1/disk/resources":
                return httpx.Response(409)  # "already exists" - the steady-state case
            if request.method == "GET" and request.url.path == "/v1/disk/resources":
                return httpx.Response(
                    200,
                    json={
                        "_embedded": {
                            "items": [
                                {
                                    "name": "batch1.json",
                                    "type": "file",
                                    "path": "disk:/1c-export/batch1.json",
                                }
                            ]
                        }
                    },
                )
            if request.method == "GET" and request.url.path == "/v1/disk/resources/download":
                return httpx.Response(
                    200, json={"href": "https://downloader.example.test/batch1.json"}
                )
            if request.method == "POST" and request.url.path == "/v1/disk/resources/move":
                return httpx.Response(201)

        if request.url.host == "downloader.example.test":
            # Yandex's real download link redirects to a separate storage
            # node - simulate that hop to guard against regressing the
            # follow_redirects fix (httpx does not follow redirects by
            # default and treats an unfollowed one as an error).
            return httpx.Response(
                302, headers={"Location": "https://storage.example.test/real-batch1.json"}
            )

        if request.url.host == "storage.example.test":
            return httpx.Response(200, content=SAMPLE_PAYLOAD)

        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_poll_once_imports_file_and_marks_it_processed(monkeypatch, db_session) -> None:
    calls: list[str] = []
    transport = _make_mock_transport(calls)

    class _MockedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _MockedAsyncClient)
    monkeypatch.setattr(yandex_relay, "SessionLocal", lambda: db_session)

    settings = yandex_relay.get_settings()
    monkeypatch.setattr(settings, "yandex_disk_oauth_token", "test-oauth-token")
    monkeypatch.setattr(settings, "enable_yandex_relay", True)

    asyncio.run(yandex_relay.poll_once())

    work_order = db_session.execute(
        select(WorkOrder).where(WorkOrder.external_number == "YAREL-0001")
    ).scalar_one()
    assert work_order.customer_name == "Relay Test Customer"

    batch = db_session.execute(
        select(ImportBatch).where(ImportBatch.batch_id == "yandex-relay-test-1")
    ).scalar_one()
    assert batch.status == "success"

    assert "POST cloud-api.yandex.net/v1/disk/resources/move" in calls


def test_poll_once_without_token_does_nothing(monkeypatch, db_session) -> None:
    settings = yandex_relay.get_settings()
    monkeypatch.setattr(settings, "yandex_disk_oauth_token", None)

    # Must not raise even though no HTTP transport is mocked - it should
    # return before making any request.
    asyncio.run(yandex_relay.poll_once())
