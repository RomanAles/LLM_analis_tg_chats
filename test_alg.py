import os
import json
import csv
from transformers import AutoTokenizer, AutoModelForCausalLM

# === Папка локальной модели на D: ===
model_path = r"D:\\CodesNodes\\LLM_analis_tg_chats\\models\\Mistral-7B-Instruct-v0.3"

# === Загрузка токенизатора и модели ===
print("Загрузка модели локально…")
tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModelForCausalLM.from_pretrained(
    model_path,
    device_map="auto",
    load_in_4bit=True  # экономим VRAM
)
print("Модель загружена!\n")

# === Параметры ===
WINDOW = 5  # количество сообщений для контекста

# === Вспомогательная функция для извлечения текста ===
def extract_text(msg):
    t = msg.get("text", "")
    if isinstance(t, list):
        return " ".join([part for part in t if isinstance(part, str)])
    return t

# === Анализ окна сообщений ===
def analyze_window(messages, idx):
    start = max(0, idx - WINDOW)
    context_msgs = messages[start:idx+1]

    dialogue = ""
    for i, m in enumerate(context_msgs):
        user = m.get("from", "unknown")
        text = extract_text(m)
        dialogue += f"{i+1}) [{user}]: {text}\n"

    prompt = f"""
Ты — извлекатель транзакций.

Проанализируй диалог ниже и определи, произошла ли покупка.
Контекст важен для понимания, кто покупает и что покупает.

Верни ТОЛЬКО JSON:
{{
  "who": "<ник покупателя или none>",
  "item": "<товар/услуга или none>",
  "price": "<стоимость или none>"
}}

Если покупки нет — всё = "none".
Не фантазируй, используй только то, что явно в сообщениях.

Диалог:
{dialogue}
JSON:
"""

    # Токенизация и генерация ответа
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    outputs = model.generate(**inputs, max_new_tokens=200)
    decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)

    try:
        j = decoded[decoded.index("{"): decoded.rindex("}")+1]
        return json.loads(j)
    except:
        return {"who": "none", "item": "none", "price": "none"}

# === Загрузка чата ===
print("Загрузка чата…")
with open("chat.json", "r", encoding="utf-8") as f:
    data = json.load(f)

messages = data["messages"]

# === Анализ всех сообщений ===
results = []
item_count = {}  # подсчёт, сколько раз купили каждый товар

print("Анализ сообщений…")
for i in range(len(messages)):
    if messages[i]["type"] != "message":
        continue
    result = analyze_window(messages, i)
    if result["item"] != "none":
        result["message_id"] = messages[i]["id"]
        result["message"] = extract_text(messages[i])
        results.append(result)

        # Подсчёт количества покупок по товару
        item_count[result["item"]] = item_count.get(result["item"], 0) + 1

# === Сохранение результатов в JSON ===
with open("purchases_context.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# === Сохранение в CSV ===
with open("purchases_context.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["message_id", "who", "item", "price", "message"])
    writer.writeheader()
    writer.writerows(results)

# === Вывод статистики ===
print("Готово! Найдено покупок:", len(results))
print("Подсчёт покупок по товарам:")
for item, count in item_count.items():
    print(f"  {item}: {count} раз(а)")
