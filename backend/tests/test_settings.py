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
    assert body["order_exclusion_mode"] == "none"
    assert body["hide_internal_orders"] is False
    assert body["warranty_repair_types"] == []
    assert body["fivesystems_api_enabled"] is False
    assert body["daily_logout_time"] == "23:30"
    assert body["planner_search_exclude_closed_orders"] is False


def test_put_settings_persists_values(client, auth_headers) -> None:
    response = client.put(
        SETTINGS_URL,
        headers=auth_headers,
        json={
            "insurance_repair_type": "Гарантийный ремонт",
            "exclude_internal_insurance": True,
            "order_exclusion_mode": "internal",
            "hide_internal_orders": True,
            "fivesystems_api_enabled": True,
            "daily_logout_time": "22:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["insurance_repair_type"] == "Гарантийный ремонт"
    assert body["exclude_internal_insurance"] is True
    assert body["order_exclusion_mode"] == "internal"
    assert body["hide_internal_orders"] is True
    assert body["fivesystems_api_enabled"] is True
    assert body["daily_logout_time"] == "22:00"

    # A later GET reflects the saved values, not fresh defaults.
    follow_up = client.get(SETTINGS_URL, headers=auth_headers)
    assert follow_up.json() == body


def test_put_settings_rejects_malformed_daily_logout_time(client, auth_headers) -> None:
    response = client.put(SETTINGS_URL, headers=auth_headers, json={"daily_logout_time": "25:99"})
    assert response.status_code == 422


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


def test_put_settings_persists_warranty_repair_types(client, auth_headers) -> None:
    response = client.put(
        SETTINGS_URL,
        headers=auth_headers,
        json={"warranty_repair_types": ["Гарантийный ремонт", "Гарантия производителя"]},
    )

    assert response.status_code == 200
    assert response.json()["warranty_repair_types"] == [
        "Гарантийный ремонт",
        "Гарантия производителя",
    ]

    follow_up = client.get(SETTINGS_URL, headers=auth_headers)
    assert follow_up.json()["warranty_repair_types"] == [
        "Гарантийный ремонт",
        "Гарантия производителя",
    ]


def test_put_settings_can_clear_warranty_repair_types(client, auth_headers) -> None:
    client.put(
        SETTINGS_URL, headers=auth_headers, json={"warranty_repair_types": ["Гарантийный ремонт"]}
    )

    response = client.put(SETTINGS_URL, headers=auth_headers, json={"warranty_repair_types": []})

    assert response.status_code == 200
    assert response.json()["warranty_repair_types"] == []


def test_put_settings_pm_fields_are_independent_of_the_insurance_fields(
    client, auth_headers
) -> None:
    """ "Специфика PanMotors" (order_exclusion_mode/hide_internal_orders)
    is a separate feature from the older insurance_repair_type/
    exclude_internal_insurance pair - saving one must not touch the other."""
    client.put(
        SETTINGS_URL,
        headers=auth_headers,
        json={
            "insurance_repair_type": "Гарантийный ремонт",
            "exclude_internal_insurance": True,
            "order_exclusion_mode": "none",
            "hide_internal_orders": False,
        },
    )

    response = client.put(
        SETTINGS_URL,
        headers=auth_headers,
        json={
            "insurance_repair_type": "Гарантийный ремонт",
            "exclude_internal_insurance": True,
            "order_exclusion_mode": "internal",
            "hide_internal_orders": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["insurance_repair_type"] == "Гарантийный ремонт"
    assert body["exclude_internal_insurance"] is True
    assert body["order_exclusion_mode"] == "internal"
    assert body["hide_internal_orders"] is True


def test_put_settings_persists_virtual_repair_types(client, auth_headers) -> None:
    response = client.put(
        SETTINGS_URL,
        headers=auth_headers,
        json={"virtual_repair_types": ["Виртуальный", "Тест"]},
    )

    assert response.status_code == 200
    assert response.json()["virtual_repair_types"] == ["Виртуальный", "Тест"]
    assert client.get(SETTINGS_URL, headers=auth_headers).json()["virtual_repair_types"] == [
        "Виртуальный",
        "Тест",
    ]


def test_order_exclusion_mode_accepts_only_the_three_values(client, auth_headers) -> None:
    for mode in ("none", "internal", "external"):
        response = client.put(
            SETTINGS_URL, headers=auth_headers, json={"order_exclusion_mode": mode}
        )
        assert response.status_code == 200
        assert response.json()["order_exclusion_mode"] == mode
        assert client.get(SETTINGS_URL, headers=auth_headers).json()["order_exclusion_mode"] == mode

    bad = client.put(SETTINGS_URL, headers=auth_headers, json={"order_exclusion_mode": "all"})
    assert bad.status_code == 422
