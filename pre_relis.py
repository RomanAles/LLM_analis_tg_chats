import os
import json
import csv
from tqdm import tqdm
from transformers import (
    AutoTokenizer, AutoModelForCausalLM,
    BitsAndBytesConfig
)

# === Путь к локальной модели ===
model_path = r"D:\\CodesNodes\\LLM_analis_tg_chats\\models\\Mistral-7B-Instruct-v0.3"

print("Загрузка модели локально…")

tokenizer = AutoTokenizer.from_pretrained(model_path)

# ⚠ load_in_4bit устарел — используем BitsAndBytesConfig
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype="float16"
)

model = AutoModelForCausalLM.from_pretrained(
    model_path,
    device_map="auto",
    quantization_config=bnb_config
)

print("Модель загружена!\n")

WINDOW = 5  # окно контекста


def extract_text(msg):
    """Извлекает текст из JSON-сообщения Telegram."""
    t = msg.get("text", "")
    if isinstance(t, list):
        t = " ".join([s for s in t if isinstance(s, str)])
    return str(t)


def analyze_window(messages, idx):
    """Достаёт последние WINDOW сообщений и отправляет модели."""
    start = max(0, idx - WINDOW)
    ctx = messages[start: idx + 1]

    dialogue = "\n".join(
        f"{i+1}) [{m.get('from','unknown')}]: {extract_text(m)}"
        for i, m in enumerate(ctx)
    )

    prompt = (
        "Ты — извлекатель данных о покупках.\n\n"
        "Проанализируй диалог и определи, была ли покупка.\n"
        "Верни строго JSON, без комментариев и текста до/после!\n"
        "{\n"
        '  "who": "<кто покупает или none>",\n'
        '  "item": "<товар или none>",\n'
        '  "price": "<цена или none>"\n'
        "}\n\n"
        "Если покупки нет — всё должно быть \"none\".\n"
        "Не придумывай ничего не из текста.\n\n"
        f"Диалог:\n{dialogue}\n\n"
        "JSON:"
    )

    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,   # предотвращает переполнение токенов
        max_length=2048
    ).to(model.device)

    outputs = model.generate(
        **inputs,
        max_new_tokens=150,
        pad_token_id=tokenizer.eos_token_id
    )
    decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)

    # === Чистка вывода до голого JSON ===
    try:
        j = decoded[decoded.index("{"): decoded.rindex("}") + 1]
        return json.loads(j)
    except Exception:
        return {"who": "none", "item": "none", "price": "none"}


print("Загрузка чата…")
with open("chat.json", "r", encoding="utf-8") as f:
    messages = json.load(f)["messages"]

results = []
item_count = {}

print("Анализ сообщений…")
for i in tqdm(range(len(messages))):
    m = messages[i]
    if m.get("type") != "message":
        continue

    res = analyze_window(messages, i)

    # если нет покупки — пропускаем
    if res["item"] == "none":
        continue

    res.update({
        "message_id": m["id"],
        "message": extract_text(m)
    })
    results.append(res)

    item_count[res["item"]] = item_count.get(res["item"], 0) + 1


# === Сохранение результатов ===
with open("purchases_context.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

with open("purchases_context.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f, fieldnames=["message_id", "who", "item", "price", "message"]
    )
    writer.writeheader()
    writer.writerows(results)

print("\nГотово! Найдено покупок:", len(results))
print("Подсчёт покупок по товарам:")
for item, count in item_count.items():
    print(f"  {item}: {count}")
