# geo.py - перевод пикселя кадра в мировые координаты (проекция луча на землю z=0)
import math
import config


def pixel_to_world(u, v, pose, max_range=300.0):
    """
    u, v  - нормированные координаты пикселя [0..1] (0,0 = левый верх)
    pose  - dict: x, y, alt, yaw, pitch_total (рад, + = камера смотрит вниз), aspect (высота/ширина)
    Возвращает (x, y) в мире или None, если луч не пересекает землю.
    """
    f = 0.5 / math.tan(config.FOV / 2.0)        # фокус в долях ширины кадра
    xr = u - 0.5                                 # вправо
    yd = (v - 0.5) * pose.get("aspect", 0.6)     # вниз
    d = pose["pitch_total"]
    fwd_c = f * math.cos(d) - yd * math.sin(d)
    down_c = f * math.sin(d) + yd * math.cos(d)
    if down_c <= 0.02 or pose["alt"] <= 0.1:
        return None
    t = pose["alt"] / down_c
    gf, gr = t * fwd_c, t * xr
    if math.hypot(gf, gr) > max_range:
        return None
    yaw = pose["yaw"]
    wx = pose["x"] + gf * math.cos(yaw) + gr * math.sin(yaw)
    wy = pose["y"] + gf * math.sin(yaw) - gr * math.cos(yaw)
    return (wx, wy)


def meters_per_frame_width(alt, pitch_total):
    """Грубая оценка ширины земли в кадре, м (для оценки площади)."""
    tilt = min(abs(pitch_total), 1.0)
    return 2.0 * (alt / max(math.cos(tilt), 0.3)) * math.tan(config.FOV / 2.0)
