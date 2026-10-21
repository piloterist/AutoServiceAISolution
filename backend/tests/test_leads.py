"""Tests for /api/v1/leads - website lead intake (separate token auth, not
verify_api_token), listing with computed status, and settings.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.call_record import CallRecord
from app.models.leads_settings import LeadsSettings
from app.models.website_lead import WebsiteLead

INTAKE_URL = "/api/v1/leads/intake"
LEADS_URL = "/api/v1/leads"
OPEN_URL = "/api/v1/leads/open"
SETTINGS_URL = "/api/v1/leads/settings"


def _enable_intake(
    db_session: Session, *, token: str = "test-intake-token", stale_after_days: int = 7
) -> None:
    db_session.add(
        LeadsSettings(id=1, enabled=True, intake_token=token, stale_after_days=stale_after_days)
    )
    db_session.commit()


def _call(
    db_session: Session,
    *,
    phone: str,
    when: datetime,
    call_type: str = "OUT",
    talk_sec: int = 30,
) -> CallRecord:
    call = CallRecord(
        id=uuid.uuid4(),
        provider="zeon",
        external_id=str(uuid.uuid4()),
        call_date=when.date(),
        occurred_at=when,
        call_type=call_type,
        client=phone,
        operator="302",
        wait_sec=5,
        talk_sec=talk_sec,
        answered=talk_sec > 0,
    )
    db_session.add(call)
    db_session.commit()
    return call


def _lead(db_session: Session, *, phone: str) -> WebsiteLead:
    lead = WebsiteLead(id=uuid.uuid4(), source="other", phone=phone, raw_payload={})
    db_session.add(lead)
    db_session.commit()
    return lead


# ---- Intake ----------------------------------------------------------------


def test_intake_rejects_missing_token(client, db_session) -> None:
    _enable_intake(db_session)
    response = client.post(INTAKE_URL, json={"user_phone": "+7 (900) 000-00-00"})
    assert response.status_code == 401


def test_intake_rejects_wrong_token(client, db_session) -> None:
    _enable_intake(db_session)
    response = client.post(
        INTAKE_URL,
        json={"user_phone": "+7 (900) 000-00-00"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_intake_rejects_disabled(client, db_session) -> None:
    db_session.add(LeadsSettings(id=1, enabled=False, intake_token="t"))
    db_session.commit()
    response = client.post(
        INTAKE_URL,
        json={"user_phone": "+7 (900) 000-00-00"},
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 401


def test_intake_rejects_missing_phone(client, db_session) -> None:
    _enable_intake(db_session)
    response = client.post(
        INTAKE_URL,
        json={"form_name": "Рассрочка"},
        headers={"Authorization": "Bearer test-intake-token"},
    )
    assert response.status_code == 422


def test_intake_accepts_quiz_body_and_extracts_photos(client, db_session) -> None:
    _enable_intake(db_session)
    payload = {
        "adv_channel": "(direct)",
        "page_url": "/kuzovnoy_remont/quiz/",
        "quiz_damage[1]": "Бампер передний",
        "quiz_damage[2]": "Капот",
        "files": "img1.jpg;img2.jpg;",
        "folder": "438730",
        "quiz_evacuator": "Да, забрать",
        "user_phone": "+7 (900) 000-00-01",
        "politic": "on",
        "recaptcha_response": "should-not-be-stored",
    }
    response = client.post(
        INTAKE_URL, json=payload, headers={"Authorization": "Bearer test-intake-token"}
    )
    assert response.status_code == 201

    listed = client.get(LEADS_URL, headers={"Authorization": "Bearer test-intake-token"})
    # /leads itself needs the normal API token, not the intake one.
    assert listed.status_code == 401


def test_full_lead_lifecycle(client, db_session, auth_headers) -> None:
    _enable_intake(db_session)
    client.post(
        INTAKE_URL,
        json={
            "quiz_damage[1]": "Бампер передний",
            "files": "img1.jpg;",
            "folder": "438730",
            "user_phone": "+7 (900) 000-00-02",
        },
        headers={"Authorization": "Bearer test-intake-token"},
    )

    listed = client.get(LEADS_URL, headers=auth_headers)
    assert listed.status_code == 200
    leads = listed.json()["leads"]
    assert len(leads) == 1
    lead = leads[0]
    assert lead["source"] == "quiz_body"
    assert lead["phone"] == "9000000002"
    # No yandex_disk_token configured in this test DB -> nothing to archive
    # to, so the dead pan-motors.ru link is dropped rather than stored (see
    # lead_photos_service.archive_photos) - photo archiving itself is
    # covered by test_lead_photos_service.py and
    # test_intake_archives_photos_when_disk_token_configured below.
    assert lead["photos"] is None
    assert "recaptcha_response" not in lead["raw_payload"]
    assert lead["status"] == "open"


def test_intake_archives_photos_when_disk_token_configured(
    client, db_session, auth_headers, monkeypatch
) -> None:
    import httpx

    from app.services.telephony_settings_service import get_telephony_settings
    from app.services.yandex_disk_client import API_BASE

    _enable_intake(db_session)
    settings = get_telephony_settings(db_session)
    settings.yandex_disk_token = "a-disk-token"
    db_session.commit()

    photo_url = "https://pan-motors.ru/tmp_files/555/img1.jpg"
    upload_href = "https://uploader.disk.yandex.net/fake"
    # TestClient itself is httpx-backed, so patching httpx.Client.get/.put
    # at the class level also intercepts the test's OWN requests to the
    # app - anything that isn't one of our two real external targets must
    # fall through to the original implementation.
    original_get = httpx.Client.get
    original_put = httpx.Client.put

    def fake_get(self, url, **kwargs):  # noqa: ANN001
        url_str = str(url)
        if url_str == photo_url:
            return httpx.Response(
                200,
                content=b"bytes",
                headers={"content-type": "image/jpeg"},
                request=httpx.Request("GET", url_str),
            )
        if url_str == f"{API_BASE}/resources/upload":
            return httpx.Response(
                200, json={"href": upload_href}, request=httpx.Request("GET", url_str)
            )
        return original_get(self, url, **kwargs)

    def fake_put(self, url, **kwargs):  # noqa: ANN001
        url_str = str(url)
        if url_str == upload_href or url_str.startswith(f"{API_BASE}/resources"):
            return httpx.Response(201, request=httpx.Request("PUT", url_str))
        return original_put(self, url, **kwargs)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setattr(httpx.Client, "put", fake_put)

    response = client.post(
        INTAKE_URL,
        json={"files": "img1.jpg;", "folder": "555", "user_phone": "+7 (900) 000-00-09"},
        headers={"Authorization": "Bearer test-intake-token"},
    )
    assert response.status_code == 201
    lead_id = response.json()["id"]

    lead = client.get(LEADS_URL, headers=auth_headers).json()["leads"][0]
    assert lead["photos"] == [f"/api/leads/{lead_id}/photos/img1.jpg"]


def test_intake_archives_inline_photo_bytes_when_present(
    client, db_session, auth_headers, monkeypatch
) -> None:
    """Product ask, 2026-10-21: the site's own tmp_files/<folder>/<name>
    link gets cleaned up before our separate fetch can reliably reach it
    (see services/lead_photos_service.archive_photos's own docstring), so
    the site now sends photo bytes inline (`photos_data`) instead - see
    services/leads_service._extract_inline_photos and Pan-Motors_web.md.
    No external photo fetch at all here, unlike the files/folder path
    above - just the Yandex.Disk upload."""
    import base64

    import httpx

    from app.services.telephony_settings_service import get_telephony_settings
    from app.services.yandex_disk_client import API_BASE

    _enable_intake(db_session)
    settings = get_telephony_settings(db_session)
    settings.yandex_disk_token = "a-disk-token"
    db_session.commit()

    upload_href = "https://uploader.disk.yandex.net/fake-inline"
    original_get = httpx.Client.get
    original_put = httpx.Client.put

    def fake_get(self, url, **kwargs):  # noqa: ANN001
        url_str = str(url)
        if url_str == f"{API_BASE}/resources/upload":
            return httpx.Response(
                200, json={"href": upload_href}, request=httpx.Request("GET", url_str)
            )
        return original_get(self, url, **kwargs)

    def fake_put(self, url, **kwargs):  # noqa: ANN001
        url_str = str(url)
        if url_str == upload_href or url_str.startswith(f"{API_BASE}/resources"):
            return httpx.Response(201, request=httpx.Request("PUT", url_str))
        return original_put(self, url, **kwargs)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setattr(httpx.Client, "put", fake_put)

    response = client.post(
        INTAKE_URL,
        json={
            "user_phone": "+7 (900) 000-00-10",
            "photos_data": [
                {
                    "filename": "img1.jpg",
                    "content_base64": base64.b64encode(b"real-bytes").decode(),
                }
            ],
        },
        headers={"Authorization": "Bearer test-intake-token"},
    )
    assert response.status_code == 201
    lead_id = response.json()["id"]

    lead = client.get(LEADS_URL, headers=auth_headers).json()["leads"][0]
    assert lead["photos"] == [f"/api/leads/{lead_id}/photos/img1.jpg"]
    assert "photos_data" not in lead["raw_payload"]


def test_intake_prefers_inline_photo_bytes_over_tmp_files_link(
    client, db_session, auth_headers, monkeypatch
) -> None:
    """When the site sends both (e.g. mid-rollout of the PHP change), the
    inline bytes win outright - no separate, racy tmp_files fetch is even
    attempted."""
    import base64

    import httpx

    from app.services.telephony_settings_service import get_telephony_settings
    from app.services.yandex_disk_client import API_BASE

    _enable_intake(db_session)
    settings = get_telephony_settings(db_session)
    settings.yandex_disk_token = "a-disk-token"
    db_session.commit()

    upload_href = "https://uploader.disk.yandex.net/fake-prefer"
    original_get = httpx.Client.get
    original_put = httpx.Client.put
    fetched_urls: list[str] = []

    def fake_get(self, url, **kwargs):  # noqa: ANN001
        url_str = str(url)
        fetched_urls.append(url_str)
        if url_str == f"{API_BASE}/resources/upload":
            return httpx.Response(
                200, json={"href": upload_href}, request=httpx.Request("GET", url_str)
            )
        return original_get(self, url, **kwargs)

    def fake_put(self, url, **kwargs):  # noqa: ANN001
        url_str = str(url)
        if url_str == upload_href or url_str.startswith(f"{API_BASE}/resources"):
            return httpx.Response(201, request=httpx.Request("PUT", url_str))
        return original_put(self, url, **kwargs)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setattr(httpx.Client, "put", fake_put)

    response = client.post(
        INTAKE_URL,
        json={
            "user_phone": "+7 (900) 000-00-11",
            "files": "other.jpg;",
            "folder": "999",
            "photos_data": [
                {
                    "filename": "img1.jpg",
                    "content_base64": base64.b64encode(b"real-bytes").decode(),
                }
            ],
        },
        headers={"Authorization": "Bearer test-intake-token"},
    )
    assert response.status_code == 201
    lead_id = response.json()["id"]

    lead = client.get(LEADS_URL, headers=auth_headers).json()["leads"][0]
    assert lead["photos"] == [f"/api/leads/{lead_id}/photos/img1.jpg"]
    assert not any("tmp_files" in u for u in fetched_urls)


def test_source_classification(client, db_session, auth_headers) -> None:
    _enable_intake(db_session)
    cases = [
        (
            {
                "form_name": "Получите быстрый ответ по цене и времени записи",
                "user_phone": "9110000001",
            },
            "quiz_mechanical",
        ),
        ({"form_name": "Получить консультацию", "user_phone": "9110000002"}, "consultation"),
        ({"form_name": "Рассрочка", "user_phone": "9110000003"}, "installment"),
        ({"form_name": "Something else entirely", "user_phone": "9110000004"}, "other"),
    ]
    for payload, _expected_source in cases:
        client.post(INTAKE_URL, json=payload, headers={"Authorization": "Bearer test-intake-token"})

    listed = client.get(LEADS_URL, headers=auth_headers).json()["leads"]
    by_phone = {lead["phone"]: lead["source"] for lead in listed}
    for payload, expected_source in cases:
        assert by_phone[payload["user_phone"]] == expected_source


# ---- Status computation ------------------------------------------------


def test_lead_resolved_by_later_real_outbound_call(client, db_session, auth_headers) -> None:
    _enable_intake(db_session)
    client.post(
        INTAKE_URL,
        json={"form_name": "Рассрочка", "user_phone": "9220000001"},
        headers={"Authorization": "Bearer test-intake-token"},
    )
    _call(
        db_session, phone="9220000001", when=datetime.now(UTC) + timedelta(minutes=1), talk_sec=30
    )

    leads = client.get(LEADS_URL, headers=auth_headers).json()["leads"]
    assert leads[0]["status"] == "resolved"


def test_lead_not_resolved_by_inbound_call(client, db_session, auth_headers) -> None:
    """Only an OUTBOUND call resolves a lead - an inbound call proves
    nothing about whether staff followed up (confirmed product decision)."""
    _enable_intake(db_session)
    client.post(
        INTAKE_URL,
        json={"form_name": "Рассрочка", "user_phone": "9220000002"},
        headers={"Authorization": "Bearer test-intake-token"},
    )
    _call(
        db_session,
        phone="9220000002",
        when=datetime.now(UTC) + timedelta(minutes=1),
        call_type="IN",
        talk_sec=30,
    )

    leads = client.get(LEADS_URL, headers=auth_headers).json()["leads"]
    assert leads[0]["status"] == "open"


def test_lead_not_resolved_by_short_outbound_call(client, db_session, auth_headers) -> None:
    _enable_intake(db_session)
    client.post(
        INTAKE_URL,
        json={"form_name": "Рассрочка", "user_phone": "9220000003"},
        headers={"Authorization": "Bearer test-intake-token"},
    )
    _call(db_session, phone="9220000003", when=datetime.now(UTC) + timedelta(minutes=1), talk_sec=3)

    leads = client.get(LEADS_URL, headers=auth_headers).json()["leads"]
    assert leads[0]["status"] == "open"


def test_lead_not_resolved_by_earlier_call(client, db_session, auth_headers) -> None:
    """A call that happened BEFORE the lead arrived can't be the callback
    for it."""
    _enable_intake(db_session)
    _call(db_session, phone="9220000004", when=datetime.now(UTC) - timedelta(days=1), talk_sec=30)
    client.post(
        INTAKE_URL,
        json={"form_name": "Рассрочка", "user_phone": "9220000004"},
        headers={"Authorization": "Bearer test-intake-token"},
    )

    leads = client.get(LEADS_URL, headers=auth_headers).json()["leads"]
    assert leads[0]["status"] == "open"


def test_lead_goes_stale_after_configured_days(client, db_session, auth_headers) -> None:
    _enable_intake(db_session, stale_after_days=3)
    client.post(
        INTAKE_URL,
        json={"form_name": "Рассрочка", "user_phone": "9220000005"},
        headers={"Authorization": "Bearer test-intake-token"},
    )
    # Backdate the lead past the 3-day stale window.
    from app.models.website_lead import WebsiteLead

    lead = db_session.query(WebsiteLead).filter_by(phone="9220000005").one()
    lead.created_at = datetime.now(UTC) - timedelta(days=4)
    db_session.commit()

    leads = client.get(LEADS_URL, headers=auth_headers).json()["leads"]
    assert leads[0]["status"] == "stale"

    # A stale (never-contacted) lead must not show up in /open.
    open_leads = client.get(OPEN_URL, headers=auth_headers).json()
    assert open_leads["count"] == 0


# ---- Settings --------------------------------------------------------------


def test_settings_defaults_and_no_token_leak(client, auth_headers) -> None:
    response = client.get(SETTINGS_URL, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["has_intake_token"] is False
    assert "intake_token" not in body


def test_regenerate_token_returns_it_once(client, auth_headers) -> None:
    response = client.post(f"{SETTINGS_URL}/regenerate-token", headers=auth_headers)
    assert response.status_code == 200
    token = response.json()["intake_token"]
    assert len(token) > 20

    settings = client.get(SETTINGS_URL, headers=auth_headers).json()
    assert settings["has_intake_token"] is True
    assert "intake_token" not in settings


def test_update_settings_persists(client, auth_headers) -> None:
    response = client.put(
        SETTINGS_URL, headers=auth_headers, json={"enabled": True, "stale_after_days": 14}
    )
    assert response.status_code == 200
    assert response.json()["stale_after_days"] == 14

    refetched = client.get(SETTINGS_URL, headers=auth_headers).json()
    assert refetched["enabled"] is True
    assert refetched["stale_after_days"] == 14


# ---- Call history (expanded lead detail card, product ask 2026-10-21) ------


def test_lead_calls_lists_calls_matching_phone_in_both_directions(
    client, db_session, auth_headers
) -> None:
    lead = _lead(db_session, phone="9991234567")
    inbound = _call(
        db_session,
        phone="9991234567",
        when=datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
        call_type="IN",
        talk_sec=20,
    )
    outbound = _call(
        db_session,
        phone="9991234567",
        when=datetime(2026, 10, 2, 10, 0, tzinfo=UTC),
        call_type="OUT",
        talk_sec=40,
    )
    # A call to an unrelated number must never show up here.
    _call(db_session, phone="9990000000", when=datetime(2026, 10, 1, 11, 0, tzinfo=UTC))

    response = client.get(f"{LEADS_URL}/{lead.id}/calls", headers=auth_headers)

    assert response.status_code == 200
    calls = response.json()["calls"]
    # Oldest first, same convention as Телефония's own drill-down.
    assert [c["call_id"] for c in calls] == [str(inbound.id), str(outbound.id)]
    assert calls[0]["call_type"] == "IN"
    assert calls[1]["call_type"] == "OUT"


def test_lead_calls_includes_transcript_before_and_after_processing(
    client, db_session, auth_headers
) -> None:
    lead = _lead(db_session, phone="9991234567")
    call = _call(
        db_session, phone="9991234567", when=datetime(2026, 10, 1, 10, 0, tzinfo=UTC), talk_sec=30
    )
    call.transcript_text = "Адаптированный текст"
    call.transcript_text_raw = "Сырой текст"
    call.topic_tag = "Замена масла"
    call.quality_score = 8
    call.quality_review = "Хороший звонок"
    db_session.commit()

    response = client.get(f"{LEADS_URL}/{lead.id}/calls", headers=auth_headers)

    body = response.json()["calls"][0]
    assert body["transcript_text"] == "Адаптированный текст"
    assert body["transcript_text_raw"] == "Сырой текст"
    assert body["topic_tag"] == "Замена масла"
    assert body["quality_score"] == 8
    assert body["quality_review"] == "Хороший звонок"


def test_lead_calls_has_recording_reflects_raw_payload_link(
    client, db_session, auth_headers
) -> None:
    lead = _lead(db_session, phone="9991234567")
    with_link = _call(db_session, phone="9991234567", when=datetime(2026, 10, 1, 10, 0, tzinfo=UTC))
    with_link.raw_payload = {"link": "abc123"}
    without_link = _call(
        db_session, phone="9991234567", when=datetime(2026, 10, 1, 11, 0, tzinfo=UTC)
    )
    db_session.commit()

    response = client.get(f"{LEADS_URL}/{lead.id}/calls", headers=auth_headers)

    by_id = {c["call_id"]: c["has_recording"] for c in response.json()["calls"]}
    assert by_id[str(with_link.id)] is True
    assert by_id[str(without_link.id)] is False


def test_lead_calls_404_for_unknown_lead(client, auth_headers) -> None:
    response = client.get(f"{LEADS_URL}/{uuid.uuid4()}/calls", headers=auth_headers)
    assert response.status_code == 404
