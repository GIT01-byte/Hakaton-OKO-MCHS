# main.py
from controller import Supervisor
import cv2
import numpy as np
import math
import time
import config
import vision
import geo
import fsm
from avoidance import ObstacleAvoider
from reporter import IncidentReporter
from logger import Logger

print("Инициализация контроллера...")
Logger.init()

supervisor = Supervisor()
timestep = int(supervisor.getBasicTimeStep())

imu = supervisor.getDevice("inertial unit")
imu.enable(timestep)
gps = supervisor.getDevice("gps")
gps.enable(timestep)
gyro = supervisor.getDevice("gyro")
gyro.enable(timestep)
camera = supervisor.getDevice("camera")
camera.enable(timestep)

camera_roll_motor = supervisor.getDevice("camera roll")
camera_pitch_motor = supervisor.getDevice("camera pitch")

fl = supervisor.getDevice("front left propeller")
fr = supervisor.getDevice("front right propeller")
rl = supervisor.getDevice("rear left propeller")
rr = supervisor.getDevice("rear right propeller")

for m in [fl, fr, rl, rr]:
    m.setPosition(float("inf"))
    m.setVelocity(0.0)

drone_node = supervisor.getFromDef(config.DRONE_NODE_NAME)
vision.start_threads()
avoider = ObstacleAvoider(supervisor, timestep)


def reset_drone(event="RESET"):
    Logger.event(event)
    if drone_node is not None:
        fl.setVelocity(0)
        fr.setVelocity(0)
        rl.setVelocity(0)
        rr.setVelocity(0)
        drone_node.getField("translation").setSFVec3f(
            [config.START_X, config.START_Y, config.START_Z]
        )
        drone_node.getField("rotation").setSFRotation([0.0, 0.0, 1.0, 0.0])
        drone_node.setVelocity([0.0] * 6)
        drone_node.resetPhysics()
        avoider.reset()


