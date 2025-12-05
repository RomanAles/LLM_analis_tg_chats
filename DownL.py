from huggingface_hub import hf_hub_download, list_repo_files
from pathlib import Path
from tqdm import tqdm

# Папка локальной модели
model_dir = Path(r"D:\\CodesNodes\\LLM_analis_tg_chats\\models\\Mistral-7B-Instruct-v0.3")
model_dir.mkdir(parents=True, exist_ok=True)

repo_id = "mistralai/Mistral-7B-Instruct-v0.3"

# Получаем список всех файлов модели
all_files = list_repo_files(repo_id)

print(f"Будет скачано {len(all_files)} файлов:")

for file in tqdm(all_files, desc="Скачивание модели", unit="файл"):
    hf_hub_download(
        repo_id=repo_id,
        filename=file,
        local_dir=model_dir,
        local_dir_use_symlinks=False
    )

print("Все файлы модели скачаны в:", model_dir)
