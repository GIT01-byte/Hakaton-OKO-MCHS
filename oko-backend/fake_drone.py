"""Имитация дрона: отправляет на сервер поток телеметрии и находки ЧС с фото.

Запуск:
    python fake_drone.py
Параметры:
    --api http://localhost:8000   адрес сервера
    --speed 1.5                   ускорение полёта (1.0 = реальное время)
    --loops 2                     число кругов патрулирования
    --no-images                   не прикреплять фото (для ускорения)
"""
import argparse
import math
import os
import random
import sys
import time

import requests

# Маршрут патрулирования (квадрат охватывает основные секторы арены)
ROUTE = [
    (-6.0, -6.0),
    (14.0, -6.0),
    (14.0, 14.0),
    (-6.0, 14.0),
    (-6.0, -6.0),
]

CRUISE_ALT = 10.0           # крейсерская высота (м)
CRUISE_SPEED = 3.0          # скорость полета дрона (м/с)
STEP = 0.5                  # телеметрия каждые 0.5 с
VIEW_RADIUS = 5.5           # дальность обнаружения объектами (м)
SEND_EVERY = 1.0            # интервал между отправками по одному очагу (с)

# 4 типа ЧС (соответствуют новой цветовой схеме):
# fire (Красный), flood (Синий), pollution (Жёлтый), landslide (Серый)
SCENE = [
    {
        "type": "fire",
        "x": 10.0,
        "y": 4.0,
        "max_area": 16.0,       # площадь для радиуса
        "people": 2,
        "subtype": "очаг открытого огня",
        "img": "fire.jpg",
    },
    {
        "type": "flood",
        "x": 3.0,
        "y": 11.0,
        "max_area": 35.0,       # большая площадь для фиксации квадратом
        "people": 1,
        "subtype": "зона подтопления (обзор 90°)",
        "img": "flood.jpg",
    },
    {
        "type": "pollution",
        "x": -3.0,
        "y": 5.0,
        "max_area": 10.0,
        "people": 0,
        "subtype": "утечка ГСМ / свалка отходов",
        "img": "pollution.jpg",
    },
    {
        "type": "landslide",
        "x": 4.0,
        "y": -3.5,
        "max_area": 12.0,
        "people": 0,
        "subtype": "каменный завал / оползень",
        "img": "landslide.jpg",
    },
]

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_assets")


def severity_for(area: float) -> str:
    return "low" if area < 5 else "medium" if area < 15 else "high"


def route_length() -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(ROUTE, ROUTE[1:]))


