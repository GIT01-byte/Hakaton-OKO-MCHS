# main.py
from controller import Supervisor
import cv2
import numpy as np
import math
import time
import config
import vision
import fsm
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

mission = fsm.MissionFSM()
fire_detector = vision.ContrastFireDetector()
small_img_buffer = np.zeros((config.YOLO_H, config.YOLO_W, 3), dtype=np.uint8)
last_telemetry_time = 0.0
frame_count = 0
last_annotated = None
smooth_pitch_disturbance = 0.0

vision_data = {
    "water_ratio": 0.0,
    "wet_edges": [],
    "is_fire": False,
    "fire_score": 0.0,
    "is_landslide": False,
    "is_landfill": False,
    "person_detected": False,
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
                    Logger.event("RESET")
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
                    mission.reset()
            except vision.queue.Empty:
                break

        if altitude > 5.0:
            mission.has_taken_off = True
        if altitude < 0.5 and current_time > 3.0 and mission.has_taken_off:
            Logger.event("CRASH")
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

                try:
                    vision.frame_queue.put_nowait(small_img_buffer.copy())
                except vision.queue.Full:
                    pass

                w_ratio, w_edges = vision.detect_flood_accurate(
                    small_img_buffer, pitch, mission.target_cam_pitch
                )

                is_fire, fire_score = fire_detector.detect(small_img_buffer)
                is_landslide = vision.detect_landslide(small_img_buffer)
                is_landfill = vision.detect_landfill(small_img_buffer)

                person_detected, yolo_boxes = False, []
                try:
                    person_detected, yolo_boxes = vision.result_queue.get_nowait()
                except vision.queue.Empty:
                    pass

                last_annotated = bgr_image.copy()
                cv2.putText(
                    last_annotated,
                    f"Mode: {mission.mode}",
                    (20, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 255),
                    2,
                )
                cv2.putText(
                    last_annotated,
                    f"Water: {w_ratio*100:.1f}%",
                    (20, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 0, 0),
                    2,
                )

                # Вывод Fire Score для отладки (можно убрать позже)
                cv2.putText(
                    last_annotated,
                    f"Fire Score: {fire_score:.4f}",
                    (20, 90),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 165, 255),
                    2,
                )

                vision_data["water_ratio"] = w_ratio
                vision_data["wet_edges"] = w_edges
                vision_data["is_fire"] = is_fire
                vision_data["fire_score"] = fire_score
                vision_data["is_landslide"] = is_landslide
                vision_data["is_landfill"] = is_landfill
                vision_data["person_detected"] = person_detected

        frame_count += 1

        # --- FSM ---
        sensors = {"gps": (gps_x, gps_y, altitude), "yaw": yaw}
        commands = mission.update(current_time, sensors, vision_data, last_annotated)

        if commands is None:
            break

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

        # 🔧 ЛОГИРОВАНИЕ ТЕЛЕМЕТРИИ
        if current_time - last_telemetry_time >= config.TELEMETRY_INTERVAL:
            Logger.telemetry(
                current_time,
                gps_x,
                gps_y,
                altitude,
                mission.mode,
                vision_data.get("water_ratio", 0),
                vision_data.get("fire_score", 0),
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
    print("✅ Система остановлена.")
