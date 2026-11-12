# mission_fire.py
import cv2
import config
from logger import Logger

CAM_PITCH_LIMIT = -0.5  # физический предел наклона камеры (рад), см. clamp в main


def update(mission, current_time, sensors, vision_data, last_annotated):
    gps_x, gps_y, altitude = sensors["gps"]
    score = vision_data.get("fire_score", 0.0)
    cmd = {"target_pitch": 0.0, "target_yaw": 0.0,
           "target_altitude": config.FLIGHT_ALTITUDE, "target_cam_pitch": 0.0}

    if mission.mode == "FIRE_APPROACH":
        cmd["target_pitch"] = -2.0
        if mission.fire_step == 0:
            mission.fire_step = 1
        mission.incident_metric = max(mission.incident_metric, score)
        mission.fire_best_score = max(mission.fire_best_score, score)
        cmd["target_cam_pitch"] = -mission.fire_step * config.FIRE_CAM_STEP_RAD
        if current_time - mission.state_timer > config.APPROACH_TIME:
            mission.mode = "FIRE_INSPECT"
            mission.fire_prev_score = mission.fire_best_score
            mission.fire_step_timer = current_time

    elif mission.mode == "FIRE_INSPECT":
        mission.fire_best_score = max(mission.fire_best_score, score)
        mission.incident_metric = max(mission.incident_metric, score)
        cmd["target_cam_pitch"] = max(
            CAM_PITCH_LIMIT, -mission.fire_step * config.FIRE_CAM_STEP_RAD)
        if current_time - mission.fire_step_timer >= config.FIRE_STEP_TIME:
            grew = mission.fire_best_score - mission.fire_prev_score >= config.FIRE_GROWTH_EPS
            if (grew and mission.fire_frames_saved < config.FIRE_MAX_FRAMES
                    and last_annotated is not None):
                fname = f"fire_step_{mission.fire_step:02d}_{int(current_time)}s.jpg"
                cv2.imwrite(fname, last_annotated)
                mission.fire_frames_saved += 1
                Logger.event("FIRE_STEP", {"step": mission.fire_step,
                                           "score": mission.fire_best_score,
                                           "file": fname})
            if grew and mission.fire_step < config.FIRE_MAX_STEPS:
                mission.fire_step += 1
            else:
                Logger.event("FIRE_MAX_INFO", {"step": mission.fire_step,
                                               "score": mission.fire_best_score,
                                               "frames": mission.fire_frames_saved})
                mission.mode = "FIRE_REPORT"
                mission.state_timer = current_time
            mission.fire_prev_score = mission.fire_best_score
            mission.fire_step_timer = current_time

    elif mission.mode == "FIRE_REPORT":
        if current_time - mission.state_timer > 1.0:
            x, y = mission.incident_xy or (gps_x, gps_y)
            from reporter import severity
            sev = severity("FIRE", mission.incident_metric)
            mission.reporter.report(
                "FIRE", x, y, altitude, sev,
                {"title": "Пожар",
                 "frame_coverage": round(mission.incident_metric, 3),
                 "fire_frames": mission.fire_frames_saved + 1},
                last_annotated)
            mission.fire_step = 0
            mission.fire_best_score = 0.0
            mission.fire_prev_score = 0.0
            mission.fire_frames_saved = 0
            mission.finish_incident(current_time)

    return cmd
