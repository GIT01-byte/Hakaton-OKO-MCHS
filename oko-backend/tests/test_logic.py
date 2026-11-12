import math
from datetime import datetime, timezone

import pytest

from app.logic import (SEVERITY_RANK, allowed_types, distance, max_severity,
                       normalize_severity, normalize_type, to_utc_iso, xy_to_latlon)


def test_normalize_type_accepts_russian_and_english():
    assert normalize_type("fire") == "fire"
    assert normalize_type(" Пожар ") == "fire"
    assert normalize_type("ВОДА") == "flood"
    assert normalize_type("утечка") == "pollution"
    assert normalize_type("оползень") == "landslide"


def test_normalize_type_rejects_unknown():
    with pytest.raises(ValueError):
        normalize_type("землетрясение")
    with pytest.raises(ValueError):
        normalize_type("person")   # тип «пострадавший» убран: люди — это поле people_count


def test_normalize_severity_matches_detector_output():
    assert normalize_severity("низкая") == "low"
    assert normalize_severity("средняя") == "medium"
    assert normalize_severity("высокая") == "high"
    with pytest.raises(ValueError):
        normalize_severity("критическая")


def test_roles_map_to_allowed_types():
    assert allowed_types("operator") is None
    assert allowed_types("viewer") is None
    assert allowed_types("firefighter") == {"fire", "flood", "landslide"}
    assert allowed_types("ecologist") == {"pollution"}


def test_max_severity():
    assert max_severity("low", "high") == "high"
    assert max_severity("medium", "low") == "medium"


def test_severity_rank_ordering():
    assert SEVERITY_RANK["high"] > SEVERITY_RANK["medium"] > SEVERITY_RANK["low"]


def test_xy_to_latlon_origin_and_offsets():
    lat, lon = xy_to_latlon(0, 0, 56.0, 60.0)
    assert (lat, lon) == (56.0, 60.0)
    lat, lon = xy_to_latlon(0, 111_320.0, 56.0, 60.0)       # 1 градус на север
    assert lat == pytest.approx(57.0)
    assert lon == pytest.approx(60.0)
    lat, lon = xy_to_latlon(100, 0, 56.0, 60.0)
    assert lat == pytest.approx(56.0)
    assert lon == pytest.approx(60.0 + 100 / (111_320.0 * math.cos(math.radians(56.0))))


def test_distance_and_utc():
    assert distance(0, 0, 3, 4) == 5.0
    s = to_utc_iso(datetime(2026, 11, 11, 9, 30, tzinfo=timezone.utc))
    assert s.endswith("+00:00")
