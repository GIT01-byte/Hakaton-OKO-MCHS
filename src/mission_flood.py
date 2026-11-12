# mission_flood.py
import math
import cv2
import config
from logger import Logger


def update(mission, current_time, sensors, vision_data, last_annotated):
    target_pitch = 0.0
    target_yaw = 0.0
    target_cam_pitch = config.CAMERA_PITCH_NADIR
    target_altitude = config.FLIGHT_ALTITUDE

    water_ratio = vision_data["water_ratio"]
    wet_edges = vision_data["wet_edges"]
    gps_x, gps_y, altitude = sensors["gps"]
    yaw = sensors["yaw"]

    # Шаг 4: Наклон камеры
    if mission.mode == "FLOOD_APPROACH":
        target_altitude = max(altitude, config.FLIGHT_ALTITUDE)
        if current_time - mission.state_timer > 0.8:
            mission.mode = "FLOOD_CENTERING"
            mission.state_timer = current_time

    # Шаг 3: Движение
    elif mission.mode == "FLOOD_CENTERING":
        yaw_error = mission.saved_heading - yaw
        if yaw_error > math.pi:
            yaw_error -= 2 * math.pi
        elif yaw_error < -math.pi:
            yaw_error += 2 * math.pi
        target_yaw = max(-1.5, min(1.5, yaw_error * config.DRONE_TURN_SPEED))
        target_pitch = -2.0

        if water_ratio > config.WATER_FULL_SCREEN_RATIO:
            target_altitude = (
                altitude + (config.MAX_FLOOD_ALTITUDE - config.FLIGHT_ALTITUDE) * 0.3
            )
            mission.mode = "FLOOD_ASCEND_PARTIAL"
            mission.state_timer = current_time

    # Шаг 2: Подъем на 30%
    elif mission.mode == "FLOOD_ASCEND_PARTIAL":
        if current_time - mission.state_timer > 2.0:
            mission.mode = "FLOOD_ASCEND_FULL"
            mission.state_timer = current_time

    # Шаг 1: Полный подъем и отчет
    elif mission.mode == "FLOOD_ASCEND_FULL":
        if len(wet_edges) >= 3 and altitude < config.MAX_FLOOD_ALTITUDE:
            target_altitude = altitude + 0.1
        else:
            frame_width_m = 2.0 * altitude * math.tan(config.FOV / 2.0)
            area_sq_m = frame_width_m**2
            filename = f"flood_report_{int(gps_x)}_{int(gps_y)}.jpg"
            if last_annotated is not None:
                cv2.imwrite(filename, last_annotated)

            # Отправляем данные в логгер
            Logger.report(
                "FLOOD",
                gps_x,
                gps_y,
                altitude,
                area_sq_m,
                filename,
                extra_data={"edges_detected": len(wet_edges)},
            )

            mission.mission_accomplished = True
            mission.mode = "RETURN_HOME"
            mission.state_timer = current_time

    return {
        "target_pitch": target_pitch,
        "target_yaw": target_yaw,
        "target_altitude": target_altitude,
        "target_cam_pitch": target_cam_pitch,
    }
