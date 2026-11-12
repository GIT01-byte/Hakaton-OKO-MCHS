# fsm.py
import math
import config
from logger import Logger
import mission_flood
import mission_fire
import mission_landslide
import mission_landfill


class MissionFSM:
    def __init__(self):
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

        self.waypoints = []
        for i in range(5):
            self.waypoints.append(
                (
                    config.START_X + config.GRID_SIZE / 2 + i * config.GRID_SIZE,
                    config.START_Y + config.GRID_SIZE / 2,
                )
            )

        self.current_wp = 0
        self.empty_squares_count = 0
        self._scan_last_yaw = 0.0
        self._scan_accumulated = 0.0

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

        # 1. ВЗЛЕТ
        if self.mode == "TAKEOFF":
            self.target_altitude = config.FLIGHT_ALTITUDE
            if self.altitude >= config.FLIGHT_ALTITUDE - 0.3 and current_time > 2.0:
                Logger.event("TAKEOFF_DONE")
                self.mode = "PATROL_MOVE"
                self.state_timer = current_time

        # 2. ПАТРУЛЬ: ПОЛЕТ К ЦЕНТРУ
        elif self.mode == "PATROL_MOVE":
            if self.current_wp >= len(self.waypoints):
                self.mode = "RETURN_HOME"
                return self._get_commands(target_pitch, target_yaw, target_cam_pitch)

            tx, ty = self.waypoints[self.current_wp]
            dist = math.hypot(tx - self.gps_x, ty - self.gps_y)

            if dist < 3.0:
                Logger.event("SQUARE_SCAN", {"id": self.current_wp + 1})
                self.mode = "PATROL_SCAN"
                self.state_timer = current_time
                self._scan_last_yaw = self.yaw
                self._scan_accumulated = 0.0
            else:
                yaw_err = math.atan2(ty - self.gps_y, tx - self.gps_x) - self.yaw
                if yaw_err > math.pi:
                    yaw_err -= 2 * math.pi
                elif yaw_err < -math.pi:
                    yaw_err += 2 * math.pi
                target_yaw = max(-1.5, min(1.5, yaw_err * config.DRONE_TURN_SPEED))
                target_pitch = (
                    config.DRONE_MAX_SPEED
                    if abs(yaw_err) < 0.4
                    else config.DRONE_MAX_SPEED * 0.3
                )

        # 3. ПАТРУЛЬ: 360 СКАНИРОВАНИЕ
        elif self.mode == "PATROL_SCAN":
            target_pitch = 0.0
            target_yaw = config.SCAN_ROTATION_SPEED

            elapsed = current_time - self.state_timer
            target_cam_pitch = math.sin(elapsed * 1.5) * config.SCAN_CAM_AMPLITUDE

            delta_yaw = self.yaw - self._scan_last_yaw
            if delta_yaw > math.pi:
                delta_yaw -= 2 * math.pi
            elif delta_yaw < -math.pi:
                delta_yaw += 2 * math.pi
            self._scan_accumulated += abs(delta_yaw)
            self._scan_last_yaw = self.yaw

            # ТРИГГЕРЫ БЕДСТВИЙ (Передаем только цифры)
            if self.water_ratio > config.WATER_TRIGGER_RATIO:
                Logger.event(
                    "WATER_DETECTED",
                    {"x": self.gps_x, "y": self.gps_y, "ratio": self.water_ratio},
                )
                self.saved_heading = self.yaw
                self.mode = "FLOOD_APPROACH"
                self.state_timer = current_time
            elif self.is_fire:
                Logger.event(
                    "FIRE_DETECTED", {"score": vision_data.get("fire_score", 0)}
                )
                self.mode = "FIRE_APPROACH"
                self.state_timer = current_time
            elif self.is_landslide:
                Logger.event("LANDSLIDE_DETECTED")
                self.mode = "LANDSLIDE_APPROACH"
                self.state_timer = current_time
            elif self.is_landfill:
                Logger.event("LANDFILL_DETECTED")
                self.mode = "LANDFILL_APPROACH"
                self.state_timer = current_time

            # ЗАВЕРШЕНИЕ СКАНИРОВАНИЯ
            elif (
                self._scan_accumulated >= (2 * math.pi - 0.1)
                or elapsed > config.SCAN_TIMEOUT
            ):
                self.empty_squares_count += 1
                Logger.event(
                    "SQUARE_EMPTY",
                    {
                        "count": self.empty_squares_count,
                        "max": config.MAX_EMPTY_SQUARES,
                    },
                )

                if self.empty_squares_count >= config.MAX_EMPTY_SQUARES:
                    self.mode = "RETURN_HOME"
                    self.state_timer = current_time
                else:
                    self.current_wp += 1
                    self.mode = "PATROL_MOVE"

        # 4. ДЕЛЕГИРОВАНИЕ В МИССИИ
        elif self.mode.startswith("FLOOD_"):
            cmd = mission_flood.update(
                self, current_time, sensors, vision_data, last_annotated
            )
            return self._get_commands_from_dict(cmd)

        elif self.mode.startswith("FIRE_"):
            cmd = mission_fire.update(
                self, current_time, sensors, vision_data, last_annotated
            )
            return self._get_commands_from_dict(cmd)

        elif self.mode.startswith("LANDSLIDE_"):
            cmd = mission_landslide.update(
                self, current_time, sensors, vision_data, last_annotated
            )
            return self._get_commands_from_dict(cmd)

        elif self.mode.startswith("LANDFILL_"):
            cmd = mission_landfill.update(
                self, current_time, sensors, vision_data, last_annotated
            )
            return self._get_commands_from_dict(cmd)

        # 5. ВОЗВРАТ ДОМОЙ
        elif self.mode == "RETURN_HOME":
            dist = math.hypot(config.START_X - self.gps_x, config.START_Y - self.gps_y)
            if dist < 2.0:
                self.mode = "LANDING"
            else:
                yaw_err = (
                    math.atan2(config.START_Y - self.gps_y, config.START_X - self.gps_x)
                    - self.yaw
                )
                if yaw_err > math.pi:
                    yaw_err -= 2 * math.pi
                elif yaw_err < -math.pi:
                    yaw_err += 2 * math.pi
                target_yaw = max(-1.5, min(1.5, yaw_err * config.DRONE_TURN_SPEED))
                target_pitch = (
                    config.DRONE_MAX_SPEED
                    if abs(yaw_err) < 0.4
                    else config.DRONE_MAX_SPEED * 0.3
                )

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
        return {
            "target_pitch": pitch,
            "target_yaw": yaw,
            "target_altitude": self.target_altitude,
            "target_cam_pitch": cam_pitch,
        }

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
        self.current_wp = 0
        self.empty_squares_count = 0
        self._scan_last_yaw = 0.0
        self._scan_accumulated = 0.0
