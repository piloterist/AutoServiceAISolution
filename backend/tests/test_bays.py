import base64
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.bay import SNAPSHOT_FAILED, BayEvent, BayLatestFrame, BaySnapshotRequest
from app.models.department import Department
from app.models.work_order import WorkOrder
from app.models.workshop import Workshop
from app.services import bay_service

JPEG = base64.b64encode(b"\xff\xd8fake-jpeg\xff\xd9").decode()


@pytest.fixture()
def workshop(db_session: Session) -> Workshop:
    department = Department(name="Каховка")
    db_session.add(department)
    db_session.flush()
    ws = Workshop(
        department_id=department.id,
        workshop_type="Слесарный",
        posts_count=3,
        start_time="08:00:00",
        end_time="20:00:00",
        working_days=[0, 1, 2, 3, 4],
    )
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    return ws


@pytest.fixture()
def uploads(monkeypatch) -> dict[str, bytes]:
    """Replaces Yandex.Disk with a dict: path -> bytes."""
    stored: dict[str, bytes] = {}

    def fake_upload(db, bay_id, path, data, overwrite):
        stored[path] = data
        return True

    monkeypatch.setattr(bay_service, "_upload", fake_upload)
    monkeypatch.setattr(bay_service, "download_snapshot", lambda db, path: stored.get(path))
    return stored


def _bays(client: TestClient, headers: dict, workshop_id: uuid.UUID) -> list[dict]:
    response = client.get(f"/api/v1/bays?workshop_id={workshop_id}", headers=headers)
    assert response.status_code == 200
    return response.json()["bays"]


def _event(client, headers, bay_id, event_type, plate=None, **extra):
    body = {"event_type": event_type, "plate": plate, **extra}
    return client.post(f"/api/v1/bays/{bay_id}/events", json=body, headers=headers)


def test_bays_require_the_api_token(client: TestClient) -> None:
    assert client.get("/api/v1/bays").status_code == 401


def test_default_bays_follow_the_posts_count(
    client: TestClient, auth_headers: dict, workshop: Workshop
) -> None:
    response = client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=auth_headers)
    assert response.status_code == 200
    assert [b["name"] for b in response.json()["bays"]] == ["Бокс 1", "Бокс 2", "Бокс 3"]
    # repeated call does not duplicate
    again = client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=auth_headers)
    assert len(again.json()["bays"]) == 3


def test_a_new_bay_is_free(client: TestClient, auth_headers: dict, workshop: Workshop) -> None:
    client.post(
        "/api/v1/bays",
        json={"workshop_id": str(workshop.id), "name": "Бокс А"},
        headers=auth_headers,
    )
    [bay] = _bays(client, auth_headers, workshop.id)
    assert (bay["state"], bay["plate"], bay["last_entry"], bay["last_exit"]) == (
        "free",
        None,
        None,
        None,
    )


def test_entry_makes_the_bay_occupied_and_exit_frees_it(
    client: TestClient, auth_headers: dict, workshop: Workshop, uploads: dict
) -> None:
    client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=auth_headers)
    bay_id = _bays(client, auth_headers, workshop.id)[0]["id"]

    entered = _event(
        client, auth_headers, bay_id, "entry_confirmed", "a123bc77", snapshot_base64=JPEG
    )
    assert entered.status_code == 201
    assert entered.json()["plate"] == "А123ВС77"  # latin lookalikes -> cyrillic
    assert entered.json()["has_snapshot"] is True

    [bay] = [b for b in _bays(client, auth_headers, workshop.id) if b["id"] == bay_id]
    assert (bay["state"], bay["plate"]) == ("occupied", "А123ВС77")
    assert bay["last_entry"]["id"] == entered.json()["id"]

    left = _event(client, auth_headers, bay_id, "exit_confirmed", snapshot_base64=JPEG)
    [bay] = [b for b in _bays(client, auth_headers, workshop.id) if b["id"] == bay_id]
    assert (bay["state"], bay["plate"]) == ("free", None)
    assert bay["last_exit"]["id"] == left.json()["id"]
    assert bay["last_entry"]["id"] == entered.json()["id"]  # still shown after the exit


