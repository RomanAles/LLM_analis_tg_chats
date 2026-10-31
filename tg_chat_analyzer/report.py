from __future__ import annotations

import csv
import html
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

TYPE_NAMES = {"fact": "Утверждение автора", "opinion": "Мнение", "question": "Вопрос",
              "recommendation": "Рекомендация", "problem": "Проблема", "solution": "Решение",
              "excerpt": "Выдержка по словам темы"}


def build_report(topic, config, identity, messages, findings, statistics, errors, run_id):
    unique = {finding["id"]: finding for finding in findings}
    findings = sorted(unique.values(), key=lambda f: (f["evidence"][0]["date"], f["id"]))
    source_keys = {e["key"] for finding in findings for e in finding["evidence"]}
    context_keys = set(source_keys)
    by_chat = defaultdict(list)
    for message in messages:
        by_chat[message.chat_id].append(message)
    for chat in by_chat.values():
        for i, message in enumerate(chat):
            if message.key in source_keys:
                context_keys.update(m.key for m in chat[max(0, i-2):i+3])
                if message.reply_to:
                    context_keys.add(f"{message.chat_id}:{message.reply_to}")
    source_messages = [m.to_dict() for m in messages if m.key in context_keys]
    matched = [m for m in messages if m.key in source_keys]
    counts = {**statistics, "findings": len(findings), "matched_messages": len(source_keys),
              "identified_participants": len({(m.chat_id, m.author_id) for m in matched if m.author_id}),
              "messages_unknown_author": sum(m.author_id is None for m in matched),
              "attachments_without_text": sum(bool(m.attachment) and not m.text.strip() for m in messages),
              "subtopics": dict(Counter(f["subtopic"] for f in findings)),
              "activity_by_day_utc": dict(sorted(Counter(m.date[:10] for m in matched).items()))}
    limitations = ["Цитаты и ID проверены программно; смысловые выводы и типы требуют проверки человеком.",
                  "Число находок не равно числу покупок или других событий.",
                  "Профили участников между разными чатами не объединяются."]
    if not identity.get("generative"):
        limitations.append("Режим выдержек использует слова темы и связи ответов; смысловая интерпретация LLM не выполнялась.")
    if config.mode == "question":
        limitations.append("Быстрый поиск охватывает выбранные фрагменты; выводы не описывают весь корпус.")
    if counts["attachments_without_text"]:
        limitations.append("Есть вложения без текста; их содержимое не распознавалось.")
    if errors:
        limitations.append("Есть ошибки обработки; обзор неполный.")
    return {"schema_version": 1, "run_id": run_id, "generated_at": datetime.now(timezone.utc).isoformat(),
            "topic": topic.to_dict(), "config": config.to_dict(), "analyzer": identity,
            "statistics": counts, "limitations": limitations, "errors": errors,
            "findings": findings, "sources": source_messages}


def markdown(report):
    s = report["statistics"]
    lines = [f"# Анализ темы: {report['topic']['name']}", "",
             f"Режим: {report['config']['mode']}; алгоритм: {report['analyzer']['backend']}.",
             f"Сообщений в выборке: {s['messages_total']}; обработано фрагментов: "
             f"{s['processed_fragments']}/{s['fragments_total']}; ошибок: {len(report['errors'])}.",
             f"Тематических сообщений: {s['matched_messages']}; находок: {s['findings']}.", ""]
    for finding in report["findings"]:
        lines.extend([f"## {finding['subtopic']}", "", f"**{TYPE_NAMES[finding['type']]}:** {finding['claim']}", ""])
        for item in finding["evidence"]:
            lines.extend(["> " + item["quote"].replace("\n", "\n> "), "",
                          f"Источник: {item['key']}; {item['author']}; {item['date']}.", ""])
    if not report["findings"]:
        lines.extend(["Подтверждённых тематических находок нет. Проверьте режим и ошибки обработки.", ""])
    lines.extend(["## Ограничения", "", *[f"- {x}" for x in report["limitations"]]])
    return "\n".join(lines) + "\n"


def render_html(report):
    e = lambda value: html.escape(str(value), quote=True)
    s = report["statistics"]
    parts = ["<!doctype html><html lang='ru'><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width,initial-scale=1'>",
             "<title>Анализ темы</title><style>body{max-width:1000px;margin:40px auto;padding:0 20px;",
             "font:16px/1.6 system-ui;background:#f5f7fa;color:#182638}article,section{background:white;",
             "padding:20px;margin:18px 0;border:1px solid #dce2ec;border-radius:12px}blockquote{",
             "white-space:pre-wrap;border-left:3px solid #5283be;padding-left:16px}a{color:#205dad}",
             ".meta{font-size:13px;color:#52637b}.source:target{outline:3px solid #d6a347}</style>",
             f"<h1>{e(report['topic']['name'])}</h1>",
             f"<p>Режим: {e(report['config']['mode'])} · {e(report['analyzer']['backend'])}</p>",
             f"<section><b>{s['matched_messages']}</b> тематических сообщений · <b>{s['findings']}</b> находок · "
             f"<b>{s['identified_participants']}</b> известных авторов в чатах<br>"
             f"Обработано фрагментов: {s['processed_fragments']}/{s['fragments_total']}; "
             f"сообщений в выборке: {s['messages_total']}; ошибок: {len(report['errors'])}</section>"]
    for finding in report["findings"]:
        parts.append(f"<article id='finding-{finding['id']}'><div class='meta'>{e(TYPE_NAMES[finding['type']])} · "
                     f"{e(finding['subtopic'])}</div><p>{e(finding['claim'])}</p>")
        for item in finding["evidence"]:
            parts.append(f"<blockquote>{e(item['quote'])}</blockquote><a href='#{item['anchor']}'>"
                         f"{e(item['author'])} · {e(item['date'])} · {e(item['key'])}</a>")
        parts.append("</article>")
    if not report["findings"]:
        parts.append("<section>Тематических находок нет. Проверьте режим и ошибки обработки.</section>")
    parts.append("<h2>Ограничения</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in report["limitations"]) + "</ul>")
    if report["errors"]:
        parts.append("<h2>Ошибки</h2><pre>" + e(json.dumps(report["errors"], ensure_ascii=False, indent=2)) + "</pre>")
    parts.append("<h2>Контекст источников</h2>")
    for message in report["sources"]:
        parts.append(f"<section class='source' id='{message['anchor']}'><div class='meta'>"
                     f"{e(message['key'])} · {e(message['author'])} · {e(message['date'])}</div>"
                     f"<blockquote>{e(message['text'])}</blockquote></section>")
    parts.append("</html>")
    return "".join(parts)


def csv_safe(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def export_report(report, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "report.md").write_text(markdown(report), encoding="utf-8")
    (directory / "report.html").write_text(render_html(report), encoding="utf-8")
    fields = ["finding_id", "type", "subtopic", "claim", "chat_id", "message_id", "author", "date", "quote"]
    with (directory / "findings.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for finding in report["findings"]:
            for item in finding["evidence"]:
                row = {**finding, **item, "finding_id": finding["id"]}
                writer.writerow({field: csv_safe(row[field]) for field in fields})
    return directory / "report.html"
