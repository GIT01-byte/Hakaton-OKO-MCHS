from controller import Supervisor

# Инициализация Supervisor (вместо Robot)
supervisor = Supervisor()
timestep = int(supervisor.getBasicTimeStep())

# Получаем узел дрона по DEF-имени (убедись, что в Webots дрон назван "DRONE")
drone_node = supervisor.getFromDef("DRONE")
if drone_node is None:
    raise RuntimeError("Узел с DEF-именем 'DRONE' не найден!")


def reset_drone_and_camera():
    # 1. Телепортация в начальную позицию (например, X=0, Y=0, Z=2)
    translation_field = drone_node.getField("translation")
    translation_field.setSFVec3f([0.0, 0.0, 2.0])

    # 2. Сброс ориентации (например, без поворота)
    rotation_field = drone_node.getField("rotation")
    rotation_field.setSFRotation([0.0, 0.0, 1.0, 0.0])

    # 3. Обнуление линейной и угловой скорости (6 компонентов)
    drone_node.setVelocity([0.0] * 6)

    # 4. Сброс физики (очистка накопленных сил и импульсов)
    drone_node.resetPhysics()

    # 5. Сброс положения камеры (если она управляется моторами)
    # Значения position зависят от модели; 0.0 — нейтральное положение.
    camera_pitch_motor = supervisor.getDevice("camera pitch")
    camera_roll_motor = supervisor.getDevice("camera roll")
    if camera_pitch_motor:
        camera_pitch_motor.setPosition(0.0)
    if camera_roll_motor:
        camera_roll_motor.setPosition(0.0)

    # 6. Прокрутить один шаг симуляции, чтобы изменения применились
    supervisor.step(timestep)
