"""Тесты API. Запускаются, если установлены fastapi, sqlalchemy и httpx."""
import io
import os
import tempfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("httpx")

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = "sqlite:///%s/test.db" % _tmp
os.environ["MEDIA_DIR"] = os.path.join(_tmp, "media")
os.environ["DRONE_API_KEY"] = "test-drone-key"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

DRONE = {"X-API-Key": "test-drone-key"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:      # with -> выполняется lifespan (создание таблиц и пользователей)
        yield c


def login(client, username, password):
    r = client.post("/api/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture(scope="module")
def oper(client):
    return login(client, "operator", "operator123")


@pytest.fixture(scope="module")
def fire(client):
    return login(client, "fire", "fire123")


@pytest.fixture(scope="module")
def eco(client):
    return login(client, "eco", "eco123")


@pytest.fixture(scope="module")
def mission_id(client):
    oper = login(client, "operator", "operator123")   # список дронов виден только по JWT
    drones = client.get("/api/drones", headers=oper).json()
    assert drones, "дрон по умолчанию должен создаваться при запуске"
    r = client.post("/api/missions", json={"drone_id": drones[0]["id"]}, headers=DRONE)
    assert r.status_code == 201
    return r.json()["id"]


# ---------------------------------------------------------------- вход и роли
def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_login_and_me(client, oper):
    me = client.get("/api/me", headers=oper).json()
    assert me["role"] == "operator" and me["allowed_types"] is None
    bad = client.post("/api/login", json={"username": "operator", "password": "неверный"})
    assert bad.status_code == 401


def test_login_per_role_visibility(client):
    fire = login(client, "fire", "fire123")
    eco = login(client, "eco", "eco123")
    assert client.get("/api/me", headers=fire).json()["allowed_types"] == ["fire", "flood", "landslide"]
    assert client.get("/api/me", headers=eco).json()["allowed_types"] == ["pollution"]


def test_drone_key_required(client, mission_id):
    r = client.post("/api/telemetry", json={"mission_id": mission_id, "x": 1, "y": 2, "z": 8})
    assert r.status_code == 401
    r2 = client.post("/api/telemetry", json={"mission_id": mission_id, "x": 1, "y": 2, "z": 8},
                     headers={"X-API-Key": "wrong-key"})
    assert r2.status_code == 401


def test_panel_requires_token(client):
    assert client.get("/api/incidents").status_code == 401


# ---------------------------------------------------------------- телеметрия
def test_telemetry_and_position(client, mission_id):
    r = client.post("/api/telemetry", json={"mission_id": mission_id, "x": 1.0, "y": 2.0, "z": 8.0,
                                            "battery": 97.5, "state": "patrol"}, headers=DRONE)
    assert r.status_code == 201
    body = r.json()
    assert body["time"].endswith("+00:00")
    assert "lat" in body and "lon" in body
    oper = login(client, "operator", "operator123")
    drone_id = client.get("/api/drones", headers=oper).json()[0]["id"]
    pos = client.get("/api/drones/%d/position" % drone_id, headers=oper).json()
    assert pos["x"] == 1.0
    assert len(client.get("/api/missions/%d/track" % mission_id, headers=oper).json()) >= 1


# ---------------------------------------------------------------- ЧС
def test_incident_create_and_merge(client, mission_id):
    data = {"mission_id": mission_id, "type": "пожар", "severity": "низкая", "x": 8.0, "y": 5.0,
            "area_pct": 2.0, "people_count": 1}
    r1 = client.post("/api/incidents", data=data, headers=DRONE)
    assert r1.status_code == 201
    first = r1.json()
    assert first["type"] == "fire" and first["severity"] == "low" and first["merged"] is False
    assert first["people_count"] == 1

    # тот же очаг с соседнего кадра: бо́льшая площадь/степень/люди -> обновление, не дубль
    data2 = dict(data, x=8.5, y=5.5, area_pct=9.0, severity="medium", people_count=3)
    r2 = client.post("/api/incidents", data=data2, headers=DRONE)
    assert r2.status_code == 200
    merged = r2.json()
    assert merged["merged"] is True and merged["id"] == first["id"]
    assert merged["detections"] == 2 and merged["severity"] == "medium"
    assert merged["area_pct"] == 9.0 and merged["people_count"] == 3

    # далёкий очаг -> новая запись
    r3 = client.post("/api/incidents", data=dict(data, x=0.0, y=0.0), headers=DRONE)
    assert r3.status_code == 201 and r3.json()["id"] != first["id"]


def test_incident_with_image_subtype_and_filters(client, mission_id, oper):
    png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    r = client.post(
        "/api/incidents",
        data={"mission_id": mission_id, "type": "pollution", "severity": "high", "x": 3.0, "y": 4.0,
              "area_pct": 30, "subtype": "утечка топлива"},
        files={"image": ("frame.png", io.BytesIO(png), "image/png")},
        headers=DRONE,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["subtype"] == "утечка топлива"
    url = body["image_url"]
    assert url.startswith("/media/incidents/")
    assert client.get(url).status_code == 200

    only_pollution = client.get("/api/incidents", params={"type": "pollution"}, headers=oper).json()
    assert only_pollution and all(i["type"] == "pollution" for i in only_pollution)
    by_sev = client.get("/api/incidents", params={"severity": "high"}, headers=oper).json()
    assert by_sev and all(i["severity"] == "high" for i in by_sev)


def test_new_types_accepted(client, mission_id, oper):
    for t in ("landslide", "оползень", "flood", "утечка"):
        r = client.post("/api/incidents",
                        data={"mission_id": mission_id, "type": t, "severity": "low",
                              "x": 5.0, "y": 5.0, "area_pct": 1}, headers=DRONE)
        assert r.status_code in (200, 201), t


def test_validation_errors(client, mission_id):
    bad = client.post("/api/incidents", data={"mission_id": mission_id, "type": "метеорит",
                                              "severity": "low", "x": 0, "y": 0}, headers=DRONE)
    assert bad.status_code == 422
    nomission = client.post("/api/incidents", data={"mission_id": 9999, "type": "fire",
                                                    "severity": "low", "x": 0, "y": 0}, headers=DRONE)
    assert nomission.status_code == 404


# ---------------------------------------------------------------- разграничение ролей
def test_role_sees_only_allowed_types(client, mission_id, fire, eco):
    fires = client.get("/api/incidents", headers=fire).json()
    assert fires, "пожарному должны быть видны ЧС из сцены"
    assert all(i["type"] in ("fire", "flood", "landslide") for i in fires)
    # прямой запрос чужого типа -> 403
    pol = client.get("/api/incidents", params={"type": "pollution"}, headers=fire)
    assert pol.status_code == 403
    # эколог видит только загрязнения
    ecos = client.get("/api/incidents", headers=eco).json()
    assert all(i["type"] == "pollution" for i in ecos)


def test_stats_respect_role(client, fire):
    stats = client.get("/api/stats", headers=fire).json()
    assert set(stats["by_type"]).issubset({"fire", "flood", "landslide"})


def test_patch_operator_only(client, oper, fire):
    inc = client.get("/api/incidents", headers=oper).json()[0]
    r = client.patch("/api/incidents/%d" % inc["id"], json={"status": "confirmed", "note": "проверено"},
                     headers=oper)
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert client.patch("/api/incidents/%d" % inc["id"], json={"status": "ой"}, headers=oper).status_code == 422
    # пожарный менять статус не может
    denied = client.patch("/api/incidents/%d" % inc["id"], json={"status": "closed"}, headers=fire)
    assert denied.status_code == 403
