"""HTTP-клиент дрона для сервера «Око МЧС».

Все методы возвращают True / dict / None при ошибке — НИКОГДА не бросают.
Данные локально сохраняет logger.py, HTTP — это только доставка.
"""

import collections
import logging
import os
import time
from typing import Optional

import requests
from requests.exceptions import RequestException

log = logging.getLogger("drone_api")

API_URL = os.getenv("OKO_API_URL", "http://127.0.0.1:8000/api")
API_KEY = os.getenv("OKO_API_KEY", "oko-drone-key")
DRONE_ID = int(os.getenv("OKO_DRONE_ID", "1"))
TIMEOUT = float(os.getenv("OKO_TIMEOUT", "1.5"))

# reporter.py умеет CRITICAL; сервер знает только low/medium/high
_SEVERITY_MAP = {
    "critical": "high",
    "критическая": "high",
    "критический": "high",
    "high": "high",
    "высокая": "high",
    "высокий": "high",
    "medium": "medium",
    "средняя": "medium",
    "средний": "medium",
    "low": "low",
    "низкая": "low",
    "низкий": "low",
}


class DroneAPIClient:
    def __init__(self):
        self.mission_id: Optional[int] = None
        self._s = requests.Session()
        self._s.headers.update({"X-API-Key": API_KEY})
        # отложенная досылка после обрыва
        self._pending = collections.deque(maxlen=500)

    # ─────────── служебное ───────────
    def health(self) -> bool:
        try:
            return self._s.get(f"{API_URL}/health", timeout=TIMEOUT).ok
        except RequestException:
            return False

    def start_mission(self) -> Optional[int]:
        try:
            r = self._s.post(
                f"{API_URL}/missions", json={"drone_id": DRONE_ID}, timeout=TIMEOUT
            )
            if r.status_code == 201:
                self.mission_id = int(r.json()["id"])
                log.info("mission started id=%s", self.mission_id)
                return self.mission_id
            log.warning("start_mission %s %s", r.status_code, r.text[:200])
        except RequestException as e:
            log.warning("start_mission network: %s", e)
        return None

    def finish_mission(self) -> bool:
        if self.mission_id is None:
            return False
        try:
            ok = self._s.post(
                f"{API_URL}/missions/{self.mission_id}/finish", timeout=TIMEOUT
            ).ok
        except RequestException:
            ok = False
        self.mission_id = None
        return ok

    # ─────────── телеметрия ───────────
    def send_telemetry(
        self,
        t: float,
        x: float,
        y: float,
        z: float,
        yaw: float = 0.0,
        mode: str = "",
        water_pct: float = 0.0,
        fire_score: float = 0.0,
        avoid: str = "",
        persons: int = 0,
        battery: float = 100.0,
    ) -> bool:
        if self.mission_id is None:
            return False
        ok = self._send_telemetry_now(
            t, x, y, z, yaw, mode, water_pct, fire_score, avoid, persons, battery
        )
        if not ok:
            self._pending.append(
                (
                    "tel",
                    (
                        t,
                        x,
                        y,
                        z,
                        yaw,
                        mode,
                        water_pct,
                        fire_score,
                        avoid,
                        persons,
                        battery,
                    ),
                )
            )
        else:
            self._flush()
        return ok

    def _send_telemetry_now(
        self, t, x, y, z, yaw, mode, water_pct, fire_score, avoid, persons, battery
    ) -> bool:
        if self.mission_id is None:
            return False
        payload = {
            "mission_id": self.mission_id,
            "x": round(x, 2),
            "y": round(y, 2),
            "z": round(z, 2),
            "yaw": round(yaw, 3),
            "battery": round(battery, 1),
            "state": str(mode),
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)),
            "water_pct": round(water_pct, 1),
            "fire_score": round(fire_score, 4),
            "avoid": str(avoid),
            "persons": int(persons),
        }
        try:
            r = self._s.post(f"{API_URL}/telemetry", json=payload, timeout=TIMEOUT)
            return r.status_code in (200, 201)
        except RequestException:
            return False

    # ─────────── инцидент ───────────
    def send_incident(
        self,
        kind: str,
        severity: str,
        x: float,
        y: float,
        area_pct: float = 0.0,
        note: str = "",
        people_count: int = 0,
        subtype: Optional[str] = None,
        image_path: Optional[str] = None,
        local_id: int = 0,
    ) -> Optional[dict]:
        if self.mission_id is None:
            return None
        sev = _SEVERITY_MAP.get(str(severity).lower(), "medium")
        data = {
            "mission_id": self.mission_id,
            "type": str(kind).lower(),
            "severity": sev,
            "x": float(x),
            "y": float(y),
            "area_pct": float(area_pct),
            "people_count": int(people_count),
            "note": note or f"auto {kind} (local_id={local_id})",
        }
        if subtype:
            data["subtype"] = str(subtype)

        fh = None
        files = None
        try:
            if image_path and os.path.exists(image_path):
                fh = open(image_path, "rb")
                files = {"image": (os.path.basename(image_path), fh, "image/jpeg")}
            r = self._s.post(
                f"{API_URL}/incidents", data=data, files=files, timeout=TIMEOUT * 2
            )
            if r.status_code in (200, 201):
                return r.json()
            log.warning("send_incident %s %s", r.status_code, r.text[:200])
            return None
        except RequestException as e:
            log.warning("send_incident network: %s", e)
            return None
        finally:
            if fh:
                fh.close()

    # ─────────── досылка отложенного ───────────
    def _flush(self):
        if self.mission_id is None:
            return
        while self._pending:
            kind, args = self._pending[0]
            if kind == "tel" and self._send_telemetry_now(*args):
                self._pending.popleft()
            else:
                break


# синглтон
client = DroneAPIClient()
