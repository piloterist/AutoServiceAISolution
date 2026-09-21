"""Tests for the per-user auth layer and the Settings admin-only tables
(Пользователи, Подразделения, Цеха, Статусы слесарки, аудит-лог)."""

AUTH_LOGIN_URL = "/api/v1/auth/login"
DEPARTMENTS_URL = "/api/v1/settings/departments"
WORKSHOPS_URL = "/api/v1/settings/workshops"
USERS_URL = "/api/v1/settings/users"
STATUSES_URL = "/api/v1/settings/slesarka-statuses"
AUDIT_LOG_URL = "/api/v1/settings/audit-log"


def _create_department(client, auth_headers, name="Каховка") -> str:
    response = client.post(DEPARTMENTS_URL, headers=auth_headers, json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def _create_user(client, auth_headers, **overrides) -> dict:
    payload = {
        "full_name": "Тестовый Пользователь",
        "login": "testuser",
        "password": "secret1",
        "role": "Сотрудник",
        "department_id": None,
        "workshop_id": None,
    }
    payload.update(overrides)
    response = client.post(USERS_URL, headers=auth_headers, json=payload)
    return response


# ---- auth -----------------------------------------------------------------


def test_login_requires_bearer_token(client) -> None:
    response = client.post(AUTH_LOGIN_URL, json={"login": "x", "password": "y"})
    assert response.status_code == 401


def test_login_succeeds_for_correct_credentials(client, auth_headers) -> None:
    _create_user(client, auth_headers, login="ivanov", password="secret1", role="Сотрудник")

    response = client.post(
        AUTH_LOGIN_URL, headers=auth_headers, json={"login": "ivanov", "password": "secret1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["login"] == "ivanov"
    assert body["role"] == "Сотрудник"
    assert "password" not in body


def test_login_rejects_wrong_password(client, auth_headers) -> None:
    _create_user(client, auth_headers, login="ivanov", password="secret1")

    response = client.post(
        AUTH_LOGIN_URL, headers=auth_headers, json={"login": "ivanov", "password": "wrong"}
    )
    assert response.status_code == 401


def test_login_rejects_unknown_login(client, auth_headers) -> None:
    response = client.post(
        AUTH_LOGIN_URL, headers=auth_headers, json={"login": "nobody", "password": "whatever"}
    )
    assert response.status_code == 401


# ---- Подразделения ----------------------------------------------------


def test_departments_crud(client, auth_headers) -> None:
    dept_id = _create_department(client, auth_headers, "Каховка")

    listed = client.get(DEPARTMENTS_URL, headers=auth_headers).json()
    assert [d["name"] for d in listed] == ["Каховка"]

    updated = client.put(
        f"{DEPARTMENTS_URL}/{dept_id}", headers=auth_headers, json={"name": "Солнцево"}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Солнцево"

    deleted = client.delete(f"{DEPARTMENTS_URL}/{dept_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert client.get(DEPARTMENTS_URL, headers=auth_headers).json() == []


def test_update_missing_department_404s(client, auth_headers) -> None:
    response = client.put(
        f"{DEPARTMENTS_URL}/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
        json={"name": "X"},
    )
    assert response.status_code == 404


# ---- Цеха ---------------------------------------------------------------


def test_workshop_crud(client, auth_headers) -> None:
    dept_id = _create_department(client, auth_headers)

    created = client.post(
        WORKSHOPS_URL,
        headers=auth_headers,
        json={
            "department_id": dept_id,
            "workshop_type": "Слесарный",
            "posts_count": 5,
            "is_default": True,
            "start_time": "07:00:00",
            "end_time": "22:00:00",
            "working_days": [0, 1, 2, 3, 4, 5],
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["department_name"] == "Каховка"
    assert body["posts_count"] == 5
    assert body["working_days"] == [0, 1, 2, 3, 4, 5]

    workshop_id = body["id"]
    updated = client.put(
        f"{WORKSHOPS_URL}/{workshop_id}",
        headers=auth_headers,
        json={
            "department_id": dept_id,
            "workshop_type": "Слесарный",
            "posts_count": 6,
            "is_default": True,
            "start_time": "08:00:00",
            "end_time": "20:00:00",
            "working_days": [0, 1, 2, 3, 4],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["posts_count"] == 6

    deleted = client.delete(f"{WORKSHOPS_URL}/{workshop_id}", headers=auth_headers)
    assert deleted.status_code == 204


def test_workshop_rejects_unknown_type(client, auth_headers) -> None:
    dept_id = _create_department(client, auth_headers)

    response = client.post(
        WORKSHOPS_URL,
        headers=auth_headers,
        json={
            "department_id": dept_id,
            "workshop_type": "Малярный",
            "posts_count": 5,
            "start_time": "07:00:00",
            "end_time": "22:00:00",
            "working_days": [0],
        },
    )
    assert response.status_code == 422


# ---- Пользователи ---------------------------------------------------------


def test_user_crud(client, auth_headers) -> None:
    dept_id = _create_department(client, auth_headers)

    created = _create_user(
        client, auth_headers, login="petrov", role="Мастер приёмщик", department_id=dept_id
    )
    assert created.status_code == 201
    body = created.json()
    assert body["login"] == "petrov"
    assert body["department_name"] == "Каховка"
    assert "password" not in body and "password_hash" not in body

    user_id = body["id"]
    updated = client.put(
        f"{USERS_URL}/{user_id}",
        headers=auth_headers,
        json={
            "full_name": "Петров П.П.",
            "login": "petrov",
            "role": "Управляющий",
            "department_id": None,
            "workshop_id": None,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["role"] == "Управляющий"
    assert updated.json()["department_id"] is None

    # Password unset on update keeps the old one working.
    login_after_update = client.post(
        AUTH_LOGIN_URL, headers=auth_headers, json={"login": "petrov", "password": "secret1"}
    )
    assert login_after_update.status_code == 200

    deleted = client.delete(f"{USERS_URL}/{user_id}", headers=auth_headers)
    assert deleted.status_code == 204


def test_user_create_rejects_duplicate_login(client, auth_headers) -> None:
    first = _create_user(client, auth_headers, login="dup")
    assert first.status_code == 201

    second = _create_user(client, auth_headers, login="dup")
    assert second.status_code == 409


def test_user_create_rejects_unknown_role(client, auth_headers) -> None:
    response = _create_user(client, auth_headers, role="Директор")
    assert response.status_code == 422


# ---- Статусы слесарки ------------------------------------------------


def test_slesarka_status_crud(client, auth_headers) -> None:
    created = client.post(
        STATUSES_URL, headers=auth_headers, json={"name": "Запись", "color": "#5b6b82"}
    )
    assert created.status_code == 201
    status_id = created.json()["id"]

    updated = client.put(
        f"{STATUSES_URL}/{status_id}",
        headers=auth_headers,
        json={"name": "Запись", "color": "#ff0000"},
    )
    assert updated.status_code == 200
    assert updated.json()["color"] == "#ff0000"

    deleted = client.delete(f"{STATUSES_URL}/{status_id}", headers=auth_headers)
    assert deleted.status_code == 204


def test_slesarka_status_rejects_bad_color(client, auth_headers) -> None:
    response = client.post(
        STATUSES_URL, headers=auth_headers, json={"name": "Готова", "color": "red"}
    )
    assert response.status_code == 422


# ---- Аудит-лог -------------------------------------------------------------


def test_audit_log_starts_empty(client, auth_headers) -> None:
    response = client.get(AUDIT_LOG_URL, headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []
