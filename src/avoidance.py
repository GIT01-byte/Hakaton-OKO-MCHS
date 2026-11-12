# avoidance.py - облёт препятствий (дома, деревья и т.п.)
#
# Два независимых источника угрозы (используется худший):
#   1) Дальномеры / лидар Webots (если установлены на дроне) - расстояние в метрах.
#   2) Монокулярное зрение: "наплыв" кадра (looming) по оптическому потоку.
#      Объект, к которому летим, расширяется в кадре; скорость расширения даёт
#      время до столкновения  tau = 1 / (скорость расширения). Глубина не нужна.
#
# Стратегия: торможение -> подъём ступенями по AVOID_CLIMB_STEP (над крышей/кроной) ->
# если на потолке высоты всё ещё преграда - боковой манёвр -> держим высоту,
# пока не пролетим препятствие, затем возвращаем штатную высоту.
import math
import cv2
import numpy as np
import config
from logger import Logger

INF = float("inf")


class RangeSensors:
    def __init__(self, robot, timestep):
        self.ds = {}
        for sector, name in config.DIST_SENSORS.items():
            dev = robot.getDevice(name) if name else None
            if dev:
                dev.enable(timestep)
                self.ds[sector] = dev
        self.lidar = robot.getDevice(config.LIDAR_NAME) if config.LIDAR_NAME else None
        if self.lidar:
            self.lidar.enable(timestep)
        self.available = bool(self.ds) or bool(self.lidar)

    def read(self):
        out = {"left": INF, "center": INF, "right": INF}
        for s, dev in self.ds.items():
            v = dev.getValue()
            if math.isfinite(v) and v < config.RANGE_MAX * 0.98:
                out[s] = v
        if self.lidar:
            rng = self.lidar.getRangeImage()
            res = self.lidar.getHorizontalResolution()
            fov = self.lidar.getFov()
            for i in range(res):  # первый слой
                r = rng[i]
                if not math.isfinite(r) or r <= 0.05 or r >= config.RANGE_MAX * 0.98:
                    continue
                ang = -fov / 2 + fov * i / max(res - 1, 1)
                if config.LIDAR_FLIP:
                    ang = -ang
                sector = "center" if abs(ang) < 0.21 else ("left" if ang > 0 else "right")
                out[sector] = min(out[sector], r)
        return out


class VisualLooming:
    W, H = 160, 96

    def __init__(self):
        self.prev = None
        self.rate = {"left": 0.0, "center": 0.0, "right": 0.0}
        xs = np.arange(self.W, dtype=np.float32) - self.W / 2
        ys = np.arange(self.H, dtype=np.float32) - self.H / 2
        self.X, self.Y = np.meshgrid(xs, ys)

    def reset(self):
        self.prev = None
        self.rate = {k: 0.0 for k in self.rate}

    def update(self, bgr, dt):
        g = cv2.GaussianBlur(
            cv2.cvtColor(cv2.resize(bgr, (self.W, self.H)), cv2.COLOR_BGR2GRAY), (5, 5), 0)
        taus = {"left": INF, "center": INF, "right": INF}
        if self.prev is None or dt <= 1e-3:
            self.prev = g
            return taus

        flow = cv2.calcOpticalFlowFarneback(self.prev, g, None, 0.5, 2, 9, 2, 5, 1.1, 0)
        self.prev = g
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0)
        gy = cv2.Sobel(g, cv2.CV_32F, 0, 1)
        tex = (np.abs(gx) + np.abs(gy)) > config.LOOM_TEXTURE

        y0, y1 = int(self.H * 0.30), int(self.H * 0.65)  # полоса вокруг горизонта
        third = self.W // 3
        sectors = {"left": (0, third), "center": (third, 2 * third), "right": (2 * third, self.W)}
        for name, (x0, x1) in sectors.items():
            sl = (slice(y0, y1), slice(x0, x1))
            m = tex[sl]
            if m.mean() < 0.08:          # пусто/небо: оценивать нечего
                self.rate[name] *= 0.5
                continue
            rx, ry = self.X[sl][m], self.Y[sl][m]
            fx, fy = flow[..., 0][sl][m], flow[..., 1][sl][m]
            # поток при приближении: flow = e * r, e - относительное расширение за интервал кадров
            e = float((fx * rx + fy * ry).sum() / ((rx ** 2 + ry ** 2).sum() + 1e-6))
            self.rate[name] = 0.6 * self.rate[name] + 0.4 * (e / dt)
            if self.rate[name] > config.LOOM_MIN_RATE:
                taus[name] = 1.0 / self.rate[name]
        return taus


