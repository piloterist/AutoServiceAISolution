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
    assert body["exclude_internal_orders"] is False
    assert body["hide_internal_orders"] is False


def test_put_settings_persists_values(client, auth_headers) -> None:
    response = client.put(
        SETTINGS_URL,
        headers=auth_headers,
        json={
            "insurance_repair_type": "Гарантийный ремонт",
            "exclude_internal_insurance": True,
            "exclude_internal_orders": True,
            "hide_internal_orders": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["insurance_repair_type"] == "Гарантийный ремонт"
    assert body["exclude_internal_insurance"] is True
    assert body["exclude_internal_orders"] is True
    assert body["hide_internal_orders"] is True

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


def test_put_settings_pm_fields_are_independent_of_the_insurance_fields(
    client, auth_headers
) -> None:
    """ "Специфика PanMotors" (exclude_internal_orders/hide_internal_orders)
    is a separate feature from the older insurance_repair_type/
    exclude_internal_insurance pair - saving one must not touch the other."""
    client.put(
        SETTINGS_URL,
        headers=auth_headers,
        json={
            "insurance_repair_type": "Гарантийный ремонт",
            "exclude_internal_insurance": True,
            "exclude_internal_orders": False,
            "hide_internal_orders": False,
        },
    )

    response = client.put(
        SETTINGS_URL,
        headers=auth_headers,
        json={
            "insurance_repair_type": "Гарантийный ремонт",
            "exclude_internal_insurance": True,
            "exclude_internal_orders": True,
            "hide_internal_orders": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["insurance_repair_type"] == "Гарантийный ремонт"
    assert body["exclude_internal_insurance"] is True
    assert body["exclude_internal_orders"] is True
    assert body["hide_internal_orders"] is True