def test_candidates_do_not_change_the_state(
    client: TestClient, auth_headers: dict, workshop: Workshop
) -> None:
    client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=auth_headers)
    bay_id = _bays(client, auth_headers, workshop.id)[0]["id"]
    for kind in ("plate_observed", "entry_candidate", "exit_candidate"):
        assert _event(client, auth_headers, bay_id, kind, "А123ВС77").status_code == 201
    assert _bays(client, auth_headers, workshop.id)[0]["state"] == "free"


def test_second_entry_without_exit_goes_to_review(
    client: TestClient, auth_headers: dict, workshop: Workshop
) -> None:
    client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=auth_headers)
    bay_id = _bays(client, auth_headers, workshop.id)[0]["id"]
    _event(client, auth_headers, bay_id, "entry_confirmed", "А123ВС77")
    _event(client, auth_headers, bay_id, "entry_confirmed", "В777ОО77")
    assert _bays(client, auth_headers, workshop.id)[0]["state"] == "review"


def test_exit_without_an_open_interval_is_only_logged(
    client: TestClient, auth_headers: dict, workshop: Workshop
) -> None:
    client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=auth_headers)
    bay_id = _bays(client, auth_headers, workshop.id)[0]["id"]
    assert _event(client, auth_headers, bay_id, "exit_confirmed").status_code == 201
    assert _bays(client, auth_headers, workshop.id)[0]["state"] == "free"


def test_unknown_event_type_and_bad_image_are_rejected(
    client: TestClient, auth_headers: dict, workshop: Workshop
) -> None:
    client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=auth_headers)
    bay_id = _bays(client, auth_headers, workshop.id)[0]["id"]
    assert _event(client, auth_headers, bay_id, "teleport").status_code == 422
    assert (
        _event(client, auth_headers, bay_id, "entry_confirmed", snapshot_base64="%%%").status_code
        == 422
    )
    assert _event(client, auth_headers, uuid.uuid4(), "entry_confirmed").status_code == 404


def test_event_snapshot_is_served_from_storage(
    client: TestClient, auth_headers: dict, workshop: Workshop, uploads: dict
) -> None:
    client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=auth_headers)
    bay_id = _bays(client, auth_headers, workshop.id)[0]["id"]
    event = _event(
        client, auth_headers, bay_id, "entry_confirmed", "А123ВС77", snapshot_base64=JPEG
    )
    image = client.get(f"/api/v1/bays/events/{event.json()['id']}/snapshot", headers=auth_headers)
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    assert image.content == base64.b64decode(JPEG)

    no_photo = _event(client, auth_headers, bay_id, "exit_confirmed")
    assert no_photo.json()["has_snapshot"] is False
    missing = client.get(
        f"/api/v1/bays/events/{no_photo.json()['id']}/snapshot", headers=auth_headers
    )
    assert missing.status_code == 404


def test_snapshot_request_roundtrip(
    client: TestClient, auth_headers: dict, workshop: Workshop
) -> None:
    client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=auth_headers)
    bay = _bays(client, auth_headers, workshop.id)[0]
    client.patch(f"/api/v1/bays/{bay['id']}", json={"camera_code": "cam1"}, headers=auth_headers)

    created = client.post(f"/api/v1/bays/{bay['id']}/snapshot-requests", headers=auth_headers)
    assert created.status_code == 201
    request_id = created.json()["id"]
    # a second click while the first is still pending reuses it
    assert (
        client.post(f"/api/v1/bays/{bay['id']}/snapshot-requests", headers=auth_headers).json()[
            "id"
        ]
        == request_id
    )

    pending = client.get("/api/v1/bays/snapshot-requests/pending", headers=auth_headers).json()
    assert [(r["id"], r["camera_code"]) for r in pending["requests"]] == [(request_id, "cam1")]
    not_ready = client.get(
        f"/api/v1/bays/snapshot-requests/{request_id}/image", headers=auth_headers
    )
    assert not_ready.status_code == 404

    done = client.post(
        f"/api/v1/bays/snapshot-requests/{request_id}/result",
        json={"snapshot_base64": JPEG},
        headers=auth_headers,
    )
    assert done.json()["status"] == "done"
    image = client.get(f"/api/v1/bays/snapshot-requests/{request_id}/image", headers=auth_headers)
    assert image.status_code == 200 and image.content == base64.b64decode(JPEG)
    assert client.get("/api/v1/bays/snapshot-requests/pending", headers=auth_headers).json() == {
        "requests": []
    }


