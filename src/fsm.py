# fsm.py
import math
import config
from logger import Logger
import mission_flood
import mission_fire
import mission_landslide
import mission_landfill
import mission_person

SAFE_MODES = ("TAKEOFF", "RETURN_HOME", "LANDING", "FINISHED")


class MissionFSM:
    def __init__(self, reporter):
        self.reporter = reporter
        self.mode = "TAKEOFF"
        self.target_altitude = config.FLIGHT_ALTITUDE
        self.target_cam_pitch = 0.0
        self.state_timer = 0.0
        self.has_taken_off = False
        self.mission_accomplished = False
        self.saved_heading = 0.0

        self.gps_x = 0.0
        self.gps_y = 0.0
        self.altitude = 0.0
        self.yaw = 0.0

        self.water_ratio = 0.0
        self.wet_edges = []
        self.is_fire = False
        self.is_landslide = False
        self.is_landfill = False
        self.person_detected = False

        self.waypoints = [
            (config.START_X + config.GRID_SIZE / 2 + i * config.GRID_SIZE,
             config.START_Y + config.GRID_SIZE / 2)
            for i in range(5)
        ]
        self._init_runtime()

    def _init_runtime(self):
        self.current_wp = 0
        self.empty_squares_count = 0
        self._scan_last_yaw = 0.0
        self._scan_accumulated = 0.0
        self._scan_had_known = False
        self.incident_xy = None
        self.incident_metric = 0.0
        self.person_last_seen = 0.0
        self.person_conf = 0.0
        self.flood_alt_goal = 0.0
        self.takeoff_time = None
        self.low_battery = False

    # ------------------------------------------------------------------ helpers
    def _enter(self, mode, t):
        self.mode = mode
        self.state_timer = t
        self.incident_metric = 0.0

    def _xy(self, vd, key):
        return vd.get(key) or (self.gps_x, self.gps_y)

    def finish_incident(self, t):
        """Инцидент отработан - возвращаемся к патрулю (раньше дрон улетал домой после первой находки)."""
        Logger.event("INCIDENT_DONE")
        self.mission_accomplished = True
        self.empty_squares_count = 0
        self.incident_xy = None
        self.person_conf = 0.0
        if self.mode != "RETURN_HOME":
            self.mode = "PATROL_MOVE"
        self.state_timer = t

    def _battery_critical(self, t):
        if self.takeoff_time is None:
            return False
        remaining = config.BATTERY_FLIGHT_TIME - (t - self.takeoff_time)
        dist = math.hypot(config.START_X - self.gps_x, config.START_Y - self.gps_y)
        need = dist / config.CRUISE_SPEED_EST + self.altitude / config.CLIMB_SPEED_EST + config.BATTERY_RESERVE
        return remaining < need

    def _check_triggers(self, t, vd, full_scan):
        """Приоритет: человек > огонь > вода > оползень > свалка. True, если режим сменился."""
        if self.person_detected and vd.get("person_world"):
            x, y = vd["person_world"]
            if not self.reporter.is_known("PERSON", x, y):
                Logger.event("PERSON_DETECTED", {"conf": vd.get("person_conf", 0), "x": x, "y": y})
                self.incident_xy = (x, y)
                self.person_last_seen = t
                self.person_conf = vd.get("person_conf", 0.0)
                self._enter("PERSON_CONFIRM", t)
                return True
            self._scan_had_known = True

        candidates = [("FIRE", self.is_fire, "fire_world", "fire_score", "FIRE_APPROACH")]
        if full_scan:
            candidates += [
                ("FLOOD", self.water_ratio > config.WATER_TRIGGER_RATIO, "water_world",
                 "water_ratio", "FLOOD_APPROACH"),
                ("LANDSLIDE", self.is_landslide, "landslide_world", "landslide_ratio", "LANDSLIDE_APPROACH"),
                ("LANDFILL", self.is_landfill, "landfill_world", "landfill_ratio", "LANDFILL_APPROACH"),
            ]
        for kind, flag, wkey, rkey, mode in candidates:
            if not flag:
                continue
            x, y = self._xy(vd, wkey)
            if self.reporter.is_known(kind, x, y):
                self._scan_had_known = True
                continue
            Logger.event("WATER_DETECTED" if kind == "FLOOD" else f"{kind}_DETECTED", {"x": x, "y": y, "score": vd.get(rkey, 0.0),
                                              "ratio": vd.get(rkey, 0.0)})
            self.incident_xy = (x, y)
            if kind == "FLOOD":
                self.saved_heading = self.yaw
            self._enter(mode, t)
            self.incident_metric = vd.get(rkey, 0.0)
            return True
        return False

    def _go_to(self, tx, ty):
        yaw_err = math.atan2(ty - self.gps_y, tx - self.gps_x) - self.yaw
        yaw_err = (yaw_err + math.pi) % (2 * math.pi) - math.pi
        yaw = max(-1.5, min(1.5, yaw_err * config.DRONE_TURN_SPEED))
        pitch = config.DRONE_MAX_SPEED if abs(yaw_err) < 0.4 else config.DRONE_MAX_SPEED * 0.3
        return pitch, yaw

    # ------------------------------------------------------------------ main
    def update(self, current_time, sensors, vision_data, last_annotated):
        self.gps_x, self.gps_y, self.altitude = sensors["gps"]
        self.yaw = sensors["yaw"]
        self.water_ratio = vision_data["water_ratio"]
        self.wet_edges = vision_data["wet_edges"]
        self.is_fire = vision_data["is_fire"]
        self.is_landslide = vision_data["is_landslide"]
        self.is_landfill = vision_data["is_landfill"]
        self.person_detected = vision_data["person_detected"]

        target_pitch = 0.0
        target_yaw = 0.0
        target_cam_pitch = 0.0
        self.target_altitude = config.FLIGHT_ALTITUDE

        # Виртуальная батарея: если энергии хватает только на дорогу домой - домой
        if self.takeoff_time is None and self.altitude > 1.0:
            self.takeoff_time = current_time
        if self.mode not in SAFE_MODES and self._battery_critical(current_time):
            Logger.event("BATTERY_LOW")
            self.low_battery = True
            self._enter("RETURN_HOME", current_time)

        # 1. ВЗЛЕТ
        if self.mode == "TAKEOFF":
            if self.altitude >= config.FLIGHT_ALTITUDE - 0.3 and current_time > 2.0:
                Logger.event("TAKEOFF_DONE")
                self._enter("PATROL_MOVE", current_time)

        # 2. ПАТРУЛЬ: ПОЛЕТ К ЦЕНТРУ КВАДРАТА
        elif self.mode == "PATROL_MOVE":
            if self.current_wp >= len(self.waypoints):
                Logger.event("MISSION_RETURN")
                self._enter("RETURN_HOME", current_time)
                return self._get_commands(0.0, 0.0, 0.0)

            if self._check_triggers(current_time, vision_data, full_scan=False):
                return self._get_commands(0.0, 0.0, 0.0)

            tx, ty = self.waypoints[self.current_wp]
            if math.hypot(tx - self.gps_x, ty - self.gps_y) < 3.0:
                Logger.event("SQUARE_SCAN", {"id": self.current_wp + 1})
                self._enter("PATROL_SCAN", current_time)
                self._scan_last_yaw = self.yaw
                self._scan_accumulated = 0.0
                self._scan_had_known = False
            else:
                target_pitch, target_yaw = self._go_to(tx, ty)

        # 3. ПАТРУЛЬ: 360° СКАНИРОВАНИЕ
        elif self.mode == "PATROL_SCAN":
            target_yaw = config.SCAN_ROTATION_SPEED
            elapsed = current_time - self.state_timer
            target_cam_pitch = math.sin(elapsed * 1.5) * config.SCAN_CAM_AMPLITUDE

            delta_yaw = (self.yaw - self._scan_last_yaw + math.pi) % (2 * math.pi) - math.pi
            self._scan_accumulated += abs(delta_yaw)
            self._scan_last_yaw = self.yaw

            if self._check_triggers(current_time, vision_data, full_scan=True):
                pass
            elif self._scan_accumulated >= (2 * math.pi - 0.1) or elapsed > config.SCAN_TIMEOUT:
                if self._scan_had_known:
                    Logger.event("SQUARE_KNOWN")
                else:
                    self.empty_squares_count += 1
                    Logger.event("SQUARE_EMPTY", {"count": self.empty_squares_count,
                                                  "max": config.MAX_EMPTY_SQUARES})

                if self.empty_squares_count >= config.MAX_EMPTY_SQUARES:
                    self._enter("RETURN_HOME", current_time)
                else:
                    self.current_wp += 1
                    self._enter("PATROL_MOVE", current_time)

        # 4. ДЕЛЕГИРОВАНИЕ В МИССИИ
        elif self.mode.startswith("PERSON_"):
            return self._get_commands_from_dict(
                mission_person.update(self, current_time, sensors, vision_data, last_annotated))
        elif self.mode.startswith("FLOOD_"):
            return self._get_commands_from_dict(
                mission_flood.update(self, current_time, sensors, vision_data, last_annotated))
        elif self.mode.startswith("FIRE_"):
            return self._get_commands_from_dict(
                mission_fire.update(self, current_time, sensors, vision_data, last_annotated))
        elif self.mode.startswith("LANDSLIDE_"):
            return self._get_commands_from_dict(
                mission_landslide.update(self, current_time, sensors, vision_data, last_annotated))
        elif self.mode.startswith("LANDFILL_"):
            return self._get_commands_from_dict(
                mission_landfill.update(self, current_time, sensors, vision_data, last_annotated))

        # 5. ВОЗВРАТ ДОМОЙ / ПОСАДКА
        elif self.mode == "RETURN_HOME":
            if math.hypot(config.START_X - self.gps_x, config.START_Y - self.gps_y) < 2.0:
                self._enter("LANDING", current_time)
            else:
                target_pitch, target_yaw = self._go_to(config.START_X, config.START_Y)

        elif self.mode == "LANDING":
            self.target_altitude = config.START_Z
            if self.altitude <= config.START_Z + 0.2:
                Logger.event("LANDING")
                self.mode = "FINISHED"

        if self.mode == "FINISHED":
            return None

        self.target_cam_pitch = target_cam_pitch
        return self._get_commands(target_pitch, target_yaw, target_cam_pitch)

    def _get_commands(self, pitch, yaw, cam_pitch):
        return {"target_pitch": pitch, "target_yaw": yaw,
                "target_altitude": self.target_altitude, "target_cam_pitch": cam_pitch}

    def _get_commands_from_dict(self, cmd_dict):
        self.target_altitude = cmd_dict["target_altitude"]
        self.target_cam_pitch = cmd_dict["target_cam_pitch"]
        return cmd_dict

    def reset(self):
        self.mode = "TAKEOFF"
        self.target_altitude = config.FLIGHT_ALTITUDE
        self.target_cam_pitch = 0.0
        self.has_taken_off = False
        self.mission_accomplished = False
        self.saved_heading = 0.0
        self._init_runtime()
