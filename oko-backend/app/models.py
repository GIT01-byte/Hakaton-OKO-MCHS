from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from . import config
from .db import Base
from .logic import utcnow, xy_to_latlon


class Drone(Base):
    __tablename__ = "drones"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    model: Mapped[str] = mapped_column(String(64), default="DJI Mavic 2 Pro")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    display_name: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(primary_key=True)
    drone_id: Mapped[int] = mapped_column(ForeignKey("drones.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="active")


class Telemetry(Base):
    __tablename__ = "telemetry"

    id: Mapped[int] = mapped_column(primary_key=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("missions.id"), index=True)
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    z: Mapped[float] = mapped_column(Float, default=0.0)
    yaw: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    battery: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # ── НОВОЕ: обогащение от детекторов дрона (из logger.py) ──
    water_pct: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=0.0
    )
    fire_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=0.0
    )
    avoid: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, default="")
    persons: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)

    @property
    def lat(self) -> float:
        return xy_to_latlon(self.x, self.y, config.BASE_LAT, config.BASE_LON)[0]

    @property
    def lon(self) -> float:
        return xy_to_latlon(self.x, self.y, config.BASE_LAT, config.BASE_LON)[1]


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("missions.id"), index=True)
    type: Mapped[str] = mapped_column(String(16), index=True)
    severity: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    area_pct: Mapped[float] = mapped_column(Float, default=0.0)
    detections: Mapped[int] = mapped_column(Integer, default=1)
    people_count: Mapped[int] = mapped_column(Integer, default=0)
    subtype: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    image_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    @property
    def lat(self) -> float:
        return xy_to_latlon(self.x, self.y, config.BASE_LAT, config.BASE_LON)[0]

    @property
    def lon(self) -> float:
        return xy_to_latlon(self.x, self.y, config.BASE_LAT, config.BASE_LON)[1]

    @property
    def image_url(self) -> Optional[str]:
        return "/media/%s" % self.image_path if self.image_path else None