class ObstacleAvoider:
    def __init__(self, robot, timestep):
        self.ranges = RangeSensors(robot, timestep)
        self.looming = VisualLooming()
        self.dist = {"left": INF, "center": INF, "right": INF}
        self.tau = {"left": INF, "center": INF, "right": INF}
        self.state = "CLEAR"
        self.t0 = 0.0
        self.raise_alt = 0.0
        self.pass_until = 0.0
        self.clear_since = None
        self.side = 1
        Logger.event("AVOID_INIT", {"ranges": self.ranges.available})

    def reset(self):
        self.state = "CLEAR"
        self.looming.reset()

    def update_vision(self, bgr, dt, cam_total_pitch):
        """Вызывать при каждом новом кадре."""
        if abs(cam_total_pitch) > config.AVOID_MAX_CAM_PITCH:
            self.looming.reset()
            self.tau = {"left": INF, "center": INF, "right": INF}
            return
        self.tau = self.looming.update(bgr, dt)

    def _levels(self):
        self.dist = self.ranges.read() if self.ranges.available else self.dist
        lv = {}
        for s in ("left", "center", "right"):
            d, tau = self.dist[s], self.tau[s]
            if d < config.DIST_DANGER or tau < config.TAU_DANGER:
                lv[s] = 2
            elif d < config.DIST_WARN or tau < config.TAU_WARN:
                lv[s] = 1
            else:
                lv[s] = 0
        return lv

    def _enter(self, state, t):
        if state != self.state:
            Logger.event("AVOID", {"from": self.state, "to": state})
        self.state, self.t0 = state, t

    def _start_climb(self, alt, t):
        self.raise_alt = min(alt + config.AVOID_CLIMB_STEP, config.OBSTACLE_MAX_ALT)
        self.clear_since = None
        self._enter("CLIMB", t)

    def process(self, cmd, t, sensors, mode):
        if mode in ("TAKEOFF", "LANDING", "FINISHED"):
            self.state = "CLEAR"
            return cmd

        alt = sensors["gps"][2]
        lv = self._levels()
        moving = cmd["target_pitch"] < -0.1
        out = dict(cmd)
        base_alt = cmd["target_altitude"]

        if self.state == "CLEAR":
            if moving and lv["center"] == 2:
                self._enter("BRAKE", t)
            elif moving and lv["center"] == 1:
                out["target_pitch"] *= 0.4
                self._start_climb(alt, t)
            elif moving and (lv["left"] or lv["right"]):
                out["target_pitch"] *= 0.6
                if lv["left"] > lv["right"]:
                    out["target_yaw"] -= config.AVOID_YAW_BIAS   # преграда слева -> вправо
                elif lv["right"] > lv["left"]:
                    out["target_yaw"] += config.AVOID_YAW_BIAS

        if self.state == "BRAKE":
            out["target_pitch"] = config.AVOID_BRAKE_PITCH       # + = назад: гасим скорость
            out["target_yaw"] = 0.0
            if t - self.t0 > config.AVOID_BRAKE_TIME:
                self._start_climb(alt, t)

        elif self.state == "CLIMB":
            out["target_pitch"] = 0.0 if lv["center"] == 2 else cmd["target_pitch"] * 0.3
            out["target_altitude"] = max(base_alt, self.raise_alt)
            if lv["center"] >= 1:
                self.clear_since = None
                at_level = alt >= self.raise_alt - 0.7
                if at_level and self.raise_alt < config.OBSTACLE_MAX_ALT:
                    self.raise_alt = min(self.raise_alt + config.AVOID_CLIMB_STEP,
                                         config.OBSTACLE_MAX_ALT)
                elif at_level and t - self.t0 > 4.0:
                    # потолок высоты, а путь закрыт - обходим сбоку (+yaw = влево)
                    self.side = -1 if lv["left"] > lv["right"] else 1
                    self._enter("SIDESTEP", t)
            else:
                if self.clear_since is None:
                    self.clear_since = t
                elif (t - self.clear_since > config.AVOID_CLEAR_CONFIRM
                      and alt >= self.raise_alt - 1.0):
                    self.pass_until = t + config.AVOID_PASS_HOLD
                    self._enter("PASS", t)

        elif self.state == "SIDESTEP":
            out["target_altitude"] = max(base_alt, self.raise_alt)
            if t - self.t0 < 1.5:                                 # разворот на месте
                out["target_pitch"], out["target_yaw"] = 0.0, self.side * 1.0
            else:                                                 # пролёт вбок
                out["target_pitch"] = cmd["target_pitch"] * 0.5
                out["target_yaw"] = self.side * 0.4
            if t - self.t0 > 4.5:
                self.pass_until = t + config.AVOID_PASS_HOLD
                self._enter("PASS", t)

        elif self.state == "PASS":
            out["target_altitude"] = max(base_alt, self.raise_alt)
            if moving and lv["center"] >= 1:
                self._start_climb(max(alt, self.raise_alt), t)
            elif t > self.pass_until:
                self._enter("CLEAR", t)

        return out
