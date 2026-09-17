SETTINGS_URL = "/api/v1/settings"


def test_get_settings_requires_auth(client) -> None:
    response = client.get(SETTINGS_URL)
    assert response.status_code == 401


def test_get_settings_returns_defaults_on_first_access(client, auth_headers) -> None:
    response = client.get(SETTINGS_URL, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["insurance_repair_type"] is None
    assert body["exclude_internal_insurance"] is False


def test_put_settings_persists_values(client, auth_headers) -> None:
    response = client.put(
        SETTINGS_URL,
        headers=auth_headers,
        json={"insurance_repair_type": "Гарантийный ремонт", "exclude_internal_insurance": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["insurance_repair_type"] == "Гарантийный ремонт"
    assert body["exclude_internal_insurance"] is True

    # A later GET reflects the saved values, not fresh defaults.
    follow_up = client.get(SETTINGS_URL, headers=auth_headers)
    assert follow_up.json() == body


def test_put_settings_can_clear_the_repair_type(client, auth_headers) -> None:
    client.put(
        SETTINGS_URL,
        headers=auth_headers,
        json={"insurance_repair_type": "Гарантийный ремонт", "exclude_internal_insurance": True},
    )

    response = client.put(
        SETTINGS_URL,
        headers=auth_headers,
        json={"insurance_repair_type": None, "exclude_internal_insurance": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["insurance_repair_type"] is None
    assert body["exclude_internal_insurance"] is False
