import gymnasium as gym
from gymnasium import spaces
import numpy as np
import math
import cv2
from ultralytics import YOLO
from controller import Supervisor


class WebotsDroneEnv(gym.Env):
    def __init__(self):
        super(WebotsDroneEnv, self).__init__()

        # Используем Supervisor вместо Robot
        self.supervisor = Supervisor()
        self.timestep = int(self.supervisor.getBasicTimeStep())

        # Датчики
        self.imu = self.supervisor.getDevice("inertial unit")
        self.imu.enable(self.timestep)
        self.gps = self.supervisor.getDevice("gps")
        self.gps.enable(self.timestep)
        self.gyro = self.supervisor.getDevice("gyro")
        self.gyro.enable(self.timestep)
        self.camera = self.supervisor.getDevice("camera")
        self.camera.enable(self.timestep)

        # Моторы
        self.fl = self.supervisor.getDevice("front left propeller")
        self.fr = self.supervisor.getDevice("front right propeller")
        self.rl = self.supervisor.getDevice("rear left propeller")
        self.rr = self.supervisor.getDevice("rear right propeller")
        for m in [self.fl, self.fr, self.rl, self.rr]:
            m.setPosition(float("inf"))
            m.setVelocity(0.0)

        # YOLO
        self.model = YOLO("yolov8n.pt")

        # Пространства
        self.action_space = spaces.Discrete(4)
        self.observation_space = spaces.Box(
            low=-1.0, high=1.0, shape=(5,), dtype=np.float32
        )
        self.target_altitude = 2.0

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)

        # Получаем узел дрона по имени DEF
        drone_node = self.supervisor.getFromDef("DRONE")

        if drone_node:
            # Телепортируем дрон на старт (X=0, Y=0, Z=2)
            drone_node.getField("translation").setSFVec3f([0.0, 0.0, 2.0])
            # Выравниваем его (нулевой поворот)
            drone_node.getField("rotation").setSFRotation([0.0, 0.0, 1.0, 0.0])
            # Обнуляем скорость физического тела
            drone_node.setVelocity([0.0] * 6)

        # Ждем пару шагов, чтобы физика применила телепортацию
        for _ in range(10):
            self.supervisor.step(self.timestep)

        return self._get_obs(), {}

    def _get_obs(self):
        roll = self.imu.getRollPitchYaw()[0]
        pitch = self.imu.getRollPitchYaw()[1]
        altitude = self.gps.getValues()[2]

        raw_image = self.camera.getImage()
        yolo_offset_x = 0.0
        yolo_area = 0.0

        if raw_image:
            image = np.frombuffer(raw_image, np.uint8).reshape(
                (self.camera.getHeight(), self.camera.getWidth(), 4)
            )
            bgr = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            results = self.model(bgr, conf=0.5, classes=[0], verbose=False)

            if len(results[0].boxes) > 0:
                box = results[0].boxes[0]
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                center_x = (x1 + x2) / 2
                yolo_offset_x = (center_x - (self.camera.getWidth() / 2)) / (
                    self.camera.getWidth() / 2
                )
                yolo_area = ((x2 - x1) * (y2 - y1)) / (
                    self.camera.getWidth() * self.camera.getHeight()
                )

        return np.array(
            [yolo_offset_x, yolo_area, altitude, roll, pitch], dtype=np.float32
        )

    def step(self, action):
        self._apply_pid(action)
        self.supervisor.step(self.timestep)
        obs = self._get_obs()
        reward, done = self._compute_reward(obs)
        return obs, reward, done, False, {}

    def _apply_pid(self, action):
        pitch_disturbance = -5.0 if action == 1 else 0.0
        roll_disturbance = 2.0 if action == 2 else (-2.0 if action == 3 else 0.0)

        roll = self.imu.getRollPitchYaw()[0]
        pitch = self.imu.getRollPitchYaw()[1]
        altitude = self.gps.getValues()[2]

        roll_input = 50.0 * roll + self.gyro.getValues()[0] + roll_disturbance
        pitch_input = 30.0 * pitch + self.gyro.getValues()[1] + pitch_disturbance

        clamped_diff = max(-1.0, min(1.0, self.target_altitude - altitude + 0.6))
        vertical_input = 3.0 * math.pow(clamped_diff, 3.0)

        fl_in = 68.5 + vertical_input - roll_input + pitch_input
        fr_in = 68.5 + vertical_input + roll_input + pitch_input
        rl_in = 68.5 + vertical_input - roll_input - pitch_input
        rr_in = 68.5 + vertical_input + roll_input - pitch_input

        self.fl.setVelocity(max(0, fl_in))
        self.fr.setVelocity(-max(0, fr_in))
        self.rl.setVelocity(-max(0, rl_in))
        self.rr.setVelocity(max(0, rr_in))

    def _compute_reward(self, obs):
        yolo_offset_x, yolo_area, altitude, roll, pitch = obs
        reward = 0.0
        done = False

        # Штраф за падение или переворот (если дрон наклонился больше 90 градусов)
        if altitude < 0.5 or abs(roll) > 1.57 or abs(pitch) > 1.57:
            return -100.0, True

        if yolo_area > 0:
            reward += 1.0
            reward += (1.0 - abs(yolo_offset_x)) * 2.0
            reward += yolo_area * 5.0
            if yolo_area > 0.3:
                reward += 10.0
                done = True
        else:
            reward -= 0.1

        return reward, done
