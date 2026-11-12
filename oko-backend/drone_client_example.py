"""Пример: как контроллер дрона в Webots отправляет данные на сервер.

Скопируйте функции в drone_patrol.py. Главное правило: запросы с короткими таймаутами
и в try/except, чтобы связь с сервером не останавливала полёт.

Дрон аутентифицируется ключом DRONE_API_KEY (заголовок X-API-Key) — сессий у дрона нет.
Типы ЧС: fire (пожар), flood (наводнение), pollution (загрязнение), landslide (оползень);
люди — это не отдельный тип, а поле people_count («людей в зоне очага»).
"""
import os

import requests

API = "http://localhost:8000/api"
HEADERS = {"X-API-Key": os.getenv("DRONE_API_KEY", "oko-drone-key")}


def start_mission(drone_id=1):
    try:
        r = requests.post(API + "/missions", json={"drone_id": drone_id},
                          headers=HEADERS, timeout=2)
        r.raise_for_status()
        return r.json()["id"]
    except Exception as e:
        print("Сервер недоступен:", e)
        return None


def send_telemetry(mission_id, x, y, z, yaw=None, battery=None, state=None):
    if mission_id is None:
        return
    try:
        requests.post(API + "/telemetry", headers=HEADERS, timeout=0.5, json={
            "mission_id": mission_id, "x": x, "y": y, "z": z,
            "yaw": yaw, "battery": battery, "state": state})
    except Exception:
        pass


def send_incident(mission_id, kind, severity, x, y, area_pct,
                  people_count=0, subtype=None, image_path=None):
    """kind: fire | flood | pollution | landslide (или по-русски);
    severity: low | medium | high (или по-русски);
    people_count — сколько людей в зоне очага (0, если никого)."""
    if mission_id is None:
        return
    data = {"mission_id": mission_id, "type": kind, "severity": severity,
            "x": x, "y": y, "area_pct": area_pct, "people_count": max(people_count, 0)}
    if subtype:
        data["subtype"] = subtype
    try:
        if image_path:
            with open(image_path, "rb") as f:
                requests.post(API + "/incidents", data=data,
                              files={"image": f}, headers=HEADERS, timeout=1.5)
        else:
            requests.post(API + "/incidents", data=data, headers=HEADERS, timeout=1.5)
    except Exception:
        pass


def finish_mission(mission_id):
    if mission_id is None:
        return
    try:
        requests.post("%s/missions/%d/finish" % (API, mission_id),
                      headers=HEADERS, timeout=2)
    except Exception:
        pass


# --- Использование в drone_patrol.py ---------------------------------------
# mission_id = start_mission()                       # один раз перед взлётом
# ... в цикле раз в секунду:
#     send_telemetry(mission_id, x, y, altitude, yaw=yaw, state=state)
# ... когда детектор нашёл ЧС (x, y - координаты дрона или пересчитанные координаты очага):
#     send_incident(mission_id, "fire", "medium", x, y, 9.6, people_count=2,
#                   image_path="frames/frame_0012.jpg")
#     send_incident(mission_id, "pollution", "low", x, y, 7.5,
#                   subtype="утечка топлива")
# ... после посадки:
#     finish_mission(mission_id)
