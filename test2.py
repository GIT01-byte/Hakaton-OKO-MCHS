from controller import Robot
import math

robot = Robot()
timestep = int(robot.getBasicTimeStep())

# 1. Датчики
imu = robot.getDevice("inertial unit")
imu.enable(timestep)
gyro = robot.getDevice("gyro")
gyro.enable(timestep)
gps = robot.getDevice("gps")
gps.enable(timestep)

# 2. Моторы
fl = robot.getDevice("front left propeller")
fr = robot.getDevice("front right propeller")
rl = robot.getDevice("rear left propeller")
rr = robot.getDevice("rear right propeller")

for m in [fl, fr, rl, rr]:
    m.setPosition(float("inf"))
    m.setVelocity(0.0)

# 3. Константы PID
K_VERTICAL_THRUST = 68.5
K_VERTICAL_OFFSET = 0.6
K_VERTICAL_P = 3.0
K_ROLL_P = 50.0
K_PITCH_P = 30.0
K_YAW_P = 2.0

target_altitude = 2.0
target_yaw = 0.0

print("Контроллер запущен. Режим супер-стабилизации.")

while robot.step(timestep) != -1:
    # Чтение датчиков (углы в радианах)
    roll = imu.getRollPitchYaw()[0]
    pitch = imu.getRollPitchYaw()[1]
    yaw = imu.getRollPitchYaw()[2]
    altitude = gps.getValues()[2]

    roll_velocity = gyro.getValues()[0]
    pitch_velocity = gyro.getValues()[1]
    yaw_velocity = gyro.getValues()[2]

    # Нормализация углов (чтобы не было скачков на 180 градусах)
    roll = math.atan2(math.sin(roll), math.cos(roll))
    pitch = math.atan2(math.sin(pitch), math.cos(pitch))

    # Нормализация ошибки рыскания
    yaw_error = target_yaw - yaw
    if yaw_error > math.pi:
        yaw_error -= 2 * math.pi
    elif yaw_error < -math.pi:
        yaw_error += 2 * math.pi

    # --- БЛОК КОМПЕНСАЦИИ НАКЛОНА (Спасает от падения при 45 градусах) ---
    # cos(roll) * cos(pitch) дает коэффициент потери тяги.
    # Мы делим базовую тягу на этот коэффициент, чтобы дрон не падал.
    tilt_compensation = max(0.2, math.cos(roll) * math.cos(pitch))
    base_thrust = K_VERTICAL_THRUST / tilt_compensation

    # Вычисление PID
    roll_input = K_ROLL_P * max(-1.0, min(1.0, roll)) + roll_velocity
    pitch_input = K_PITCH_P * max(-1.0, min(1.0, pitch)) + pitch_velocity
    yaw_input = K_YAW_P * yaw_error + yaw_velocity

    clamped_diff_alt = max(
        -1.0, min(1.0, target_altitude - altitude + K_VERTICAL_OFFSET)
    )
    vertical_input = K_VERTICAL_P * math.pow(clamped_diff_alt, 3.0)

    # Микширование тяги
    fl_input = base_thrust + vertical_input - roll_input + pitch_input - yaw_input
    fr_input = base_thrust + vertical_input + roll_input + pitch_input + yaw_input
    rl_input = base_thrust + vertical_input - roll_input - pitch_input + yaw_input
    rr_input = base_thrust + vertical_input + roll_input - pitch_input - yaw_input

    # --- ЗАЩИТА ОТ ПРОВАЛА В МИНУС ---
    # Если мотор уходит в минус (крутится назад), он теряет тягу.
    # Ограничиваем минимальное значение, чтобы дрон всегда имел сцепление с воздухом.
    fl_input = max(0.0, fl_input)
    fr_input = max(0.0, fr_input)
    rl_input = max(0.0, rl_input)
    rr_input = max(0.0, rr_input)

    # Отправка команд (с компенсацией реактивного момента)
    fl.setVelocity(fl_input)
    fr.setVelocity(-fr_input)
    rl.setVelocity(-rl_input)
    rr.setVelocity(rr_input)
