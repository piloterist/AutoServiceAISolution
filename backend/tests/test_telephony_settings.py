"""Tests for Settings -> IP-телефония: the connection-settings singleton
and the phone-source directory (see app/api/v1/endpoints/telephony.py)."""

SETTINGS_URL = "/api/v1/telephony/settings"
SOURCES_URL = "/api/v1/telephony/sources"
PING_URL = "/api/v1/telephony/ping"


def test_read_settings_creates_defaults_on_first_access(client, auth_headers) -> None:
    response = client.get(SETTINGS_URL, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "zeon"
    assert body["enabled"] is False
    assert body["zeon_auth"] == "bearer"


def test_write_settings_persists_fields(client, auth_headers) -> None:
    payload = {
        "enabled": True,
        "zeon_api_url": "https://z138.fpg.ru/zeon/api/v2/start.php",
        "zeon_api_key": "secret-key",
        "zeon_auth": "bearer",
        "operator_names": "302:Алексей,303:Мария",
        "poll_interval_minutes": 5,
    }
    response = client.put(SETTINGS_URL, headers=auth_headers, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["zeon_api_url"] == payload["zeon_api_url"]
    assert body["poll_interval_minutes"] == 5

    refetched = client.get(SETTINGS_URL, headers=auth_headers).json()
    assert refetched["operator_names"] == "302:Алексей,303:Мария"


def test_write_settings_rejects_unknown_auth_mode(client, auth_headers) -> None:
    response = client.put(SETTINGS_URL, headers=auth_headers, json={"zeon_auth": "basic"})
    assert response.status_code == 422


def test_write_settings_persists_classify_calls_fields(client, auth_headers) -> None:
    """Call-topic classification (YandexGPT, product ask 2026-10-02) - off
    by default, and the model is editable without a redeploy (same
    pattern as speechkit_model)."""
    response = client.get(SETTINGS_URL, headers=auth_headers)
    assert response.json()["classify_calls_enabled"] is False
    assert response.json()["yandexgpt_model"] == "yandexgpt-lite/latest"

    response = client.put(
        SETTINGS_URL,
        headers=auth_headers,
        json={"classify_calls_enabled": True, "yandexgpt_model": "yandexgpt/latest"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["classify_calls_enabled"] is True
    assert body["yandexgpt_model"] == "yandexgpt/latest"


def test_ping_fails_gracefully_when_unconfigured(client, auth_headers) -> None:
    response = client.post(PING_URL, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]


def _create_source(client, auth_headers, **overrides) -> dict:
    payload = {
        "line_code": "pan",
        "name": "2GIS",
        "caption": None,
        "group_name": "Карты и каталоги",
        "sort_order": 1,
    }
    payload.update(overrides)
    return client.post(SOURCES_URL, headers=auth_headers, json=payload)


def test_create_and_list_phone_source(client, auth_headers) -> None:
    response = _create_source(client, auth_headers)
    assert response.status_code == 201
    source_id = response.json()["id"]

    listed = client.get(SOURCES_URL, headers=auth_headers).json()
    assert len(listed) == 1
    assert listed[0]["id"] == source_id
    assert listed[0]["line_code"] == "pan"


def test_create_phone_source_rejects_unknown_group(client, auth_headers) -> None:
    response = _create_source(client, auth_headers, group_name="Where")
    assert response.status_code == 422


def test_create_phone_source_rejects_duplicate_line_code(client, auth_headers) -> None:
    first = _create_source(client, auth_headers)
    assert first.status_code == 201

    second = _create_source(client, auth_headers, name="Yandex Maps")
    assert second.status_code == 409


def test_update_phone_source(client, auth_headers) -> None:
    source_id = _create_source(client, auth_headers).json()["id"]

    response = client.put(
        f"{SOURCES_URL}/{source_id}",
        headers=auth_headers,
        json={
            "line_code": "pan2",
            "name": "Yandex Maps",
            "caption": "IVR Yamaps",
            "group_name": "Прямые номера",
            "sort_order": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["line_code"] == "pan2"
    assert body["caption"] == "IVR Yamaps"


def test_update_missing_phone_source_returns_404(client, auth_headers) -> None:
    response = client.put(
        f"{SOURCES_URL}/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
        json={
            "line_code": "x",
            "name": "x",
            "caption": None,
            "group_name": "Прочие",
            "sort_order": 0,
        },
    )
    assert response.status_code == 404


def test_delete_phone_source(client, auth_headers) -> None:
    source_id = _create_source(client, auth_headers).json()["id"]

    response = client.delete(f"{SOURCES_URL}/{source_id}", headers=auth_headers)
    assert response.status_code == 204

    listed = client.get(SOURCES_URL, headers=auth_headers).json()
    assert listed == []
