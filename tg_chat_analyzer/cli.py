from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timedelta, timezone
from importlib.resources import files
from pathlib import Path

from . import __version__
from .config import AnalysisConfig, Topic
from .importer import import_export
from .pipeline import analyze
from .report import export_report
from .storage import Store


def date_bound(value, end=False):
    if not value:
        return None
    if len(value) == 10:
        date = datetime.combine(datetime.fromisoformat(value).date(), time.max if end else time.min)
    else:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone(timedelta(hours=7)))
    return date.astimezone(timezone.utc).isoformat()


def config_from_dict(value):
    if not isinstance(value, dict):
        raise ValueError("Настройки должны быть объектом")
    unknown = set(value) - set(AnalysisConfig.__dataclass_fields__)
    if unknown:
        raise ValueError("Неизвестные настройки: " + ", ".join(sorted(unknown)))
    return AnalysisConfig(**value)


def load_demo(store, split="dev"):
    resource = files("tg_chat_analyzer").joinpath("demo", split + ".json")
    data = json.loads(resource.read_text(encoding="utf-8"))
    return import_export(store, data, source_name=f"synthetic-{split}.json")


def demo_topic(split="dev"):
    return Topic.from_dict(json.loads(files("tg_chat_analyzer").joinpath(
        "demo", "topic_" + split + ".json").read_text(encoding="utf-8")))


def evaluate(config, split="dev"):
    manifest = json.loads(files("tg_chat_analyzer").joinpath("demo", "labels.json").read_text(encoding="utf-8"))
    results = []
    for dataset in manifest["datasets"]:
        if split != "all" and split != dataset["split"]:
            continue
        with Store(":memory:") as store:
            imported = load_demo(store, dataset["split"])
            report = analyze(store, demo_topic(dataset["split"]), config)
            expected = {f"{imported['chat_id']}:{i}" for i in dataset["relevant_message_ids"]}
            predicted = {e["key"] for f in report["findings"] for e in f["evidence"]}
            tp = len(expected & predicted)
            precision = tp / len(predicted) if predicted else 0
            recall = tp / len(expected) if expected else 0
            results.append({"split": dataset["split"], "synthetic": True, "backend": report["analyzer"],
                "precision": round(precision, 4), "recall": round(recall, 4),
                "f1": round(2*precision*recall/(precision+recall), 4) if precision+recall else 0,
                "tp": tp, "fp": sorted(predicted-expected), "fn": sorted(expected-predicted),
                "statistics": report["statistics"], "errors": report["errors"]})
    return {"notice": "Синтетическая проверка регрессий; не оценка качества на реальных чатах", "results": results}


def build_parser():
    parser = argparse.ArgumentParser(prog="tg-chat-analyzer", description="Локальный анализ тем в Telegram JSON")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--db", default="data/chats.sqlite")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("import", "chats", "analyze", "demo", "evaluate", "serve"):
        command = sub.add_parser(name)
        command.add_argument("--db", default=argparse.SUPPRESS)
        if name == "import":
            command.add_argument("files", nargs="+", type=Path)
            command.add_argument("--chat-id")
            command.add_argument("--utc-offset", type=float, default=7)
        elif name in {"analyze", "evaluate"}:
            command.add_argument("--config", type=Path)
            for key in ("backend", "model", "base-url", "mode", "embedding-model"):
                command.add_argument("--" + key)
            for key in ("top-k", "context-chars", "context-tokens", "max-output-tokens"):
                command.add_argument("--" + key, type=int)
            if name == "analyze":
                topics = command.add_mutually_exclusive_group(required=True)
                topics.add_argument("--topic")
                topics.add_argument("--topic-file", type=Path)
                command.add_argument("--keyword", action="append", default=[])
                command.add_argument("--chat", action="append")
                command.add_argument("--since")
                command.add_argument("--until")
                command.add_argument("--output", type=Path, default=Path("output/latest"))
                command.add_argument("--force", action="store_true")
                command.add_argument("--stop-after", type=int)
            else:
                command.add_argument("--split", choices=["dev", "holdout", "all"], default="dev")
                command.add_argument("--output", type=Path, default=Path("output/evaluation.json"))
        elif name == "demo":
            command.add_argument("--output", type=Path, default=Path("output/demo"))
        elif name == "serve":
            command.add_argument("--port", type=int, default=8765)
            command.add_argument("--open", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "serve":
            from .server import serve
            serve(args.db, args.port, args.open)
            return 0
        config_values = json.loads(args.config.read_text(encoding="utf-8")) if getattr(args, "config", None) else {}
        for key in AnalysisConfig.__dataclass_fields__:
            value = getattr(args, key, None)
            if value is not None:
                config_values[key] = value
        config = config_from_dict(config_values)
        if args.command == "evaluate":
            result = evaluate(config, args.split)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return int(any(row["errors"] for row in result["results"]))
        with Store(args.db) as store:
            if args.command == "import":
                if args.chat_id and len(args.files) != 1:
                    raise ValueError("--chat-id можно задавать только для одного файла")
                reports = [import_export(store, path, chat_id=args.chat_id, utc_offset_hours=args.utc_offset) for path in args.files]
                print(json.dumps(reports, ensure_ascii=False, indent=2))
                return int(any(report["errors"] for report in reports))
            if args.command == "chats":
                print(json.dumps(store.list_chats(), ensure_ascii=False, indent=2))
                return 0
            if args.command == "demo":
                load_demo(store)
                report = analyze(store, demo_topic(), AnalysisConfig(), chat_ids=["-990001"])
            else:
                topic = Topic.load(args.topic_file) if args.topic_file else Topic(args.topic, keywords=args.keyword)
                since, until = date_bound(args.since), date_bound(args.until, True)
                if since and until and since > until:
                    raise ValueError("Начало периода позже окончания")
                report = analyze(store, topic, config, chat_ids=args.chat, since=since, until=until,
                    force=args.force, stop_after=args.stop_after,
                    progress=lambda state: print(f"\r{state['current']}/{state['total']} | cache {state['cached']} | errors {state['errors']}",
                                                  end="", file=sys.stderr, flush=True))
                print(file=sys.stderr)
            path = export_report(report, args.output)
            print(json.dumps({"run_id": report["run_id"], "report": str(path.resolve()),
                              "statistics": report["statistics"]}, ensure_ascii=False, indent=2))
            return 130 if report["statistics"]["state"] == "interrupted" else int(bool(report["errors"]))
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
