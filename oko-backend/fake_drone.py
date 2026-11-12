"""Имитация дрона: отправляет на сервер настоящий поток данных, как будет делать Webots.

Нужна, чтобы проверять сервер и сайт без симулятора:
миссия -> телеметрия раз в 0.5 с -> находки с фото (многократно, как с соседних кадров) -> завершение.

Сцена соответствует демо-данным (app/seed.py): пожар, наводнение, загрязнение, оползень.
Люди не «пострадавшие», а «люди в зоне очага» (people_count): дрон считает всех,
кто оказался рядом, — среди них могут быть просто прохожие.

Запуск (сервер должен работать):
    python fake_drone.py
Параметры:
    --api http://localhost:8000   адрес сервера
    --speed 2                     во сколько раз быстрее лететь (по умолчанию 1)
    --loops 3                     сколько вылетов подряд (по умолчанию 1)
    --no-images                   не отправлять фото
    --drone-id 1                  номер дрона
    --api-key oko-drone-key       ключ дрона (тот же, что в DRONE_API_KEY на сервере)
Остановка: Ctrl+C (вылет аккуратно завершится).
"""
import argparse
import math
import os
import random
import sys
import time

import requests

ROUTE = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]   # как в сцене Webots
CRUISE_ALT = 8.0
CRUISE_SPEED = 2.0          # м/с
STEP = 0.5                  # секунд между отправками телеметрии
VIEW_RADIUS = 4.0           # на каком расстоянии дрон «видит» объект, м
SEND_EVERY = 1.0            # как часто «детектор» повторно сообщает об очаге, с

# что стоит в сцене: тип, где, максимальная площадь в кадре (%), люди в зоне, подтип, фото
# (пороги степени — те же, что в detect_emergency.py)
SCENE = [
    {"type": "fire",      "x": 8.0, "y": 5.0, "max_area": 11.0, "people": 2,
     "subtype": None,           "img": "fire.jpg"},
    {"type": "flood",     "x": 3.0, "y": 4.0, "max_area": 34.0, "people": 3,
     "subtype": None,           "img": "flood.jpg"},
    {"type": "pollution", "x": 2.0, "y": 8.5, "max_area": 8.0,  "people": 0,
     "subtype": "утечка топлива", "img": "pollution.jpg"},
    {"type": "landslide", "x": 9.0, "y": 1.5, "max_area": 6.0,  "people": 0,
     "subtype": None,           "img": "landslide.jpg"},
]
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_assets")


def severity_for(area):
    """Те же пороги, что в detect_emergency.py."""
    return "low" if area < 3 else "medium" if area < 12 else "high"


def route_length():
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(ROUTE, ROUTE[1:]))


