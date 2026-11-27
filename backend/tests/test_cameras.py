import pytest
from fastapi.testclient import TestClient

from app.services.camera_service import normalize_mac

URL = "/api/v1/cameras"


@pytest.mark.parametrize(
    "raw",
    ["9ca2f4da22ea", "9c:a2:f4:da:22:ea", "9C-A2-F4-DA-22-EA", " 9ca2.f4da.22ea "],
)
def test_normalize_mac_accepts_any_common_notation(raw: str) -> None:
    assert normalize_mac(raw) == "9C-A2-F4-DA-22-EA"


def test_normalize_mac_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        normalize_mac("9C-A2-F4")


def test_cameras_require_auth(client: TestClient) -> None:
    assert client.get(URL).status_code == 401


def test_camera_directory_crud(client: TestClient, auth_headers: dict) -> None:
    created = client.post(
        URL,
        headers=auth_headers,
        json={"code": "cam1", "mac": "9ca2f4da22ea", "model": "VIGI C440", "name": "Бокс 1"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["mac"] == "9C-A2-F4-DA-22-EA"
    assert body["ip"] is None

    # the same MAC or code again: conflict
    for payload in (
        {"code": "cam2", "mac": "9C:A2:F4:DA:22:EA"},
        {"code": "cam1", "mac": "3C7895D6C70E"},
    ):
        assert client.post(URL, headers=auth_headers, json=payload).status_code == 409

    second = client.post(URL, headers=auth_headers, json={"code": "cam2", "mac": "3C7895D6C70E"})
    assert second.status_code == 201

    listed = client.get(URL, headers=auth_headers).json()
    assert [c["code"] for c in listed] == ["cam1", "cam2"]

    updated = client.put(
        f"{URL}/{body['id']}",
        headers=auth_headers,
        json={"code": "cam1", "mac": "9C-A2-F4-DA-22-EA", "note": "Каховка, слесарный"},
    )
    assert updated.status_code == 200 and updated.json()["note"] == "Каховка, слесарный"

    assert client.delete(f"{URL}/{second.json()['id']}", headers=auth_headers).status_code == 204
    assert client.delete(f"{URL}/{second.json()['id']}", headers=auth_headers).status_code == 404


def test_bad_mac_is_rejected(client: TestClient, auth_headers: dict) -> None:
    response = client.post(URL, headers=auth_headers, json={"code": "cam1", "mac": "nonsense"})
    assert response.status_code == 422


def test_reported_ip_lands_in_the_directory(client: TestClient, auth_headers: dict) -> None:
    client.post(URL, headers=auth_headers, json={"code": "cam1", "mac": "9ca2f4da22ea"})
    # the node's own signal (camera_status) is separate from the reported IP
    client.post(
        "/api/v1/bays/heartbeat",
        headers=auth_headers,
        json={"camera_code": "cam1", "camera_ok": True},
    )

    response = client.post(
        f"{URL}/report-ip", headers=auth_headers, json={"code": "cam1", "ip": "192.168.0.223"}
    )
    assert response.status_code == 204

    camera = client.get(URL, headers=auth_headers).json()[0]
    assert camera["ip"] == "192.168.0.223"
    assert camera["ip_seen_at"] is not None
    assert camera["camera_ok"] is True and camera["node_seen_at"] is not None

    # an unknown code is ignored, not an error (the camera may not be in the directory yet)
    unknown = client.post(
        f"{URL}/report-ip", headers=auth_headers, json={"code": "nope", "ip": "192.168.0.9"}
    )
    assert unknown.status_code == 204


def test_camera_mode_defaults_to_bay_and_can_be_a_gate(
    client: TestClient, auth_headers: dict
) -> None:
    bay = client.post(URL, headers=auth_headers, json={"code": "cam1", "mac": "9ca2f4da22ea"})
    assert bay.json()["mode"] == "bay"

    gate = client.post(
        URL, headers=auth_headers, json={"code": "gate1", "mac": "3C7895D6C70E", "mode": "gate"}
    )
    assert gate.status_code == 201 and gate.json()["mode"] == "gate"

    bad = client.post(
        URL, headers=auth_headers, json={"code": "x", "mac": "AABBCCDDEEFF", "mode": "garage"}
    )
    assert bad.status_code == 422

    changed = client.put(
        f"{URL}/{bay.json()['id']}",
        headers=auth_headers,
        json={"code": "cam1", "mac": "9C-A2-F4-DA-22-EA", "mode": "gate"},
    )
    assert changed.json()["mode"] == "gate"