def test_node_can_report_a_failed_snapshot(
    client: TestClient, auth_headers: dict, workshop: Workshop
) -> None:
    client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=auth_headers)
    bay_id = _bays(client, auth_headers, workshop.id)[0]["id"]
    request_id = client.post(
        f"/api/v1/bays/{bay_id}/snapshot-requests", headers=auth_headers
    ).json()["id"]
    done = client.post(
        f"/api/v1/bays/snapshot-requests/{request_id}/result",
        json={"failed": True},
        headers=auth_headers,
    )
    assert done.json()["status"] == "failed"


def test_unanswered_requests_expire(db_session: Session, workshop: Workshop) -> None:
    bay = bay_service.create_bay(db_session, workshop_id=workshop.id, name="Бокс 1")
    request = bay_service.request_snapshot(db_session, bay.id)
    request.requested_at = datetime.now(UTC) - timedelta(minutes=5)
    db_session.commit()
    assert bay_service.pending_requests(db_session) == []
    db_session.refresh(request)
    assert request.status == SNAPSHOT_FAILED
    # an expired request is replaced by a fresh one
    assert bay_service.request_snapshot(db_session, bay.id).id != request.id
    assert db_session.query(BaySnapshotRequest).count() == 2


def test_normalize_plate() -> None:
    assert bay_service.normalize_plate(" a 123 bc 77 ") == "А123ВС77"
    assert bay_service.normalize_plate("") is None
    assert bay_service.normalize_plate(None) is None


def test_live_frame_does_not_touch_yandex_disk(
    client: TestClient, auth_headers: dict, workshop: Workshop, monkeypatch
) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("the live frame must not go through Yandex.Disk")

    monkeypatch.setattr(bay_service, "_upload", boom)
    monkeypatch.setattr(bay_service, "download_snapshot", boom)
    client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=auth_headers)
    bay_id = _bays(client, auth_headers, workshop.id)[0]["id"]
    request_id = client.post(
        f"/api/v1/bays/{bay_id}/snapshot-requests", headers=auth_headers
    ).json()["id"]
    client.post(
        f"/api/v1/bays/snapshot-requests/{request_id}/result",
        json={"snapshot_base64": JPEG},
        headers=auth_headers,
    )
    image = client.get(f"/api/v1/bays/snapshot-requests/{request_id}/image", headers=auth_headers)
    assert image.status_code == 200 and image.content == base64.b64decode(JPEG)


def test_only_the_latest_live_frame_of_a_bay_is_kept(
    client: TestClient, auth_headers: dict, workshop: Workshop
) -> None:
    client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=auth_headers)
    bay_id = _bays(client, auth_headers, workshop.id)[0]["id"]
    ids = []
    for _ in range(2):
        request_id = client.post(
            f"/api/v1/bays/{bay_id}/snapshot-requests", headers=auth_headers
        ).json()["id"]
        client.post(
            f"/api/v1/bays/snapshot-requests/{request_id}/result",
            json={"snapshot_base64": JPEG},
            headers=auth_headers,
        )
        ids.append(request_id)
    first = client.get(f"/api/v1/bays/snapshot-requests/{ids[0]}/image", headers=auth_headers)
    second = client.get(f"/api/v1/bays/snapshot-requests/{ids[1]}/image", headers=auth_headers)
    assert (first.status_code, second.status_code) == (404, 200)


