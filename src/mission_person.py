# mission_person.py - человек: подтверждение с малой высоты -> отчёт (наивысший приоритет)
import math
import config
from logger import Logger
from reporter import severity


def update(mission, current_time, sensors, vision_data, last_annotated):
    gps_x, gps_y, altitude = sensors["gps"]
    yaw = sensors["yaw"]
    cmd = {"target_pitch": 0.0, "target_yaw": 0.0,
           "target_altitude": config.PERSON_CHECK_ALT,
           "target_cam_pitch": config.CAMERA_PITCH_NADIR}

    if vision_data.get("person_world"):
        mission.incident_xy = vision_data["person_world"]      # уточняем цель
    seen = vision_data["person_detected"]
    if seen:
        mission.person_last_seen = current_time
        mission.person_conf = max(mission.person_conf, vision_data.get("person_conf", 0.0))

    if mission.mode == "PERSON_CONFIRM":
        tx, ty = mission.incident_xy
        dist = math.hypot(tx - gps_x, ty - gps_y)
        if dist > 4.0:   # подлетаем к цели
            yaw_err = math.atan2(ty - gps_y, tx - gps_x) - yaw
            yaw_err = (yaw_err + math.pi) % (2 * math.pi) - math.pi
            cmd["target_yaw"] = max(-1.5, min(1.5, yaw_err * config.DRONE_TURN_SPEED))
            cmd["target_pitch"] = -1.5 if abs(yaw_err) < 0.4 else -0.5

        low_enough = altitude <= config.PERSON_CHECK_ALT + 2.0
        if low_enough and mission.person_conf >= config.PERSON_FINAL_CONF:
            mission.mode = "PERSON_REPORT"
            mission.state_timer = current_time
        elif (current_time - mission.person_last_seen > config.PERSON_LOST_TIMEOUT or
              current_time - mission.state_timer > config.PERSON_CONFIRM_TIMEOUT):
            Logger.event("PERSON_FALSE_ALARM")
            mission.reporter.ignore("PERSON", tx, ty)
            mission.finish_incident(current_time)

    elif mission.mode == "PERSON_REPORT":
        if current_time - mission.state_timer > 1.0:
            x, y = mission.incident_xy
            mission.reporter.report(
                "PERSON", x, y, altitude, severity("PERSON", 1.0),
                {"confidence": round(mission.person_conf, 2),
                 "note": "подтверждён с малой высоты; не животное"},
                last_annotated)
            mission.finish_incident(current_time)

    return cmd
