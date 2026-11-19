"""Tests for /api/v1/leads - website lead intake (separate token auth, not
verify_api_token), listing with computed status, and settings.
"""

import json
import time
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

    photo_url = "https://pan-motors.ru/tmp_files/files-555/img1.jpg"
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


def _fake_site_and_disk(monkeypatch, served: dict[str, bytes]) -> None:  # noqa: ANN001
    """The site's photo links (`served`: url -> bytes) and Yandex.Disk, both faked."""
    import httpx

    from app.services.yandex_disk_client import API_BASE

    upload_href = "https://uploader.disk.yandex.net/fake-copy"
    original_get = httpx.Client.get
    original_put = httpx.Client.put

    def fake_get(self, url, **kwargs):  # noqa: ANN001
        url_str = str(url)
        if url_str in served:
            return httpx.Response(
                200,
                content=served[url_str],
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


def test_intake_downloads_the_site_photo_links_after_answering(
    client, db_session, auth_headers, monkeypatch
) -> None:
    """The site (no PHP-FPM) keeps copies of the photos and sends only their links
    (`photo_urls`); we answer at once and download them in the background. Names with
    spaces / Cyrillic arrive percent-encoded."""
    from app.services.telephony_settings_service import get_telephony_settings

    _enable_intake(db_session)
    get_telephony_settings(db_session).yandex_disk_token = "a-disk-token"
    db_session.commit()
    base = "https://pan-motors.ru/tmp_files/crm_photos/0123abcd"
    _fake_site_and_disk(
        monkeypatch,
        {f"{base}/img1.jpg": b"one", f"{base}/%D0%A4%D0%BE%D1%82%D0%BE%202.jpg": b"two"},
    )

    response = client.post(
        INTAKE_URL,
        json={
            "user_phone": "+7 (900) 000-00-11",
            "files": "img1.jpg;Фото 2.jpg;",
            "folder": "999",
            "photo_urls": [f"{base}/img1.jpg", f"{base}/%D0%A4%D0%BE%D1%82%D0%BE%202.jpg"],
        },
        headers={"Authorization": "Bearer test-intake-token"},
    )
    assert response.status_code == 201
    lead_id = response.json()["id"]

    lead = client.get(LEADS_URL, headers=auth_headers).json()["leads"][0]
    assert lead["photos"] == [
        f"/api/leads/{lead_id}/photos/img1.jpg",
        f"/api/leads/{lead_id}/photos/Фото 2.jpg",
    ]
    assert "photo_urls" not in lead["raw_payload"]


def test_intake_ignores_photo_links_outside_the_sites_tmp_files(
    client, db_session, auth_headers, monkeypatch
) -> None:
    from app.services.telephony_settings_service import get_telephony_settings

    _enable_intake(db_session)
    get_telephony_settings(db_session).yandex_disk_token = "a-disk-token"
    db_session.commit()
    bad = [
        "http://pan-motors.ru/tmp_files/x/a.jpg",  # not https
        "https://127.0.0.1/tmp_files/x/a.jpg",  # an IP address
        "https://localhost/tmp_files/x/a.jpg",  # no dot in the host
        "https://pan-motors.ru/wp-config.php",  # outside tmp_files
    ]
    _fake_site_and_disk(monkeypatch, {url: b"x" for url in bad})

    response = client.post(
        INTAKE_URL,
        json={"user_phone": "+7 (900) 000-00-12", "photo_urls": bad},
        headers={"Authorization": "Bearer test-intake-token"},
    )
    assert response.status_code == 201  # the lead itself is never refused over a link
    assert client.get(LEADS_URL, headers=auth_headers).json()["leads"][0]["photos"] is None


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


def test_lead_resolved_by_later_real_inbound_call(client, db_session, auth_headers) -> None:
    """Revised 2026-10-21 (see services/leads_service.py's own module
    docstring for the full story): a real, answered inbound call - the
    client calling back and actually talking to staff - resolves a lead
    too, same as an outbound one. Was previously "open" under the old
    outbound-only rule, which left leads like this stuck as "Просрочена"
    despite a real, substantive conversation having taken place."""
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
    assert leads[0]["status"] == "resolved"


def test_lead_not_resolved_by_short_inbound_call(client, db_session, auth_headers) -> None:
    """An inbound call still has to be a real conversation
    (>= MIN_REAL_TALK_SEC) to count - same bar as outbound, just no longer
    gated on direction too."""
    _enable_intake(db_session)
    client.post(
        INTAKE_URL,
        json={"form_name": "Рассрочка", "user_phone": "9220000003"},
        headers={"Authorization": "Bearer test-intake-token"},
    )
    _call(
        db_session,
        phone="9220000003",
        when=datetime.now(UTC) + timedelta(minutes=1),
        call_type="IN",
        talk_sec=2,
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


def test_lead_work_order_match_uses_real_creation_date_not_import_time(
    db_session: Session,
) -> None:
    """The matched work order is the first one on the lead's phone whose
    ДатаСоздания (created_date) is after the lead. created_at - when our
    import first saw the row - is "now" for every row here, but must be
    ignored: an order created in 2025 and merely imported today is not a
    result of today's lead (product ask, 2026-10-23)."""
    from decimal import Decimal

    from app.models.work_order import WorkOrder
    from app.services import leads_service

    lead_time = datetime.now(UTC) - timedelta(days=2)
    lead = WebsiteLead(
        source="consultation",
        phone="9990000007",
        raw_payload={},
        created_at=lead_time,
    )
    db_session.add(lead)
    for number, created in (
        ("OLD-IMPORTED-LATE", datetime.now(UTC) - timedelta(days=400)),
        ("NEW", lead_time + timedelta(hours=5)),
    ):
        db_session.add(
            WorkOrder(
                external_number=number,
                source_system="alpha-auto",
                document_date=created,
                created_date=created,
                amount=Decimal("100.00"),
                phone="+7 (999) 000-00-07",
            )
        )
    db_session.commit()

    (item,) = leads_service.list_leads(db_session)

    assert item.matched_work_order_number == "NEW"


def test_intake_records_which_site_sent_the_lead(client, db_session, auth_headers) -> None:
    _enable_intake(db_session)
    response = client.post(
        INTAKE_URL,
        json={"user_phone": "+7 (900) 111-22-33", "page_url": "/kuzovnoy_remont/quiz/"},
        headers={
            "Authorization": "Bearer test-intake-token",
            "Origin": "https://www.second-site.ru",
            "X-Forwarded-For": "203.0.113.7, 10.0.0.1",
            "User-Agent": "Mozilla/5.0 test",
        },
    )
    assert response.status_code == 201
    lead = db_session.get(WebsiteLead, uuid.UUID(response.json()["id"]))
    assert lead.request_meta["site"] == "second-site.ru"
    assert lead.request_meta["ip"] == "203.0.113.7"

    listed = client.get(LEADS_URL, headers=auth_headers).json()["leads"]
    assert listed[0]["site"] == "second-site.ru"
    assert listed[0]["request_meta"]["origin"] == "https://www.second-site.ru"


def test_site_falls_back_to_the_referer_and_old_leads_have_none(
    client, db_session, auth_headers
) -> None:
    _enable_intake(db_session)
    client.post(
        INTAKE_URL,
        json={"user_phone": "+7 (900) 111-22-34"},
        headers={
            "Authorization": "Bearer test-intake-token",
            "Referer": "https://third-site.ru/kuzovnoy_remont/quiz/",
        },
    )
    _lead(db_session, phone="9005556677")  # без метаданных, как до этого обновления
    sites = {
        lead["phone"]: lead["site"]
        for lead in client.get(LEADS_URL, headers=auth_headers).json()["leads"]
    }
    assert sites["9001112234"] == "third-site.ru"
    assert sites["9005556677"] is None


def test_site_is_taken_from_the_wordpress_user_agent(client, db_session, auth_headers) -> None:
    _enable_intake(db_session)
    response = client.post(
        INTAKE_URL,
        json={"user_phone": "+7 (900) 111-22-35"},
        headers={
            "Authorization": "Bearer test-intake-token",
            "User-Agent": "WordPress/7.1.3; https://pan-motors.ru",
        },
    )
    assert response.status_code == 201
    lead = db_session.get(WebsiteLead, uuid.UUID(response.json()["id"]))
    assert lead.request_meta["site"] == "pan-motors.ru"
    # A lead stored before this rule (no "site" in the meta) still shows its site on read.
    db_session.query(WebsiteLead).filter(WebsiteLead.id == lead.id).update(
        {"request_meta": {"user_agent": "WordPress/7.1.3; https://second-site.ru"}}
    )
    db_session.commit()
    listed = client.get(LEADS_URL, headers=auth_headers).json()["leads"]
    assert listed[0]["site"] == "second-site.ru"


# ---- заявки с сайта на Webflow: форма / multipart, свои имена полей, фото файлами ----------

WEBFLOW_QUIZ = {
    "required_fields": "Phone number",
    "Страница": "https://panmotors77.ru/quiz",
    "Форма": "Кузов",
    "Bamper": "on",
    "Kapot": "on",
    "No photo": "on",
    "Evakuator": "Нет",
    "Summa": "500000",
    "Budget": "Мой бюджет",
    "Gift": "Покраска",
    "message": "Telegram",
    "Phone number": "+7 (000) 000-00-00",
}


def _form_lead(client, data=None, files=None, headers=None):
    return client.post(
        INTAKE_URL,
        data=data,
        files=files,
        headers={"Authorization": "Bearer test-intake-token", **(headers or {})},
    )


def test_a_webflow_form_is_understood_without_the_sites_field_names(client, db_session) -> None:
    _enable_intake(db_session)
    response = _form_lead(client, data=WEBFLOW_QUIZ)  # urlencoded
    assert response.status_code == 201, response.text
    lead = db_session.get(WebsiteLead, uuid.UUID(response.json()["id"]))
    assert lead.phone == "0000000000" and lead.source == "quiz_body"
    payload = lead.raw_payload
    assert payload["page_url"] == "https://panmotors77.ru/quiz"
    assert payload["form_name"] == "Кузов"
    assert set(payload["quiz_damage"].values()) == {"Бампер", "Капот"}
    assert (payload["quiz_budget"], payload["quiz_budget_sum"]) == ("Мой бюджет", "500000")
    assert (payload["quiz_gift"], payload["quiz_messenger"]) == ("Покраска", "Telegram")
    # Служебное и сопоставленное не дублируется под старыми именами.
    for stale in ("required_fields", "Phone number", "Bamper", "Форма", "Страница"):
        assert stale not in payload


def test_multipart_with_an_empty_file_part_and_php_style_names_is_accepted(
    client, db_session
) -> None:
    _enable_intake(db_session)
    # PHP превращает пробелы в именах полей в подчёркивания; пустой file[] - как у браузера без фото.
    data = {
        "Phone_2": "8 900 111-22-33",
        "Name_2": "Иван",
        "advchannel": "yandex",
        "Форма": "evacuator",
    }
    files = {"file[]": ("", b"", "application/octet-stream")}
    response = _form_lead(client, data=data, files=files)
    assert response.status_code == 201, response.text
    lead = db_session.get(WebsiteLead, uuid.UUID(response.json()["id"]))
    assert lead.phone == "9001112233" and lead.name == "Иван"
    assert lead.raw_payload["adv_channel"] == "yandex"
    assert lead.photos is None


def test_photos_in_a_multipart_request_are_taken_without_the_files_folder_scheme(
    client, db_session, monkeypatch
) -> None:
    from app.services import lead_photos_service

    _enable_intake(db_session)
    seen: dict = {}

    def fake_archive(photos, lead_id, token):
        seen["names"] = [name for name, _ in photos]
        return [f"/api/leads/{lead_id}/photos/{name}" for name, _ in photos]

    monkeypatch.setattr(lead_photos_service, "archive_photo_bytes", fake_archive)
    files = [
        ("file[]", ("../evil name.jpg", b"\xff\xd8jpeg-1", "image/jpeg")),
        ("file[]", ("", b"", "application/octet-stream")),
        ("file[]", ("second.png", b"\x89PNGdata", "image/png")),
    ]
    response = _form_lead(client, data={"Phone number": "+7 900 000-11-22"}, files=files)
    assert response.status_code == 201, response.text
    lead = db_session.get(WebsiteLead, uuid.UUID(response.json()["id"]))
    assert seen["names"] == ["evil name.jpg", "second.png"]  # без каталога, пустой part пропущен
    assert len(lead.photos) == 2


def test_the_request_meta_records_what_actually_arrived_for_photo_diagnostics(
    client, db_session, monkeypatch
) -> None:
    from app.services import lead_photos_service

    _enable_intake(db_session)
    monkeypatch.setattr(lead_photos_service, "archive_photo_bytes", lambda *_: [])  # Диск не принял
    files = [
        ("file[]", ("a.jpg", b"jpeg-bytes", "image/jpeg")),
        ("file[]", ("", b"", "application/octet-stream")),
    ]
    response = _form_lead(
        client, data={"Phone number": "+7 900 000-11-22", "Name": "T"}, files=files
    )
    assert response.status_code == 201, response.text
    intake = json.loads(
        db_session.get(WebsiteLead, uuid.UUID(response.json()["id"])).request_meta["intake"]
    )
    assert intake["content_type"] == "multipart/form-data"
    # Пустую часть без имени файла (браузер без фото) парсер формы отбрасывает.
    assert [(p["filename"], p["kept"]) for p in intake["file_parts"]] == [("a.jpg", True)]
    assert intake["photos_in_request"] == 1 and intake["photos_archived"] == 0  # дошло, не легло
    assert "Phone number" in intake["fields"] or "user_phone" in intake["fields"]

    nothing = _form_lead(client, data={"Phone number": "+7 900 000-11-23"})
    meta = json.loads(
        db_session.get(WebsiteLead, uuid.UUID(nothing.json()["id"])).request_meta["intake"]
    )
    assert meta["file_parts"] == [] and meta["photos_in_request"] == 0


def test_the_old_json_format_is_unchanged_and_a_form_without_phone_is_still_rejected(
    client, db_session
) -> None:
    _enable_intake(db_session)
    ok = client.post(
        INTAKE_URL,
        json={"user_phone": "+7 (900) 123-45-67", "form_name": "Рассрочка", "adv_channel": "ya"},
        headers={"Authorization": "Bearer test-intake-token"},
    )
    assert ok.status_code == 201
    lead = db_session.get(WebsiteLead, uuid.UUID(ok.json()["id"]))
    assert lead.source == "installment" and lead.raw_payload["adv_channel"] == "ya"
    assert _form_lead(client, data={"Name": "Без телефона"}).status_code == 422
    assert (
        client.post(
            INTAKE_URL, json=["не объект"], headers={"Authorization": "Bearer test-intake-token"}
        ).status_code
        == 422
    )


def test_the_intake_diagnostics_say_what_photo_links_the_site_sent_and_what_came_of_them(
    client, db_session, monkeypatch
) -> None:
    from app.services import lead_photos_service

    _enable_intake(db_session)

    def fake_fetch(urls, report=None, time_budget=None):
        report.append({"url": urls[0], "result": "bad_response", "status": 404})
        return []

    monkeypatch.setattr(lead_photos_service, "fetch_photos", fake_fetch)
    good = "https://panmotors77.ru/tmp_files/crm_photos/abc/IMG_1.jpg"
    response = client.post(
        INTAKE_URL,
        json={
            "user_phone": "+7 (900) 123-45-67",
            "photo_urls": [good, "https://panmotors77.ru/other/script.php"],
        },
        headers={"Authorization": "Bearer test-intake-token"},
    )
    assert response.status_code == 201, response.text
    db_session.expire_all()
    lead = db_session.get(WebsiteLead, uuid.UUID(response.json()["id"]))
    intake = json.loads(lead.request_meta["intake"])
    assert intake["photo_urls_count"] == 2 and intake["photo_urls_accepted"] == 1
    assert intake["photo_urls_sample"][0] == good
    assert intake["urls_asked"] == 1 and intake["urls_fetched"] == 0
    assert intake["urls_report"] == [{"url": good, "result": "bad_response", "status": 404}]


def test_a_photo_link_of_the_new_site_outside_tmp_files_is_accepted_if_it_is_an_image() -> None:
    from app.services.leads_service import photo_urls_to_archive

    payload = {
        "photo_urls": [
            "https://panmotors77.ru/tmp/upload_x99Evh.jpg",  # так шлёт panmotors77.ru
            "https://panmotors77.ru/tmp/upload_x99Evh.php",  # не картинка
            "http://panmotors77.ru/tmp/a.jpg",  # не https
            "https://10.0.0.5/tmp/a.jpg",  # IP-адрес
        ]
    }
    assert photo_urls_to_archive(payload) == ["https://panmotors77.ru/tmp/upload_x99Evh.jpg"]


def test_the_new_sites_photo_links_are_downloaded_before_answering_not_in_the_background(
    client, db_session, auth_headers, monkeypatch
) -> None:
    """panmotors77.ru удаляет временный файл сразу после обработки заявки: ссылку скачиваем до
    ответа (фоновая загрузка получала 404)."""
    from app.services import leads_service
    from app.services.telephony_settings_service import get_telephony_settings

    _enable_intake(db_session)
    get_telephony_settings(db_session).yandex_disk_token = "a-disk-token"
    db_session.commit()
    url = "https://panmotors77.ru/tmp/upload_x99Evh.jpg"
    _fake_site_and_disk(monkeypatch, {url: b"jpeg-bytes"})
    background: list = []
    monkeypatch.setattr(
        leads_service, "archive_lead_photos_from_urls", lambda *args: background.append(args)
    )

    response = client.post(
        INTAKE_URL,
        json={"user_phone": "+7 (900) 000-11-22", "photo_urls": [url]},
        headers={"Authorization": "Bearer test-intake-token"},
    )

    assert response.status_code == 201
    assert background == []  # фоновой загрузки нет
    lead_id = response.json()["id"]
    # Загрузка на Диск идёт отдельным потоком уже после ответа: ждём, пока фото появятся.
    for _ in range(100):
        lead = client.get(LEADS_URL, headers=auth_headers).json()["leads"][0]
        if lead["photos"]:
            break
        time.sleep(0.05)
    assert lead["photos"] == [f"/api/leads/{lead_id}/photos/upload_x99Evh.jpg"]
    intake = json.loads(lead["request_meta"]["intake"])
    # Скачано до ответа, на Диск загружено после ответа (в фоне), время каждого шага - в диагностике.
    assert intake["urls_mode"] == "fetch_before_answer_upload_after"
    assert intake["urls_fetched"] == 1 and intake["urls_archived"] == 1
    assert "fetch_ms" in intake and "upload_ms" in intake


def test_all_photo_links_up_to_the_limit_are_fetched_before_answering() -> None:
    from app.services.leads_service import MAX_PHOTO_URLS, site_photo_urls_to_fetch_now

    urls = [f"https://panmotors77.ru/tmp/upload_{n}.jpg" for n in range(12)]
    assert site_photo_urls_to_fetch_now({"photo_urls": urls}) == urls[:MAX_PHOTO_URLS]
    assert MAX_PHOTO_URLS >= 8  # восемь фото от посетителя не теряются
