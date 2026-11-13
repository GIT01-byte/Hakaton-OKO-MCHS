from controller import Supervisor

supervisor = Supervisor()
timestep = int(supervisor.getBasicTimeStep())

# Сочные, "огненные" цвета:
# 0 -> Насыщенный красный
# 1 -> Яркий оранжевый
# 2 -> Теплый желтый (без зелени)
colors = [
    [1.0, 0.05, 0.0],  
    [1.0, 0.45, 0.0],  
    [1.0, 0.85, 0.0]   
]

def find_appearance_node(node):
    if node is None:
        return None
    if node.getTypeName() in ["Material", "PBRAppearance"]:
        return node
    if node.getTypeName() == "Shape":
        app_field = node.getField("appearance")
        if app_field:
            app_node = app_field.getSFNode()
            if app_node:
                res = find_appearance_node(app_node)
                if res: return res
    children_field = node.getField("children")
    if children_field:
        for i in range(children_field.getCount()):
            child = children_field.getMFNode(i)
            res = find_appearance_node(child)
            if res: return res
    return None

appearance_data = []

def find_all_solids(node):
    if node is None:
        return
    def_name = node.getDef()
    
    if def_name and "SOLID" in def_name:
        group_id = -1
        if def_name.startswith("SOLID_1"):
            group_id = 1
        elif def_name.startswith("SOLID_2"):
            group_id = 2
        elif def_name.startswith("SOLID_3"):
            group_id = 3
            
        if group_id != -1:
            app = find_appearance_node(node)
            if app:
                appearance_data.append((app, group_id))
                
    children_field = node.getField("children")
    if children_field:
        for i in range(children_field.getCount()):
            find_all_solids(children_field.getMFNode(i))

find_all_solids(supervisor.getRoot())
print(f"--- Найдено объектов: {len(appearance_data)} ---")

step_count = 0
last_time = 0.0

while supervisor.step(timestep) != -1:
    current_time = supervisor.getTime()

    if current_time - last_time >= 1.0:
        last_time = current_time
        step_count += 1
        
        for app, group_id in appearance_data:
            
            # Бегущий огонь (сдвиг цветов для каждой группы)
            if group_id == 1:
                color_idx = step_count % 3
            elif group_id == 2:
                color_idx = (step_count + 1) % 3
            elif group_id == 3:
                color_idx = (step_count + 2) % 3

            current_color = colors[color_idx]
            
            if app.getTypeName() == "PBRAppearance":
                # 1. Меняем базовый цвет
                color_field = app.getField("baseColor")
                if color_field:
                    color_field.setSFColor(current_color)
                
                # 2. ДЕЛАЕМ ИХ СВЕТЯЩИМИСЯ (суть огня!)
                emissive_field = app.getField("emissiveColor")
                if emissive_field:
                    emissive_field.setSFColor(current_color) # Красим свечение в тот же цвет
                    
                emissive_intensity = app.getField("emissiveIntensity")
                if emissive_intensity:
                    emissive_intensity.setSFFloat(0.8) # Сила свечения (0.8 - самое то, чтобы не слепило)

                # 3. Обновляем шейдер для Webots
                rough_field = app.getField("roughness")
                if rough_field:
                    rough_field.setSFFloat(0.2) # Делаем их чуть более гладкими, чтобы блестели
                    
            else:
                color_field = app.getField("diffuseColor")
                if color_field:
                    color_field.setSFColor(current_color)
        
        print(f"Секунда {int(current_time)} | Огонь горит!")