def test_event_snapshot_download_is_retried(db_session: Session, monkeypatch) -> None:
    from types import SimpleNamespace

    import httpx

    monkeypatch.setattr(
        bay_service.telephony_settings_service,
        "get_telephony_settings",
        lambda db: SimpleNamespace(yandex_disk_token="t"),
    )
    calls = []

    def flaky(client, token, path):
        calls.append(path)
        if len(calls) < 3:
            raise httpx.ConnectError("ssl eof")
        return b"jpeg"

    monkeypatch.setattr(bay_service.yandex_disk_client, "download", flaky)
    assert bay_service.download_snapshot(db_session, "disk:/Bays/x.jpg") == b"jpeg"
    assert len(calls) == 3


def test_plate_is_parsed_from_the_1c_car_description() -> None:
    parse = bay_service.plate_from_description
    assert parse("Шкода Октавиа № А612СМ777 VIN XW8AN2NE8GH021166") == "А612СМ777"
    assert parse("HAVAL F7X № к209ом790 VIN XZGFF06A3NA619123") == "К209ОМ790"
    assert parse("Opel Astra № a579xt199 VIN W0L0AHL48A2084305") == "А579ХТ199"
    assert parse("SKODA KAROQ VIN XW8JC6NU2NH207268") is None
    assert parse(None) is None


def _work_order(number: str, car: str, day: int) -> WorkOrder:
    return WorkOrder(
        external_number=number,
        document_date=datetime(2026, 10, day, tzinfo=UTC),
        amount=0,
        vehicle_description=car,
    )


def test_closed_and_refused_work_orders_do_not_make_a_plate_known(
    client: TestClient, auth_headers: dict, db_session: Session
) -> None:
    closed = _work_order("ЗН-ЗАКР", "Peugeot № Е370ВО197 VIN P", 1)
    closed.status = "Закрыт"
    refused = _work_order("ЗН-ОТК", "Kia № М111ММ777 VIN K", 2)
    refused.status = "Отказ"
    older_open = _work_order("ЗН-РАБ", "Audi № К279КО777 VIN A", 3)
    older_open.status = "В работе"
    newer_closed = _work_order("ЗН-ЗАКР2", "Audi № К279КО777 VIN A", 9)
    newer_closed.status = "Закрыт"
    no_status = _work_order("ЗН-БЕЗ", "Ford № Х222ХХ777 VIN F", 4)
    db_session.add_all([closed, refused, older_open, newer_closed, no_status])
    db_session.commit()
    response = client.get("/api/v1/bays/known-plates", headers=auth_headers)
    plates = {p["plate"]: p["work_order_number"] for p in response.json()["plates"]}
    # закрытый и отказной не считаются; у Audi берётся открытый, хоть он и старше закрытого
    assert plates == {"К279КО777": "ЗН-РАБ", "Х222ХХ777": "ЗН-БЕЗ"}


def test_known_plates_come_from_work_orders_latest_first(
    client: TestClient, auth_headers: dict, db_session: Session
) -> None:
    db_session.add_all(
        [
            _work_order("ЗН-1", "Skoda № А612СМ777 VIN X", 1),
            _work_order("ЗН-2", "Skoda № А612СМ777 VIN X", 5),
            _work_order("ЗН-3", "Audi VIN Y", 6),
        ]
    )
    db_session.commit()
    response = client.get("/api/v1/bays/known-plates", headers=auth_headers)
    assert response.status_code == 200
    plates = response.json()["plates"]
    assert [(p["plate"], p["work_order_number"]) for p in plates] == [("А612СМ777", "ЗН-2")]