def draw_boxes(img, boxes, color, label):
    h, w = img.shape[:2]
    for b in boxes:
        box = b["box"] if isinstance(b, dict) else b
        p1 = (int(box[0] * w), int(box[1] * h))
        p2 = (int(box[2] * w), int(box[3] * h))
        cv2.rectangle(img, p1, p2, color, 2)
        txt = (
            label
            if not isinstance(b, dict)
            else f"{b.get('label', label)} {b['conf']:.2f}"
        )
        cv2.putText(
            img,
            txt,
            (p1[0], max(12, p1[1] - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2,
        )


reporter = IncidentReporter()
mission = fsm.MissionFSM(reporter)
fire_detector = vision.ContrastFireDetector()
person_tracker = vision.PersonTracker()
small_img_buffer = np.zeros((config.YOLO_H, config.YOLO_W, 3), dtype=np.uint8)
last_telemetry_time = 0.0
last_frame_time = 0.0
frame_count = 0
last_annotated = None
smooth_pitch_disturbance = 0.0
last_dets = {"persons": [], "animals": [], "trash": [], "fire_ml": []}

vision_data = {
    "water_ratio": 0.0,
    "wet_edges": [],
    "water_world": None,
    "is_fire": False,
    "fire_score": 0.0,
    "fire_world": None,
    "is_landslide": False,
    "landslide_ratio": 0.0,
    "landslide_world": None,
    "is_landfill": False,
    "landfill_ratio": 0.0,
    "landfill_world": None,
    "person_detected": False,
    "person_world": None,
    "person_conf": 0.0,
}

try:
    while True:
        if supervisor.step(timestep) == -1:
            break

        current_time = supervisor.getTime()
        roll, pitch, yaw = imu.getRollPitchYaw()
        gps_x, gps_y, altitude = gps.getValues()
        roll_velocity = gyro.getValues()[0]
        pitch_velocity = gyro.getValues()[1]

        # --- Клавиши ---
        while True:
            try:
                key = vision.key_queue.get_nowait()
                if key == 27:
                    raise SystemExit
                elif key == ord("r") or key == ord("к"):
                    reset_drone()
                    mission.reset()
            except vision.queue.Empty:
                break

        if altitude > 5.0:
            mission.has_taken_off = True
        if altitude < 0.5 and current_time > 3.0 and mission.has_taken_off:
            reset_drone("CRASH")
            mission.reset()
            continue

        # --- ЗРЕНИЕ ---
        if frame_count % config.FRAME_SKIP == 0:
            raw_image = camera.getImage()
            if raw_image:
                image = np.frombuffer(raw_image, np.uint8).reshape(
                    (camera.getHeight(), camera.getWidth(), 4)
                )
                bgr_image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
                cv2.resize(
                    bgr_image, (config.YOLO_W, config.YOLO_H), dst=small_img_buffer
                )

                cam_total_pitch = (
                    pitch + mission.target_cam_pitch
                )  # + = камера смотрит вниз
                pose = {
                    "x": gps_x,
                    "y": gps_y,
                    "alt": altitude,
                    "yaw": yaw,
                    "pitch_total": cam_total_pitch,
                    "aspect": camera.getHeight() / camera.getWidth(),
                }

                # нейросеть: кадр в повышенном разрешении + поза на момент съёмки
                try:
                    vision.frame_queue.put_nowait(
                        (
                            cv2.resize(
                                bgr_image, (config.YOLO_DET_W, config.YOLO_DET_H)
                            ),
                            pose,
                        )
                    )
                except vision.queue.Full:
                    pass

                # результаты нейросети (люди / животные / мусор)
                try:
                    last_dets, det_pose = vision.result_queue.get_nowait()
                    person_tracker.update(last_dets["persons"], det_pose)
                except vision.queue.Empty:
                    pass

                # классический CV
                w_ratio, w_edges, w_c = vision.detect_flood_accurate(
                    small_img_buffer, pitch, mission.target_cam_pitch
                )
                is_fire, fire_score = fire_detector.detect(small_img_buffer)
                fire_c = fire_detector.info["centroid"]
                if last_dets["fire_ml"]:  # дообученная модель огня, если подключена
                    b = last_dets["fire_ml"][0]
                    is_fire, fire_c = True, ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
                is_landslide, slide_ratio, slide_c = vision.detect_landslide(
                    small_img_buffer
                )
                is_landfill, fill_ratio, fill_c = vision.detect_landfill(
                    small_img_buffer, len(last_dets["trash"])
                )

                def world(c):
                    return geo.pixel_to_world(c[0], c[1], pose) if c else None

                vision_data = {
                    "water_ratio": w_ratio,
                    "wet_edges": w_edges,
                    "water_world": world(w_c),
                    "is_fire": is_fire,
                    "fire_score": fire_score,
                    "fire_world": world(fire_c),
                    "is_landslide": is_landslide,
                    "landslide_ratio": slide_ratio,
                    "landslide_world": world(slide_c),
                    "is_landfill": is_landfill,
                    "landfill_ratio": fill_ratio,
                    "landfill_world": world(fill_c),
                    "person_detected": person_tracker.confirmed,
                    "person_world": person_tracker.position,
                    "person_conf": person_tracker.conf,
                }

                # объезд препятствий: зрение (поток) - на каждом новом кадре
                avoider.update_vision(
                    bgr_image,
                    max(current_time - last_frame_time, 1e-3),
                    cam_total_pitch,
                )
                last_frame_time = current_time

                # --- Визуализация ---
                last_annotated = bgr_image.copy()
                draw_boxes(last_annotated, last_dets["persons"], (0, 255, 0), "PERSON")
                draw_boxes(
                    last_annotated, last_dets["animals"], (0, 165, 255), "ANIMAL"
                )
                draw_boxes(last_annotated, last_dets["trash"], (255, 0, 255), "TRASH")
                draw_boxes(last_annotated, last_dets["fire_ml"], (0, 0, 255), "FIRE")
                lines = [
                    (f"Mode: {mission.mode}  Avoid: {avoider.state}", (0, 255, 255)),
                    (
                        f"Water: {w_ratio*100:.1f}%  Fire Score: {fire_score:.4f}",
                        (255, 0, 0),
                    ),
                    (
                        f"Slide: {slide_ratio*100:.0f}%  Landfill: {fill_ratio*100:.0f}%",
                        (0, 128, 255),
                    ),
                    (
                        f"Cam Pitch: {math.degrees(cam_total_pitch):.0f} deg",
                        (0, 255, 0),
                    ),
                    (
                        f"Persons: {len(last_dets['persons'])} (confirmed={person_tracker.confirmed})  "
                        f"Animals: {len(last_dets['animals'])}",
                        (0, 255, 0),
                    ),
                ]
                for i, (txt, col) in enumerate(lines):
                    cv2.putText(
                        last_annotated,
                        txt,
                        (20, 30 + 28 * i),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        col,
                        2,
                    )

        frame_count += 1

        # --- FSM ---
        sensors = {"gps": (gps_x, gps_y, altitude), "yaw": yaw}
        commands = mission.update(current_time, sensors, vision_data, last_annotated)

        if commands is None:
            break

        # --- ОБЛЁТ ПРЕПЯТСТВИЙ (поверх команд миссии) ---
        commands = avoider.process(commands, current_time, sensors, mission.mode)

        target_pitch_dist = commands["target_pitch"]
        yaw_disturbance = commands["target_yaw"]
        target_altitude = commands["target_altitude"]
        target_cam_pitch = commands["target_cam_pitch"]

        # --- КАМЕРА ---
        if camera_pitch_motor:
            camera_pitch_motor.setPosition(
                max(-0.5, min(0.5, target_cam_pitch - 0.1 * pitch_velocity))
            )
        if camera_roll_motor:
            camera_roll_motor.setPosition(max(-0.5, min(0.5, -0.05 * roll_velocity)))

        # --- МОТОРЫ ---
        smooth_pitch_disturbance = (
            smooth_pitch_disturbance * 0.95 + target_pitch_dist * 0.05
        )
        pitch_disturbance = smooth_pitch_disturbance

        roll_input = config.K_ROLL_P * max(-1.0, min(1.0, roll)) + roll_velocity
        pitch_input = (
            config.K_PITCH_P * max(-1.0, min(1.0, pitch))
            + pitch_velocity
            + pitch_disturbance
        )
        yaw_input = yaw_disturbance

        clamped_diff_alt = max(
            -1.0, min(1.0, target_altitude - altitude + config.K_VERTICAL_OFFSET)
        )
        vertical_input = config.K_VERTICAL_P * math.pow(clamped_diff_alt, 3.0)

        fl_in = (
            config.K_VERTICAL_THRUST
            + vertical_input
            - roll_input
            + pitch_input
            - yaw_input
        )
        fr_in = (
            config.K_VERTICAL_THRUST
            + vertical_input
            + roll_input
            + pitch_input
            + yaw_input
        )
        rl_in = (
            config.K_VERTICAL_THRUST
            + vertical_input
            - roll_input
            - pitch_input
            + yaw_input
        )
        rr_in = (
            config.K_VERTICAL_THRUST
            + vertical_input
            + roll_input
            - pitch_input
            - yaw_input
        )

        fl.setVelocity(max(0.0, fl_in))
        fr.setVelocity(-max(0.0, fr_in))
        rl.setVelocity(-max(0.0, rl_in))
        rr.setVelocity(max(0.0, rr_in))

        if last_annotated is not None:
            try:
                vision.vis_queue.put_nowait(last_annotated)
            except vision.queue.Full:
                pass

        if current_time - last_telemetry_time >= config.TELEMETRY_INTERVAL:
            Logger.telemetry(
                current_time,
                gps_x,
                gps_y,
                altitude,
                mission.mode,
                vision_data.get("water_ratio", 0),
                vision_data.get("fire_score", 0),
                avoider.state,
                len(last_dets["persons"]),
            )
            last_telemetry_time = current_time

except (KeyboardInterrupt, SystemExit):
    print("\nЗавершение работы...")

finally:
    try:
        vision.vis_queue.put_nowait(None)
    except vision.queue.Full:
        pass
    try:
        vision.frame_queue.put_nowait(None)
    except vision.queue.Full:
        pass
    time.sleep(0.2)
    cv2.destroyAllWindows()
    Logger.finish_mission()
    print("✅ Система остановлена.")
