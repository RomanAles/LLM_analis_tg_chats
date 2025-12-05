import os
from transformers import AutoModelForCausalLM, AutoTokenizer

# === Папки на D: ===
CACHE_DIR = r"D:\huggingface_cache"
TEMP_DIR = r"D:\huggingface_temp"

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

# === Переменные окружения ===
os.environ["HF_HOME"] = CACHE_DIR   # кэш HuggingFace
os.environ["TRANSFORMERS_CACHE"] = CACHE_DIR
os.environ["HF_DATASETS_CACHE"] = CACHE_DIR
os.environ["HF_METRICS_CACHE"] = CACHE_DIR
os.environ["TMP"] = TEMP_DIR         # временные файлы
os.environ["TEMP"] = TEMP_DIR

# === Модель ===
MODEL_ID = "mistralai/Mistral-7B-Instruct-v0.3"

print("Загрузка токенизатора…")
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)

print("Загрузка модели…")
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    device_map="auto",
    dtype="auto",
    load_in_4bit=True
)

print("\nМодель успешно загружена!")
print("Кэш модели находится в:", CACHE_DIR)
print("Временные файлы используются из:", TEMP_DIR)