def position_at(dist: float):
    """Возвращает координаты x, y и курсовой угол yaw (радианы)."""
    for (x1, y1), (x2, y2) in zip(ROUTE, ROUTE[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        if dist <= seg:
            t = dist / seg
            yaw = math.atan2(y2 - y1, x2 - x1)
            return x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, yaw
        dist -= seg
    x, y = ROUTE[-1]
    return x, y, 0.0


class Api:
    def __init__(self, base: str, api_key: str):
        self.base = base.rstrip("/") + "/api"
        self.headers = {"X-API-Key": api_key}

    def post(self, path: str, **kw):
        r = requests.post(self.base + path, timeout=4, headers=self.headers, **kw)
        r.raise_for_status()
        return r

    def mission_start(self, drone_id: int) -> int:
        return self.post("/missions", json={"drone_id": drone_id}).json()["id"]

    def mission_finish(self, mid: int):
        self.post(f"/missions/{mid}/finish")

    def telemetry(self, mid: int, x: float, y: float, z: float, yaw: float, battery: float, state: str):
        self.post("/telemetry", json={
            "mission_id": mid,
            "x": round(x, 3),
            "y": round(y, 3),
            "z": round(z, 2),
            "yaw": round(yaw, 3),
            "battery": round(battery, 1),
            "state": state
        })

    def incident(self, mid: int, kind: str, sev: str, x: float, y: float, area: float,
                 people: int, subtype: str, image_path: str = None):
        data = {
            "mission_id": mid,
            "type": kind,
            "severity": sev,
            "x": round(x, 3),
            "y": round(y, 3),
            "area_pct": round(area, 2),
            "people_count": people,
        }
        if subtype:
            data["subtype"] = subtype
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                return self.post("/incidents", data=data,
                                 files={"image": (os.path.basename(image_path), f, "image/jpeg")})
        return self.post("/incidents", data=data)


def fly(api: Api, drone_id: int, speed: float, images: bool):
    mid = api.mission_start(drone_id)
    print(f"\n==========================================")
    print(f"🚀 ВЫЛЕТ №{mid} НАЧАТ (Дрон ID: {drone_id})")
    print(f"==========================================")

    last_sent = {}
    sent = merged = 0
    total = route_length()
    dist = 0.0
    t0 = time.time()

    try:
        # 1. Взлёт
        takeoff_steps = max(1, int(2.5 / STEP))
        for i in range(takeoff_steps + 1):
            z = CRUISE_ALT * (i / takeoff_steps)
            api.telemetry(mid, ROUTE[0][0], ROUTE[0][1], max(z, 0.1), 0.0, 100.0, "takeoff")
            time.sleep(STEP / speed)
        print(" -> Взлёт выполнен, набор высоты 10м. Начало патрулирования...")

        # 2. Полёт по квадратному маршруту
        while dist < total:
            x, y, yaw = position_at(dist)
            battery = max(10.0, 100.0 - (20.0 * (dist / total)))
            api.telemetry(mid, x, y, CRUISE_ALT, yaw, battery, "patrol")

            now = time.time()
            for obj in SCENE:
                d = math.hypot(obj["x"] - x, obj["y"] - y)
                if d <= VIEW_RADIUS:
                    if now - last_sent.get(obj["type"], 0) >= (SEND_EVERY / speed):
                        last_sent[obj["type"]] = now
                        
                        # Расчет видимой площади в зависимости от дистанции
                        factor = max(0.4, 1.0 - (d / (VIEW_RADIUS * 1.2)))
                        area = obj["max_area"] * factor * random.uniform(0.9, 1.0)
                        sev = severity_for(area)
                        
                        # Небольшой шум сенсоров к координатам (±0.3м)
                        det_x = obj["x"] + random.uniform(-0.3, 0.3)
                        det_y = obj["y"] + random.uniform(-0.3, 0.3)
                        people = obj["people"]

                        img_file = os.path.join(ASSETS, obj["img"]) if images else None
                        r = api.incident(
                            mid=mid,
                            kind=obj["type"],
                            sev=sev,
                            x=det_x,
                            y=det_y,
                            area=area,
                            people=people,
                            subtype=obj["subtype"],
                            image_path=img_file
                        )
                        body = r.json()
                        sent += 1
                        if body.get("merged"):
                            merged += 1
                            status_str = f"Обновлена (кадров: {body['detections']})"
                        else:
                            status_str = "НОВАЯ ЧС"

                        print(f"  [ДЕТЕКЦИЯ] {obj['type'].upper():<10} | Степень: {sev:<6} | "
                              f"Площадь: {area:4.1f}% | X={det_x:5.1f}, Y={det_y:5.1f} -> {status_str}")

            dist += CRUISE_SPEED * STEP
            time.sleep(STEP / speed)

        # 3. Посадка
        print(" -> Завершение маршрута, посадка на базу...")
        land_steps = max(1, int(2.0 / STEP))
        for i in range(land_steps + 1):
            z = CRUISE_ALT * (1.0 - (i / land_steps))
            api.telemetry(mid, ROUTE[-1][0], ROUTE[-1][1], max(z, 0.1), 0.0, 85.0, "land")
            time.sleep(STEP / speed)

    finally:
        api.mission_finish(mid)
        elapsed = time.time() - t0
        print(f"==========================================")
        print(f"🏁 ВЫЛЕТ №{mid} ЗАВЕРШЁН за {elapsed:.1f} сек.")
        print(f"   Отчетов ЧС: {sent} (из них объединено в очаги: {merged})")
        print(f"==========================================\n")


def main():
    ap = argparse.ArgumentParser(description="Имитатор патрульного дрона МЧС")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--speed", type=float, default=1.2, help="Множитель скорости полёта")
    ap.add_argument("--loops", type=int, default=1, help="Сколько кругов облететь")
    ap.add_argument("--no-images", action="store_true", help="Не загружать фотографии")
    ap.add_argument("--drone-id", type=int, default=1)
    ap.add_argument("--api-key", default=os.getenv("DRONE_API_KEY", "oko-drone-key"))
    args = ap.parse_args()

    api = Api(args.api, args.api_key)
    try:
        requests.get(f"{args.api.rstrip('/')}/api/health", timeout=3).raise_for_status()
    except Exception as e:
        print(f"ОШИБКА: Сервер {args.api} недоступен ({e}). Сначала запустите uvicorn!")
        sys.exit(1)

    try:
        for i in range(args.loops):
            if args.loops > 1:
                print(f"--- Круг {i + 1} из {args.loops} ---")
            fly(api, args.drone_id, max(args.speed, 0.2), images=not args.no_images)
            if i < args.loops - 1:
                time.sleep(2.0)
    except KeyboardInterrupt:
        print("\nПолет прерван оператором (Ctrl+C).")


if __name__ == "__main__":
    main()