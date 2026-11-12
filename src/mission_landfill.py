# mission_landfill.py
import mission_common


def update(mission, current_time, sensors, vision_data, last_annotated):
    return mission_common.update("LANDFILL", mission, current_time, sensors, vision_data, last_annotated)
