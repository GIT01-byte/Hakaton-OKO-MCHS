# mission_fire.py
import mission_common


def update(mission, current_time, sensors, vision_data, last_annotated):
    return mission_common.update("FIRE", mission, current_time, sensors, vision_data, last_annotated)
