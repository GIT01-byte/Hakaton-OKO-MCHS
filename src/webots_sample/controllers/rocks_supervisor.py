from controller import Supervisor, Node

supervisor = Supervisor()
timestep = int(supervisor.getBasicTimeStep())

# Имена камней точно как в поле name в Webots (на скрине "rock(15)")
rock_names = ["rock(13)", "rock(14)", "rock(15)"] 

root_children = supervisor.getRoot().getField("children")

for name in rock_names:
    # Ищем камень по имени
    rock_node = None
    for i in range(root_children.getCount()):
        child = root_children.getMFNode(i)
        if child.getTypeName() == "Rock":
            name_field = child.getField("name")
            if name_field and name_field.getSFString() == name:
                rock_node = child
                break
                
    if rock_node:
        print(f"Добавляем физику для {name}...")
        physics_field = rock_node.getField("physics")
        
        # Если физики нет (NULL), создаем её
        if physics_field.getSFNode() is None:
            physics_node = Node.create("Physics")
            physics_field.setSFNode(physics_node)
            
            # Настраиваем массу и отключаем статичность
            physics_node.getField("mass").setSFFloat(50.0)
            physics_node.getField("static").setSFBool(False)
    else:
        print(f"Камень {name} не найден!")

print("Камни активированы.")
while supervisor.step(timestep) != -1:
    pass