def position_at(dist):
    """Точка маршрута на расстоянии dist от старта и курс (рад)."""
    for (x1, y1), (x2, y2) in zip(ROUTE, ROUTE[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        if dist <= seg:
            t = dist / seg
            return x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, math.atan2(y2 - y1, x2 - x1)
        dist -= seg
    x, y = ROUTE[-1]
    return x, y, math.pi


class Api:
    def __init__(self, base, api_key):
        self.base = base.rstrip("/") + "/api"
        self.headers = {"X-API-Key": api_key}   # дрон аутентифицируется ключом

    def post(self, path, **kw):
        r = requests.post(self.base + path, timeout=5, headers=self.headers, **kw)
        r.raise_for_status()
        return r

    def mission_start(self, drone_id):
        return self.post("/missions", json={"drone_id": drone_id}).json()["id"]

    def mission_finish(self, mid):
        self.post("/missions/%d/finish" % mid)

    def telemetry(self, mid, x, y, z, yaw, battery, state):
        self.post("/telemetry", json={"mission_id": mid, "x": round(x, 3), "y": round(y, 3), "z": round(z, 2),
                                      "yaw": round(yaw, 3), "battery": round(battery, 1), "state": state})

    def incident(self, mid, kind, sev, x, y, area, people, subtype, image_path):
        data = {"mission_id": mid, "type": kind, "severity": sev, "x": round(x, 3), "y": round(y, 3),
                "area_pct": round(area, 2), "people_count": people}
        if subtype:
            data["subtype"] = subtype
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                return self.post("/incidents", data=data,
                                 files={"image": (os.path.basename(image_path), f, "image/jpeg")})
        return self.post("/incidents", data=data)


def fly(api, drone_id, speed, images):
    mid = api.mission_start(drone_id)
    print("== Вылет №%d начат" % mid)
    last_sent = {}
    sent = merged = 0
    total = route_length()
    dist = 0.0
    t0 = time.time()
    try:
        # --- взлёт (3 с моделируемого времени)
        for i in range(int(3 / STEP) + 1):
            z = CRUISE_ALT * i / int(3 / STEP)
            api.telemetry(mid, 0, 0, max(z, 0.1), 0.0, 100.0, "takeoff")
            time.sleep(STEP / speed)
        print("   взлёт завершён, лечу по маршруту")

        # --- патруль
        while dist < total:
            x, y, yaw = position_at(dist)
            battery = 100 - 12 * dist / total
            api.telemetry(mid, x, y, CRUISE_ALT, yaw, battery, "patrol")

            now = time.time()
            for obj in SCENE:
                d = math.hypot(obj["x"] - x, obj["y"] - y)
                if d > VIEW_RADIUS or now - last_sent.get(obj["type"], 0) < SEND_EVERY / speed:
                    continue
                last_sent[obj["type"]] = now
                # «детектор» ошибается в положении на ~0.4 м, а площадь зависит от расстояния;
                # людей в кадре считает с погрешностью ±1 (часть уходит, часть приходит)
                area = obj["max_area"] * (1 - d / (VIEW_RADIUS * 1.3)) * random.uniform(0.85, 1.0)
                ex = obj["x"] + random.uniform(-0.4, 0.4)
                ey = obj["y"] + random.uniform(-0.4, 0.4)
                sev = severity_for(area)
                people = max(0, obj["people"] + random.choice((-1, 0, 0, 1))) if obj["people"] else 0
                r = api.incident(mid, obj["type"], sev, ex, ey, area, people, obj["subtype"],
                                 os.path.join(ASSETS, obj["img"]) if images else None)
                body = r.json()
                sent += 1
                merged += 1 if body["merged"] else 0
                print("   %-9s %-6s площадь %5.1f%%  людей в зоне: %d  -> №%d (%s, кадров: %d)" % (
                    obj["type"], sev, area, people, body["id"],
                    "обновлена" if body["merged"] else "НОВАЯ", body["detections"]))

            dist += CRUISE_SPEED * STEP
            time.sleep(STEP / speed)

        # --- посадка
        for i in range(int(2 / STEP) + 1):
            z = CRUISE_ALT * (1 - i / int(2 / STEP))
            api.telemetry(mid, 0, 0, max(z, 0.1), math.pi, 88.0, "land")
            time.sleep(STEP / speed)
    finally:
        api.mission_finish(mid)
        print("== Вылет №%d завершён: отправлено сообщений о ЧС %d, из них обновили уже известные %d (%.0f с)"
              % (mid, sent, merged, time.time() - t0))


def main():
    ap = argparse.ArgumentParser(description="Имитация дрона для проверки сервера и сайта")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--loops", type=int, default=1)
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--drone-id", type=int, default=1)
    ap.add_argument("--api-key", default=os.getenv("DRONE_API_KEY", "oko-drone-key"))
    a = ap.parse_args()

    api = Api(a.api, a.api_key)
    try:
        requests.get(a.api.rstrip("/") + "/api/health", timeout=3).raise_for_status()
    except Exception as e:
        print("Сервер недоступен по адресу %s: %s\nЗапустите: uvicorn app.main:app --reload" % (a.api, e))
        sys.exit(1)

    try:
        for n in range(a.loops):
            fly(api, a.drone_id, max(a.speed, 0.1), images=not a.no_images)
            if n < a.loops - 1:
                time.sleep(2)
    except KeyboardInterrupt:
        print("\nОстановлено пользователем")
    except requests.HTTPError as e:
        print("Сервер вернул ошибку:", e, getattr(e.response, "text", ""))
        sys.exit(2)


if __name__ == "__main__":
    main()