def test_entry_is_linked_to_the_work_order_of_the_plate(
    client: TestClient, auth_headers: dict, db_session: Session, workshop: Workshop
) -> None:
    order = _work_order("ЗН-7", "Skoda № А612СМ777 VIN X", 3)
    db_session.add(order)
    db_session.commit()
    client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=auth_headers)
    bay_id = _bays(client, auth_headers, workshop.id)[0]["id"]

    assert _event(client, auth_headers, bay_id, "entry_confirmed", "A612CM777").status_code == 201
    card = _bays(client, auth_headers, workshop.id)[0]
    assert (card["work_order_id"], card["work_order_number"]) == (str(order.id), "ЗН-7")
    event = db_session.query(BayEvent).one()
    assert event.work_order_id == order.id
    assert event.review_status == "auto"


def test_unmatched_entry_can_be_flagged_for_review(
    client: TestClient, auth_headers: dict, workshop: Workshop
) -> None:
    client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=auth_headers)
    bay = _bays(client, auth_headers, workshop.id)[0]
    response = _event(
        client, auth_headers, bay["id"], "entry_confirmed", "Е560КС97", needs_review=True
    )
    assert response.status_code == 201
    assert response.json()["review_status"] == "needs_review"
    assert response.json()["plate"] == "Е560КС97"


def _first_bay(client: TestClient, headers: dict, workshop: Workshop) -> dict:
    client.post(f"/api/v1/bays/defaults?workshop_id={workshop.id}", headers=headers)
    return _bays(client, headers, workshop.id)[0]


