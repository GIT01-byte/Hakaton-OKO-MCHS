"""Чистая логика без зависимостей от FastAPI и базы (легко тестируется)."""
import math
from datetime import datetime, timezone
from typing import Optional

TYPES = {
    "fire": "fire", "пожар": "fire", "огонь": "fire", "дым": "fire",
    "flood": "flood", "наводнение": "flood", "вода": "flood", "подтопление": "flood",
    "pollution": "pollution", "загрязнение": "pollution", "свалка": "pollution",
    "утечка": "pollution", "нефть": "pollution",
    "landslide": "landslide", "оползень": "landslide", "сель": "landslide",
}
TYPE_LABELS = {
    "fire": "Пожар", "flood": "Наводнение", "pollution": "Загрязнение", "landslide": "Оползень",
}
SEVERITIES = {
    "low": "low", "низкая": "low",
    "medium": "medium", "средняя": "medium",
    "high": "high", "высокая": "high",
}
SEVERITY_LABELS = {"low": "Низкая", "medium": "Средняя", "high": "Высокая"}
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
METERS_PER_DEG_LAT = 111_320.0

# Какие типы ЧС видит каждая роль (None = все). Разграничение по службам:
# пожарному не нужны свалки, экологу — пожары.
ROLE_TYPES = {
    "operator": None,                                   # оператор ЦУКС: всё
    "viewer": None,                                     # наблюдатель: всё, только чтение
    "firefighter": {"fire", "flood", "landslide"},      # МЧС/пожарная охрана
    "ecologist": {"pollution"},                         # экологическая служба
}
ROLES = set(ROLE_TYPES)


def normalize_type(value: str) -> str:
    key = (value or "").strip().lower()
    if key not in TYPES:
        raise ValueError("неизвестный тип ЧС: %r (допустимо: fire, flood, pollution, landslide)" % value)
    return TYPES[key]


def normalize_severity(value: str) -> str:
    key = (value or "").strip().lower()
    if key not in SEVERITIES:
        raise ValueError("неизвестная степень: %r (допустимо: low, medium, high)" % value)
    return SEVERITIES[key]


def allowed_types(role: str) -> Optional[set]:
    """None = все типы разрешены."""
    return ROLE_TYPES.get(role, set())


def max_severity(a: str, b: str) -> str:
    return a if SEVERITY_RANK[a] >= SEVERITY_RANK[b] else b


def xy_to_latlon(x: float, y: float, base_lat: float, base_lon: float):
    """Метры симулятора (x - на восток, y - на север) -> широта/долгота от базовой точки."""
    lat = base_lat + y / METERS_PER_DEG_LAT
    lon = base_lon + x / (METERS_PER_DEG_LAT * math.cos(math.radians(base_lat)))
    return lat, lon


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.hypot(x2 - x1, y2 - y1)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def to_utc_iso(dt: datetime) -> str:
    """ISO-строка с явным часовым поясом (чтобы браузер не считал время местным)."""
    return as_utc(dt).isoformat()
