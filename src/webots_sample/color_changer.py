from controller import Supervisor

supervisor = Supervisor()
timestep = int(supervisor.getBasicTimeStep())

# Имена DEF-узлов, которые мы создали в Шаге 1
solid_defs = ["SOLID_1", "SOLID_2", "SOLID_3"]

# Ваша палитра цветов (R, G, B). В Webots значения от 0.0 до 1.0
colors = [
    [1.0, 0.15, 0.0],  # r1g0.15b0
    [1.0, 0.25, 0.0],  # r1g0.25b0
    [1.0, 0.50, 0.0]   # r1g0.5b0
]

# Функция для поиска узла цвета (Material или PBRAppearance) внутри Solid
def get_appearance_node(def_name):
    node = supervisor.getFromDef(def_name)
    if not node:
        print(f"Ошибка: узел {def_name} не найден!")
        return None

    children = node.getField("children")
    if not children:
        return None

    for i in range(children.getCount()):
        child = children.getMFNode(i)
        if child.getTypeName() == "Shape":
            appearance_field = child.getField("appearance")
            if appearance_field:
                return appearance_field.getSFNode()
    return None

# Собираем все узлы цвета один раз при старте
appearance_nodes = []
for s_def in solid_defs:
    app = get_appearance_node(s_def)
    if app:
        appearance_nodes.append(app)
    else:
        print(f"Внимание: у {s_def} не найден Shape с appearance (Material)")

color_index = 0
last_time = 0.0

print("Скрипт смены цвета запущен!")

# Главный цикл симуляции
while supervisor.step(timestep) != -1:
    current_time = supervisor.getTime()

    # Проверяем, прошла ли ровно 1 секунда с последней смены
    if current_time - last_time >= 1.0:
        last_time = current_time
        
        # Берем следующий цвет из списка
        color = colors[color_index]
        
        # Применяем цвет ко всем трем объектам
        for app in appearance_nodes:
            if app.getTypeName() == "PBRAppearance":
                color_field = app.getField("baseColor")
            else:
                color_field = app.getField("diffuseColor")
                
            if color_field:
                color_field.setSFColor(color)
        
        print(f"Время: {current_time:.1f}с | Цвет изменен на: R={color[0]}, G={color[1]}, B={color[2]}")
        
        # Переключаем индекс на следующий цвет (если дошли до конца - идем в начало)
        color_index = (color_index + 1) % len(colors)C:\Users\123\OneDrive\Документы\mavicC:\Users\123\OneDrive\Документы\mavic