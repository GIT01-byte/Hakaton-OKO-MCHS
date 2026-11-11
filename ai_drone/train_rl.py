from stable_baselines3 import PPO
from drone_rl_env import WebotsDroneEnv
import os

# Создаем папку для моделей
os.makedirs("rl_models", exist_ok=True)

# Создаем среду
env = WebotsDroneEnv()

# Создаем модель PPO (нейросеть)
# MlpPolicy означает, что мы подаем ей вектор чисел (наши 5 параметров), а не картинку
model = PPO("MlpPolicy", env, verbose=1, tensorboard_log="./ppo_drone_tensorboard/")

print("Начинаем обучение...")
# Обучаем на 10 000 шагов (для теста, реально нужно миллионы)
model.learn(total_timesteps=10000)

# Сохраняем модель
model.save("rl_models/ppo_drone_scan")
print("Обучение завершено и модель сохранена!")
