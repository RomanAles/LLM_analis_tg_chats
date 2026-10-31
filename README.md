# Тема — локальный анализ переписки Telegram

Импорт Telegram JSON → тема и период → обсуждения → находки с проверяемыми цитатами.
Локальная SQLite, CLI и веб-интерфейс. Весь код примеров и проверок работает
исключительно с **синтетическими данными**; настоящие переписки не включены.

## Быстрый старт в Windows / Miniconda

Проверено с Python 3.13.5 из Miniconda в отдельном `.venv`.
Базовый анализ и интерфейс не требуют сторонних Python-зависимостей.

```powershell
# Выполнять из корня проекта. Укажите путь к своей Miniconda.
& 'D:\miniconda3\python.exe' -m venv .venv

# Демонстрация на вымышленных сообщениях, отчёт в output/demo/
.\scripts\run.ps1 demo

# Локальный интерфейс
.\scripts\run.ps1 serve --port 8765
```

Откройте http://127.0.0.1:8765/ и нажмите «Попробовать синтетический пример» →
«Начать анализ». Карточка находки открывает исходное сообщение и соседний контекст.
Доступны история запусков, оценка находок и HTML/Markdown/JSON/CSV.

Если ensurepip не может писать во временный каталог в ограниченной среде:

```powershell
New-Item -ItemType Directory -Path '.tmp' -Force | Out-Null
$env:TEMP = Join-Path (Get-Location) '.tmp'
$env:TMP = $env:TEMP
& '.\.venv\Scripts\python.exe' -m ensurepip --upgrade
```

Для установки команды `tg-chat-analyzer` внутрь окружения:

```powershell
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-build.txt
& '.\.venv\Scripts\python.exe' -m pip install --no-build-isolation --no-deps -e .
```

Альтернатива: `conda env create -f environment.yml`, затем
`conda run -n tg-chat-analyzer python -m tg_chat_analyzer demo`.
Не нужно создавать venv внутри conda env. Файл environment.yml — рецепт,
а проверенные здесь версии инструментов сборки указаны в requirements-build.txt.

## Два способа анализа

- **Выдержки без модели**: слова, простые словоформы, синонимы, исключения и ответы
  на тематические сообщения. Работает сразу, без GPU. Это прозрачная исходная
  точка сравнения, а не смысловая интерпретация переписки.
- **Локальная LLM**: Ollama и установленная модель. Структурированный ответ
  по JSON Schema; проверяются существование ID и дословность цитат.
  Факты со слов автора, мнения, вопросы, рекомендации, проблемы и решения.

Полный обзор обрабатывает все фрагменты выбранного периода. Быстрый поиск
анализирует top-k кандидатов; отчёт явно показывает ограничение охвата.
100% охват обработки не означает 100% смысловую полноту.

## Рекомендуемые кандидаты моделей

Для проверенной RTX 4070 SUPER 12 GB: **Qwen3.5-9B в 4-bit** как основной
кандидат, **Qwen3.5-4B** как более лёгкий. Apache 2.0. Начальный контекст — 8192.
Выбор предварительный: превосходство над исходной Mistral на этой задаче ещё
не измерено. Веса в рамках разработки не скачивались.

После самостоятельной установки Ollama:

```powershell
ollama pull qwen3.5:9b
.\scripts\run.ps1 import examples/synthetic/dev.json
.\scripts\run.ps1 analyze --topic-file examples/synthetic/topic_dev.json --config configs/qwen35_9b.json --output output/qwen
```

В обычном анализе модель не скачивается. Внешние адреса inference API запрещены:
работа только с локальным runtime. Thinking выключен; ответ ограничен схемой.
Подробнее и первичные источники: [docs/MODELS.md](docs/MODELS.md).

## CLI

```powershell
# Один или несколько экспортов
.\scripts\run.ps1 import examples/synthetic/dev.json examples/synthetic/holdout.json
.\scripts\run.ps1 chats

# Тема из файла, все фрагменты
.\scripts\run.ps1 analyze --topic-file examples/synthetic/topic_dev.json --chat=-990001 --output output/nas

# Свободная тема, быстрый поиск, даты включительно по UTC+7
.\scripts\run.ps1 analyze --topic 'Резервное копирование' --keyword 'бэкап' --keyword 'backup' --mode question --top-k 5 --since 2026-01-01 --until 2026-01-31

# Продолжение: повторите ту же команду; --force пересчитывает этот запуск
.\scripts\run.ps1 analyze --topic-file examples/synthetic/topic_dev.json --chat=-990001 --output output/nas
```

Параметр `--db` задаёт файл SQLite (по умолчанию `data/chats.sqlite`). Экспорты
без ID чата получают ID по источнику; для стабильности можно задать `import --chat-id`.
Повторный импорт обновляет присутствующие записи, но не удаляет отсутствующие:
экспорт может быть частичным. Даты без timezone читаются как UTC+7;
`import --utc-offset` позволяет изменить это явно. date_unixtime имеет приоритет.

Тему можно сохранить в JSON:

```json
{
  "name": "Опыт домашних NAS",
  "description": "Шум и резервные копии",
  "keywords": ["NAS", "бэкап", "backup"],
  "exclude_keywords": ["NASCAR"],
  "synonyms": {"NAS": ["сетевое хранилище", "домашний сервер"]}
}
```

Опциональный смысловой поиск: `--embedding-model` с названием уже установленной
локальной embedding-модели Ollama. Словарный и смысловой ранги объединяются.
Реальные embeddings здесь не прогонялись; проверен программный контракт адаптера.

Для прежних текстовых Causal LM сохранён optional Transformers-адаптер:
`pip install -e ".[transformers,quantization]"` внутри подходящего окружения,
затем `--backend transformers --model <локальный каталог>`. GPU-зависимости
нужно подобрать к CUDA. Qwen3.5 запускайте через Ollama; она мультимодальная.
`pre_relis.py` сохраняет отдельный сценарий покупок, параметры доступны через `--help`.

## Проверки и синтетические данные

```powershell
.\scripts\check.ps1
.\scripts\run.ps1 evaluate --split dev --output output/evaluation_dev.json
.\scripts\run.ps1 evaluate --split holdout --output output/evaluation_holdout.json
& '.\.venv\Scripts\python.exe' scripts/generate_synthetic.py
```

Генератор воспроизводит 44 записи и отдельные метки для двух тем; пакет содержит
копию этих же демо для установки из wheel. Данные не получены из настоящих чатов.
Проверено 33 автоматических теста и основной сценарий в браузере.
Результаты и ограничения: [docs/VALIDATION.md](docs/VALIDATION.md).

## Структура и границы

`tg_chat_analyzer/`: импорт, SQLite, контекст, поиск, адаптеры моделей, конвейер,
отчёты, CLI, локальный сервер и статический интерфейс.

`examples/synthetic/`: демонстрационные экспорты, темы и разметка.
`tests/`: проверки на синтетических сценариях. `docs/`: требования, оценка и ход работы.

Отчёт группирует находки с источниками. Он не выполняет распознавание аудио,
проверку фактов во внешнем мире или автоматическую проверку противоречий.
Веб-загрузка: до 24 MB исходных файлов; большие экспорты — через CLI.
Корпус пока загружается в память. Сервер предназначен для локального использования.

Исходные переписки, базы, модели, окружения и результаты находятся в `.gitignore`.
Состояние шагов: [docs/PROGRESS.md](docs/PROGRESS.md).
