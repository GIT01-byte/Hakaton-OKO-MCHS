# mission_fire.py
import cv2
import config
from logger import Logger


def update(mission, current_time, sensors, vision_data, last_annotated):
    target_pitch = 0.0
    target_yaw = 0.0
    target_cam_pitch = 0.0
    target_altitude = config.FLIGHT_ALTITUDE

    gps_x, gps_y, altitude = sensors["gps"]

    if mission.mode == "FIRE_APPROACH":
        target_pitch = -2.0
        if current_time - mission.state_timer > 2.5:
            mission.mode = "SCAN_AND_REPORT"
            mission.state_timer = current_time

    elif mission.mode == "SCAN_AND_REPORT":
        if current_time - mission.state_timer > 1.0:
            filename = f"alert_FIRE_{int(gps_x)}_{int(gps_y)}.jpg"
            if last_annotated is not None:
                cv2.imwrite(filename, last_annotated)

            Logger.report("FIRE", gps_x, gps_y, altitude, 0, filename)

            mission.mission_accomplished = True
            mission.mode = "RETURN_HOME"
            mission.state_timer = current_time

    return {
        "target_pitch": target_pitch,
        "target_yaw": target_yaw,
        "target_altitude": target_altitude,
        "target_cam_pitch": target_cam_pitch,
    }
