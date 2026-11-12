"""Демо-данные: вылет по квадрату 10x10 м и ЧС из сцены (как в fake_drone.py),
плюс пользователи с разными ролями.

Запуск:  python -m app.seed --reset
(--reset стирает все данные и создаёт заново)
"""
import math
import os
import shutil
import sys
from datetime import timedelta

from sqlalchemy import select

from . import config
from .db import Base, SessionLocal, engine
from .logic import utcnow
from .models import Drone, Incident, Mission, Telemetry, User
from .security import hash_password

ROUTE = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
ALT = 8.0
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "seed_assets")

# Логин/пароль/роль/отображаемое имя. Демо-пароли — только для стенда!
USERS = [
    ("operator", "operator123", "operator", "Оператор ЦУКС"),
    ("fire", "fire123", "firefighter", "Пожарная служба"),
    ("eco", "eco123", "ecologist", "Экологическая служба"),
    ("viewer", "viewer123", "viewer", "Наблюдатель"),
]


def copy_asset(name: str):
    dst_dir = os.path.join(config.MEDIA_DIR, "incidents")
    os.makedirs(dst_dir, exist_ok=True)
    src = os.path.join(ASSETS, name)
    if not os.path.exists(src):
        return None
    shutil.copy(src, os.path.join(dst_dir, "seed_" + name))
    return "incidents/seed_" + name


def route_points(step=0.5):
    pts = []
    for (x1, y1), (x2, y2) in zip(ROUTE, ROUTE[1:]):
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) / step))
        for i in range(n):
            pts.append((x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n))
    pts.append(ROUTE[-1])
    return pts


def main(reset: bool):
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    with SessionLocal() as db:
        drone = db.scalars(select(Drone)).first()
        if drone is None:
            drone = Drone(name="Mavic-1", model="DJI Mavic 2 Pro")
            db.add(drone)

        for username, password, role, name in USERS:
            if db.scalars(select(User).where(User.username == username)).first() is None:
                db.add(User(username=username, password_hash=hash_password(password),
                            role=role, display_name=name))
        db.commit()

        now = utcnow()

        # --- завершённый вылет (вчерашний) с закрытыми ЧС
        old = Mission(drone_id=drone.id, started_at=now - timedelta(days=1, minutes=4),
                      finished_at=now - timedelta(days=1), status="finished")
        db.add(old)
        db.commit()
        db.add_all([
            Incident(mission_id=old.id, type="fire", severity="low", status="closed", x=2.0, y=7.5,
                     area_pct=1.9, detections=4, people_count=0, first_seen=now - timedelta(days=1, minutes=3),
                     last_seen=now - timedelta(days=1, minutes=2), note="Потушен силами МЧС"),
            Incident(mission_id=old.id, type="pollution", severity="medium", status="confirmed",
                     x=6.0, y=2.0, area_pct=8.4, detections=6, people_count=0,
                     subtype="несанкционированная свалка",
                     first_seen=now - timedelta(days=1, minutes=3),
                     last_seen=now - timedelta(days=1, minutes=1)),
        ])

        # --- текущий вылет: телеметрия по маршруту за последние ~3 минуты
        mission = Mission(drone_id=drone.id, started_at=now - timedelta(minutes=3), status="active")
        db.add(mission)
        db.commit()

        pts = route_points()
        total = len(pts)
        for i, (x, y) in enumerate(pts):
            t = now - timedelta(minutes=3) + timedelta(seconds=180 * i / max(1, total - 1))
            db.add(Telemetry(mission_id=mission.id, time=t, x=x, y=y,
                             z=ALT if 0 < i < total - 1 else 0.1,
                             battery=round(100 - 12 * i / total, 1),
                             state="patrol", yaw=0.0))

        db.add_all([
            Incident(mission_id=mission.id, type="fire", severity="medium", x=8.0, y=5.0, area_pct=9.6,
                     detections=7, people_count=2, first_seen=now - timedelta(minutes=2, seconds=10),
                     last_seen=now - timedelta(minutes=1, seconds=40), image_path=copy_asset("fire.jpg"),
                     note="Людей в зоне очага: 2 (по кадрам дрона)"),
            Incident(mission_id=mission.id, type="flood", severity="high", x=3.0, y=4.0, area_pct=31.2,
                     detections=9, people_count=3, first_seen=now - timedelta(minutes=1, seconds=30),
                     last_seen=now - timedelta(minutes=1), image_path=copy_asset("flood.jpg")),
            Incident(mission_id=mission.id, type="pollution", severity="low", x=2.0, y=8.5, area_pct=7.5,
                     detections=3, people_count=0, subtype="утечка топлива",
                     first_seen=now - timedelta(seconds=50), last_seen=now - timedelta(seconds=30)),
            Incident(mission_id=mission.id, type="landslide", severity="high", x=9.0, y=1.5, area_pct=5.8,
                     detections=4, people_count=0, first_seen=now - timedelta(seconds=45),
                     last_seen=now - timedelta(seconds=15), note="Сход грунта на склоне"),
        ])
        db.commit()
        print("Готово: 2 вылета, %d точек телеметрии, 6 ЧС, %d пользователей"
              % (total, len(USERS)))
        for username, _, role, name in USERS:
            print("  %-9s / (пароль в seed.py)  -> %s (%s)" % (username, name, role))


if __name__ == "__main__":
    main(reset="--reset" in sys.argv)
