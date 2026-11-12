# mission_flood.py
import math
import config
from reporter import severity


def update(mission, current_time, sensors, vision_data, last_annotated):
    target_pitch = 0.0
    target_yaw = 0.0
    target_cam_pitch = config.CAMERA_PITCH_NADIR
    target_altitude = config.FLIGHT_ALTITUDE

    water_ratio = vision_data["water_ratio"]
    wet_edges = vision_data["wet_edges"]
    gps_x, gps_y, altitude = sensors["gps"]
    yaw = sensors["yaw"]

    # Шаг 4: Наклон камеры (надир)
    if mission.mode == "FLOOD_APPROACH":
        target_altitude = max(altitude, config.FLIGHT_ALTITUDE)
        if current_time - mission.state_timer > 0.8:
            print("[FLOOD] Камера в надире. Движение до заполнения (Шаг 3).")
            mission.mode = "FLOOD_CENTERING"
            mission.state_timer = current_time

    # Шаг 3: Движение по направлению, пока вода не заполнит экран
    elif mission.mode == "FLOOD_CENTERING":
        yaw_error = mission.saved_heading - yaw
        if yaw_error > math.pi:
            yaw_error -= 2 * math.pi
        elif yaw_error < -math.pi:
            yaw_error += 2 * math.pi
        target_yaw = max(-1.5, min(1.5, yaw_error * config.DRONE_TURN_SPEED))
        target_pitch = -2.0
        target_altitude = max(altitude, config.FLIGHT_ALTITUDE)

        timed_out = current_time - mission.state_timer > config.FLOOD_CENTERING_TIMEOUT
        if water_ratio > config.WATER_FULL_SCREEN_RATIO or timed_out:
            print(f"[FLOOD] {'Таймаут' if timed_out else 'Экран заполнен'} "
                  f"({water_ratio*100:.1f}%). Подъем на 30% (Шаг 2).")
            mission.flood_alt_goal = altitude + (config.MAX_FLOOD_ALTITUDE - config.FLIGHT_ALTITUDE) * 0.3
            target_altitude = mission.flood_alt_goal
            mission.mode = "FLOOD_ASCEND_PARTIAL"
            mission.state_timer = current_time

    # Шаг 2: Подъем на 30%
    elif mission.mode == "FLOOD_ASCEND_PARTIAL":
        target_altitude = min(mission.flood_alt_goal, config.MAX_FLOOD_ALTITUDE)
        if current_time - mission.state_timer > 2.0:
            print("[FLOOD] Промежуточный подъем завершен. Полный подъем (Шаг 1).")
            mission.mode = "FLOOD_ASCEND_FULL"
            mission.state_timer = current_time

    # Шаг 1: Полный подъем и отчет
    elif mission.mode == "FLOOD_ASCEND_FULL":
        if len(wet_edges) >= 3 and altitude < config.MAX_FLOOD_ALTITUDE:
            target_altitude = altitude + 0.1
        else:
            print(f"\n[FLOOD] Границы видны (краев: {len(wet_edges)}). Делаю отчет.")
            frame_width_m = 2.0 * altitude * math.tan(config.FOV / 2.0)
            area_sq_m = frame_width_m ** 2 * water_ratio
            x, y = mission.incident_xy or (gps_x, gps_y)
            mission.reporter.report(
                "FLOOD", x, y, altitude, severity("FLOOD", area_sq_m),
                {"area_m2": round(area_sq_m, 1), "edges_detected": len(wet_edges)},
                last_annotated)
            mission.flood_alt_goal = 0.0
            mission.finish_incident(current_time)

    return {
        "target_pitch": target_pitch,
        "target_yaw": target_yaw,
        "target_altitude": target_altitude,
        "target_cam_pitch": target_cam_pitch,
    }
