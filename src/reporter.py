# reporter.py - классификация опасности, геопозиция, лог и передача в штаб
import math
import cv2
import config
from logger import Logger


def severity(kind, metric):
    """Степень опасности по метрике: доля кадра (огонь/оползень/свалка) или площадь м² (наводнение)."""
    if kind == "PERSON":
        return "CRITICAL"
    table = {
        "FIRE": (0.01, 0.05, 0.15),
        "LANDSLIDE": (0.30, 0.45, 0.65),
        "LANDFILL": (0.20, 0.35, 0.50),
        "FLOOD": (500.0, 3000.0, 15000.0),
    }
    lo, mid, hi = table.get(kind, (0.1, 0.3, 0.6))
    if metric < lo:
        return "LOW"
    if metric < mid:
        return "MEDIUM"
    if metric < hi:
        return "HIGH"
    return "CRITICAL"


class IncidentReporter:
    """Дедупликация инцидентов + степень опасности; сам отчёт пишет Logger.report (mission_reports.json)."""

    def __init__(self):
        self.known = []  # (kind, x, y) - уже отправленные
        self.ignored = []  # (kind, x, y) - ложные тревоги
        self.counter = 0

    def _near(self, lst, kind, x, y, radius):
        return any(
            k == kind and math.hypot(x - kx, y - ky) < radius for k, kx, ky in lst
        )

    def is_known(self, kind, x, y):
        r = config.DEDUP_RADIUS.get(kind, 40.0)
        return self._near(self.known, kind, x, y, r) or self._near(
            self.ignored, kind, x, y, config.PERSON_IGNORE_RADIUS
        )

    def ignore(self, kind, x, y):
        self.ignored.append((kind, x, y))

    def report(self, kind, x, y, z, sev, details, image):
        if self._near(self.known, kind, x, y, config.DEDUP_RADIUS.get(kind, 40.0)):
            return None
        self.known.append((kind, x, y))
        self.counter += 1
        details = dict(details)
        area = details.pop("area_m2", 0.0)
        fname = f"./drone_alerts/alert_{kind}_{self.counter:03d}_{int(x)}_{int(y)}.jpg"
        if image is not None:
            cv2.imwrite(fname, image)
        extra = {"id": self.counter, "severity": sev}
        extra.update(details)
        rec = Logger.report(kind, x, y, z, area, fname, extra_data=extra)
        self._send(rec)
        return rec

    def _send(self, rec):
        if not config.HQ_URL:
            return
        import json
        import threading

        def post():
            try:
                import urllib.request

                req = urllib.request.Request(
                    config.HQ_URL,
                    data=json.dumps(rec).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=3)
            except Exception as e:
                print(f"[HQ] не удалось отправить: {e}")

        threading.Thread(target=post, daemon=True).start()
