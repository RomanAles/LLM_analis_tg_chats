from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import fingerprint
from .legacy import extract_text


def timestamp(value, unix=None, utc_offset_hours=7):
    if unix is not None:
        return datetime.fromtimestamp(float(unix), timezone.utc).isoformat()
    if not isinstance(value, str):
        raise ValueError("Нет даты сообщения")
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone(timedelta(hours=utc_offset_hours)))
    return date.astimezone(timezone.utc).isoformat()


def import_export(store, source, *, source_name=None, chat_id=None, utc_offset_hours=7):
    if isinstance(source, (str, Path)):
        path = Path(source)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        source_name = source_name or str(path.resolve())
    else:
        data = source
        source_name = source_name or "uploaded.json"
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        raise ValueError("Нужен Telegram JSON с массивом messages")
    identity = chat_id if chat_id is not None else data.get("id")
    if identity is None:
        identity = "source-" + fingerprint(source_name)[:20]
    if type(identity) not in (str, int) or not str(identity).strip():
        raise ValueError("Некорректный chat_id")
    identity = str(identity)
    report = {"chat_id": identity, "source": source_name, "synthetic": data.get("synthetic") is True,
              "inserted": 0, "updated": 0, "unchanged": 0, "service": 0,
              "attachments": 0, "errors": [], "warnings": []}
    if data.get("id") is None and chat_id is None:
        report["warnings"].append("Нет chat_id: идентификатор зависит от имени источника; можно задать --chat-id")
    rows, seen, naive_dates = [], set(), 0
    for position, raw in enumerate(data["messages"]):
        try:
            if not isinstance(raw, dict):
                raise ValueError("Сообщение должно быть объектом")
            if raw.get("type") == "service":
                report["service"] += 1
                continue
            if raw.get("type") != "message":
                raise ValueError("Неизвестный тип записи")
            msg_id = raw.get("id")
            if type(msg_id) is not int or msg_id <= 0:
                raise ValueError("Нужен положительный целочисленный message_id")
            if msg_id in seen:
                raise ValueError("Повторный message_id внутри файла")
            seen.add(msg_id)
            if raw.get("date_unixtime") is None and isinstance(raw.get("date"), str):
                if datetime.fromisoformat(raw["date"].replace("Z", "+00:00")).tzinfo is None:
                    naive_dates += 1
            date = timestamp(raw.get("date"), raw.get("date_unixtime"), utc_offset_hours)
            reply = raw.get("reply_to_message_id")
            thread = raw.get("message_thread_id", raw.get("reply_to_top_id"))
            if any(x is not None and (type(x) is not int or x <= 0) for x in (reply, thread)):
                raise ValueError("Некорректный идентификатор ответа или темы")
            attachment = raw.get("media_type") or ("photo" if "photo" in raw else None)
            if not attachment and raw.get("file"):
                attachment = "file"
            if attachment:
                report["attachments"] += 1
            author = raw.get("from") or "Неизвестный автор"
            author_id = raw.get("from_id")
            if author_id is None and raw.get("from"):
                author_id = "name:" + str(raw["from"])
            values = (identity, msg_id, date, str(author), str(author_id) if author_id else None,
                      extract_text(raw), reply, thread, str(attachment) if attachment else None,
                      fingerprint({"raw": raw, "normalized_date": date}), json.dumps(raw, ensure_ascii=False))
            rows.append(values)
        except (ValueError, TypeError, OverflowError, OSError) as exc:
            report["errors"].append({"position": position, "message_id": raw.get("id")
                                    if isinstance(raw, dict) else None, "error": str(exc)})
    if naive_dates:
        report["warnings"].append(f"{naive_dates} дат без timezone прочитаны как UTC{utc_offset_hours:+g}")
    connection = store.connection
    source_hash = fingerprint(data)
    with connection:
        connection.execute("INSERT INTO chats VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,metadata=excluded.metadata",
            (identity, str(data.get("name", identity)), json.dumps(
                {k: v for k, v in data.items() if k != "messages"}, ensure_ascii=False)))
        for row in rows:
            old = connection.execute("SELECT content_hash FROM messages WHERE chat_id=? AND id=?", row[:2]).fetchone()
            status = "inserted" if old is None else "unchanged" if old[0] == row[-2] else "updated"
            report[status] += 1
            if status != "unchanged":
                connection.execute("""INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(chat_id,id) DO UPDATE SET date=excluded.date,author=excluded.author,
                    author_id=excluded.author_id,text=excluded.text,reply_to=excluded.reply_to,
                    thread_id=excluded.thread_id,attachment=excluded.attachment,
                    content_hash=excluded.content_hash,raw_json=excluded.raw_json""", row)
        connection.execute("INSERT OR IGNORE INTO source_documents VALUES(?,?)",
                           (source_hash, json.dumps(data, ensure_ascii=False)))
        connection.execute("INSERT INTO imports(source,source_hash,chat_id,report) VALUES(?,?,?,?)",
                           (source_name, source_hash, identity, json.dumps(report, ensure_ascii=False)))
    return report
