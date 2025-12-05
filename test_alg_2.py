import os
import json
import pandas as pd
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

# === Настройки ===
MODEL_ID = "mistralai/Mistral-7B-Instruct-v0.3"
WINDOW = 5
CHAT_FOLDER = "./chats"  # папка с JSON
OUTPUT_JSON = "purchases_context.json"
OUTPUT_CSV = "purchases_summary.csv"

# === Загрузка модели ===
print("Загрузка модели…")
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)

model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    device_map="auto",
    dtype="auto",
    load_in_4bit=True
)

def extract_text(msg):
    t = msg.get("text", "")
    if isinstance(t, list):
        parts = []
        for x in t:
            if isinstance(x, str):
                parts.append(x)
            elif isinstance(x, dict) and "text" in x:
                parts.append(x["text"])
        return " ".join(parts)
    return t

def analyze_window(messages, idx):
    start = max(0, idx - WINDOW)
    context_msgs = messages[start:idx + 1]

    dialogue = ""
    for i, m in enumerate(context_msgs):
        user = m.get("from", "unknown")
        text = extract_text(m)
        dialogue += f"{i+1}) [{user}]: {text}\n"

    prompt = f"""
Ты — извлекатель транзакций.

Проанализируй диалог ниже и определи, произошла ли покупка.
Контекст важен для понимания, кто покупает и что покупает.

Верни строго JSON:
{{
  "who": "<ник покупателя или none>",
  "item": "<товар/услуга или none>",
  "price": "<стоимость или none>"
}}

Если покупки нет — всё = "none".
Не придумывай информацию, используй только то, что явно сказано.

Диалог:
{dialogue}
JSON:
"""

    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    outputs = model.generate(**inputs, max_new_tokens=200)
    decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)

    # ищем JSON в ответе
    try:
        start_i = decoded.index("{")
        end_i = decoded.rindex("}") + 1
        j = json.loads(decoded[start_i:end_i])
        return j
    except:
        return {"who": "none", "item": "none", "price": "none"}

all_results = []

print("Поиск JSON файлов…")
files = [f for f in os.listdir(CHAT_FOLDER) if f.endswith(".json")]
print("Найдено файлов:", len(files))

for file in files:
    path = os.path.join(CHAT_FOLDER, file)
    print("\nЧтение:", file)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("messages", [])

    print("Анализ сообщений…")

    for i in range(len(messages)):
        if messages[i].get("type") != "message":
            continue

        result = analyze_window(messages, i)

        if result["item"] != "none":
            result.update({
                "chat": data.get("name", ""),
                "file": file,
                "message_id": messages[i]["id"],
                "message_text": extract_text(messages[i]),
                "date": messages[i].get("date")
            })
            all_results.append(result)

print("\nСохранение результатов…")

with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2)

df = pd.DataFrame(all_results)
if len(df) > 0:
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

print("\nГотово!")
print("Найдено покупок:", len(all_results))

if len(df) > 0:
    print("\nСтатистика покупок по товарам:")
    stats = df.groupby("item")["item"].count()
    print(stats)
