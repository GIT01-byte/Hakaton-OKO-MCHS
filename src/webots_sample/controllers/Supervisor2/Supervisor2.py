from controller import Supervisor

supervisor = Supervisor()
timestep = int(supervisor.getBasicTimeStep())

# Ищем узел воды, которому мы дали DEF "WATER"
water_node = supervisor.getFromDef("WATER")

# Переменные для анимации текстуры
tex_translation = None
offset_x = 0.0

if water_node is None:
    print("ОШИБКА: Узел воды с DEF 'WATER' не найден! Проверьте имя.")
else:
    try:
        # Пробираемся к текстуре: Fluid -> children -> Shape -> appearance -> textureTransform -> translation
        children = water_node.getField("children")
        shape = children.getMFNode(0)
        
        if shape is None:
            print("ОШИБКА: Внутри Fluid нет Shape. Вода не будет видна!")
        else:
            appearance = shape.getField("appearance").getSFNode()
            
            if appearance is None:
                print("ОШИБКА: Внутри Shape нет appearance (PBRAppearance).")
            else:
                tex_transform = appearance.getField("textureTransform").getSFNode()
                
                if tex_transform is None:
                    print("ОШИБКА: Внутри PBRAppearance нет textureTransform. Добавьте TextureTransform!")
                else:
                    tex_translation = tex_transform.getField("translation")
                    print("--- Анимация воды успешно инициализирована! ---")
    except Exception as e:
        print(f"ОШИБКА при поиске текстуры: {e}")

# Главный цикл симуляции
while supervisor.step(timestep) != -1:
    if tex_translation is not None:
        # Сдвигаем текстуру вдоль оси X (эффект течения)
        offset_x -= 0.01  # <-- Скорость течения (можно менять)
        
        # Если текстура ушла за край, возвращаем её в начало (чтобы течение было бесконечным)
        if offset_x < -1.0:
            offset_x += 1.0
            
        # Применяем смещение (X, Y)
        tex_translation.setSFVec2f([offset_x, 0.0])