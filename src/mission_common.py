# mission_common.py - общий сценарий для огня / оползня / свалки:
# подлёт -> отчёт -> возврат к патрулю (раньше режим "SCAN_AND_REPORT" не обрабатывался FSM и дрон зависал).
import config

TITLES = {"FIRE": "Пожар", "LANDSLIDE": "Оползень", "LANDFILL": "Свалка"}
RATIO_KEYS = {"FIRE": "fire_score", "LANDSLIDE": "landslide_ratio", "LANDFILL": "landfill_ratio"}


def update(kind, mission, current_time, sensors, vision_data, last_annotated):
    cmd = {"target_pitch": 0.0, "target_yaw": 0.0,
           "target_altitude": config.FLIGHT_ALTITUDE, "target_cam_pitch": 0.0}
    gps_x, gps_y, altitude = sensors["gps"]

    if mission.mode == f"{kind}_APPROACH":
        cmd["target_pitch"] = -2.0
        mission.incident_metric = max(mission.incident_metric, vision_data.get(RATIO_KEYS[kind], 0.0))
        if current_time - mission.state_timer > config.APPROACH_TIME:
            mission.mode = f"{kind}_REPORT"
            mission.state_timer = current_time

    elif mission.mode == f"{kind}_REPORT":
        mission.incident_metric = max(mission.incident_metric, vision_data.get(RATIO_KEYS[kind], 0.0))
        if current_time - mission.state_timer > 1.0:
            x, y = mission.incident_xy or (gps_x, gps_y)
            from reporter import severity
            sev = severity(kind, mission.incident_metric)
            mission.reporter.report(
                kind, x, y, altitude, sev,
                {"title": TITLES[kind], "frame_coverage": round(mission.incident_metric, 3)},
                last_annotated)
            mission.finish_incident(current_time)

    return cmd