def test_history_lists_stays_newest_first_with_photos_duration_and_work_order(
    client: TestClient, auth_headers: dict, db_session: Session, workshop: Workshop, uploads
) -> None:
    order = _work_order("ЗН-9", "Skoda № А612СМ777 VIN X", 3)
    db_session.add(order)
    db_session.commit()
    bay = _first_bay(client, auth_headers, workshop)
    today = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0)
    for plate, hour, minutes in (("Е560КС977", 0, 30), ("А612СМ777", 2, 45)):
        start = today + timedelta(hours=hour)
        assert _event(
            client, auth_headers, bay["id"], "entry_confirmed", plate,
            occurred_at=start.isoformat(), snapshot_base64=JPEG,
        ).status_code == 201  # fmt: skip
        assert _event(
            client, auth_headers, bay["id"], "exit_confirmed", plate,
            occurred_at=(start + timedelta(minutes=minutes)).isoformat(), snapshot_base64=JPEG,
        ).status_code == 201  # fmt: skip
    # A stay on another day is outside the default filter.
    old = today - timedelta(days=3)
    _event(
        client, auth_headers, bay["id"], "entry_confirmed", "К111КК77", occurred_at=old.isoformat()
    )
    _event(
        client, auth_headers, bay["id"], "exit_confirmed", "К111КК77",
        occurred_at=(old + timedelta(hours=1)).isoformat(),
    )  # fmt: skip

    day = today.date().isoformat()
    response = client.get(
        f"/api/v1/bays/history?bay_id={bay['id']}&date_from={day}&date_to={day}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["plate"] for i in items] == ["А612СМ777", "Е560КС977"]
    newest, oldest = items
    assert newest["duration_seconds"] == 45 * 60
    assert newest["work_order_number"] == "ЗН-9"
    assert oldest["work_order_number"] is None
    assert newest["entry"]["has_snapshot"] and newest["exit"]["has_snapshot"]
    assert newest["bay_name"] == bay["name"]

    wide = client.get(
        f"/api/v1/bays/history?date_from={(today - timedelta(days=5)).date()}&date_to={day}",
        headers=auth_headers,
    )
    assert len(wide.json()["items"]) == 3


def test_history_rejects_an_inverted_range(client: TestClient, auth_headers: dict) -> None:
    response = client.get(
        "/api/v1/bays/history?date_from=2026-11-05&date_to=2026-11-04", headers=auth_headers
    )
    assert response.status_code == 422


def test_latest_frame_is_replaced_by_the_next_one(
    client: TestClient, auth_headers: dict, db_session: Session, workshop: Workshop, uploads
) -> None:
    bay = _first_bay(client, auth_headers, workshop)
    assert bay["latest_frame_at"] is None
    assert (
        client.get(f"/api/v1/bays/{bay['id']}/latest-frame", headers=auth_headers).status_code
        == 404
    )

    posted = client.post(
        f"/api/v1/bays/{bay['id']}/latest-frame",
        json={"snapshot_base64": JPEG},
        headers=auth_headers,
    )
    assert posted.status_code == 204
    assert _bays(client, auth_headers, workshop.id)[0]["latest_frame_at"] is not None
    image = client.get(f"/api/v1/bays/{bay['id']}/latest-frame", headers=auth_headers)
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"

    first_at = _bays(client, auth_headers, workshop.id)[0]["latest_frame_at"]
    again = client.post(
        f"/api/v1/bays/{bay['id']}/latest-frame",
        json={"snapshot_base64": JPEG},
        headers=auth_headers,
    )
    assert again.status_code == 204
    assert db_session.query(BayLatestFrame).count() == 1  # the old frame is replaced, not kept
    assert _bays(client, auth_headers, workshop.id)[0]["latest_frame_at"] >= first_at

    _event(client, auth_headers, bay["id"], "entry_confirmed", "А123ВС77")
    assert (
        _bays(client, auth_headers, workshop.id)[0]["latest_frame_at"] is not None
    )  # events keep it


def test_latest_frame_rejects_garbage(
    client: TestClient, auth_headers: dict, workshop: Workshop
) -> None:
    bay = _first_bay(client, auth_headers, workshop)
    response = client.post(
        f"/api/v1/bays/{bay['id']}/latest-frame",
        json={"snapshot_base64": "%%%"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_heartbeat_tracks_the_node_and_the_camera(
    client: TestClient, auth_headers: dict, workshop: Workshop
) -> None:
    bay = _first_bay(client, auth_headers, workshop)
    client.patch(f"/api/v1/bays/{bay['id']}", json={"camera_code": "cam1"}, headers=auth_headers)
    card = _bays(client, auth_headers, workshop.id)[0]
    assert (card["node_seen_at"], card["camera_ok"]) == (None, None)  # узел ещё не отчитывался

    def beat(ok: bool):
        return client.post(
            "/api/v1/bays/heartbeat",
            json={"camera_code": "cam1", "camera_ok": ok},
            headers=auth_headers,
        )

    assert beat(True).status_code == 204
    card = _bays(client, auth_headers, workshop.id)[0]
    assert card["camera_ok"] is True and card["node_seen_at"] is not None
    since_ok = card["camera_ok_since"]

    assert beat(True).status_code == 204  # то же состояние - момент начала не сдвигается
    assert _bays(client, auth_headers, workshop.id)[0]["camera_ok_since"] == since_ok

    assert beat(False).status_code == 204
    card = _bays(client, auth_headers, workshop.id)[0]
    assert card["camera_ok"] is False
    assert card["camera_ok_since"] >= since_ok


def test_bay_card_carries_the_video_frame_window_and_the_workshop_days(
    client: TestClient, auth_headers: dict, workshop: Workshop
) -> None:
    card = _first_bay(client, auth_headers, workshop)
    # Окно кадров 08:00-24:00 минус запас узла ±30 минут.
    assert (card["work_start"], card["work_end"]) == ("08:30:00", "23:30:00")
    assert card["work_days"] == [0, 1, 2, 3, 4]


def test_heartbeat_requires_a_camera_code(client: TestClient, auth_headers: dict) -> None:
    response = client.post(
        "/api/v1/bays/heartbeat", json={"camera_code": "", "camera_ok": True}, headers=auth_headers
    )
    assert response.status_code == 422
