from __future__ import annotations

import json
import time
from dataclasses import replace

from . import __version__
from .analysis import PROMPT_VERSION, SCHEMA, make_analyzer, make_prompt
from .config import fingerprint
from .context import build_fragments
from .models import Fragment
from .report import build_report
from .search import OllamaEmbedder, rank_fragments


def ensure_job_tables(store):
    store.connection.executescript("""
        CREATE TABLE IF NOT EXISTS runs(
            id TEXT PRIMARY KEY, status TEXT NOT NULL, request TEXT NOT NULL,
            report TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS fragment_results(
            run_id TEXT NOT NULL REFERENCES runs(id), fragment_id TEXT NOT NULL,
            status TEXT NOT NULL, result TEXT, error TEXT, attempts INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(run_id,fragment_id));
        CREATE TABLE IF NOT EXISTS feedback(
            id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
            finding_id TEXT NOT NULL, verdict TEXT NOT NULL, comment TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    """)


def effective_config(config, topic):
    if config.backend != "ollama":
        return config
    empty = Fragment("", "", (), (), "time_heuristic")
    overhead = len(make_prompt(empty, topic).encode("utf-8")) + 128
    available = config.context_tokens - config.max_output_tokens - overhead
    # Context JSON metadata also consumes tokens. Conservative splitting is
    # preferable to letting the runtime silently drop the beginning of a chat.
    budget = min(config.context_chars, available // 4)
    if budget < 256:
        raise ValueError("Недостаточно контекста для темы, схемы и ответа; увеличьте context_tokens")
    return replace(config, context_chars=budget, max_messages=min(config.max_messages, 8))


def analyze(store, topic, config, *, chat_ids=None, since=None, until=None, analyzer=None,
            embed=None, force=False, stop_after=None, cancel=None, progress=None):
    ensure_job_tables(store)
    started = time.monotonic()
    messages = store.messages(chat_ids, since, until)
    if not messages:
        raise ValueError("В выбранном периоде и чатах нет сообщений")
    analyzer = analyzer or make_analyzer(config)
    identity = analyzer.identity()
    actual_config = effective_config(config, topic)
    fragments = build_fragments(messages, actual_config)
    if embed is None and config.embedding_model:
        embed = OllamaEmbedder(config.embedding_model, config.base_url, config.timeout)
    hits = rank_fragments(fragments, topic, config.mode, config.top_k, embed)
    request = {"application": __version__, "prompt": PROMPT_VERSION, "schema": fingerprint(SCHEMA),
               "context_version": 1, "search_version": 1,
               "topic": topic.to_dict(), "config": config.to_dict(), "effective_config": actual_config.to_dict(),
               "identity": identity, "corpus": fingerprint([(m.key, m.content_hash) for m in messages]),
               "filters": {"chats": sorted(chat_ids or []), "since": since, "until": until}}
    run_id = fingerprint(request)[:32]
    connection = store.connection
    with connection:
        connection.execute("INSERT INTO runs(id,status,request) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET status='running',updated_at=CURRENT_TIMESTAMP",
                           (run_id, "running", json.dumps(request, ensure_ascii=False)))
        if force:
            connection.execute("DELETE FROM fragment_results WHERE run_id=?", (run_id,))
    findings, errors, covered = [], [], set()
    counts = {"messages_total": len(messages), "fragments_total": len(fragments), "selected_fragments": len(hits),
              "processed_fragments": 0, "cached_fragments": 0, "not_found_fragments": 0,
              "insufficient_context_fragments": 0, "incomplete_context_fragments": sum(f.truncated for f in fragments)}
    attempted, interrupted = 0, False
    try:
        for index, hit in enumerate(hits):
            if (cancel and cancel.is_set()) or (stop_after is not None and attempted >= stop_after):
                interrupted = True
                break
            fragment = hit.fragment
            old = connection.execute("SELECT * FROM fragment_results WHERE run_id=? AND fragment_id=?",
                                     (run_id, fragment.id)).fetchone()
            if old is not None and old["status"] == "done":
                result = json.loads(old["result"])
                counts["cached_fragments"] += 1
            else:
                attempted += 1
                try:
                    result = analyzer.analyze(fragment, topic)
                    with connection:
                        connection.execute("""INSERT INTO fragment_results(run_id,fragment_id,status,result)
                            VALUES(?,?,'done',?) ON CONFLICT(run_id,fragment_id) DO UPDATE SET
                            status='done',result=excluded.result,error=NULL,attempts=attempts+1,updated_at=CURRENT_TIMESTAMP""",
                            (run_id, fragment.id, json.dumps(result, ensure_ascii=False)))
                except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                    error = {"fragment_id": fragment.id, "targets": list(fragment.target_keys),
                             "error": f"{type(exc).__name__}: {exc}"}
                    errors.append(error)
                    with connection:
                        connection.execute("""INSERT INTO fragment_results(run_id,fragment_id,status,error)
                            VALUES(?,?,'error',?) ON CONFLICT(run_id,fragment_id) DO UPDATE SET
                            status='error',result=NULL,error=excluded.error,attempts=attempts+1,updated_at=CURRENT_TIMESTAMP""",
                            (run_id, fragment.id, json.dumps(error, ensure_ascii=False)))
                    if progress:
                        progress({"run_id": run_id, "current": index+1, "total": len(hits), "cached": counts["cached_fragments"],
                                  "errors": len(errors), "status": "running"})
                    continue
            findings.extend(result["findings"])
            counts["processed_fragments"] += 1
            covered.update(fragment.target_keys)
            if result["status"] == "not_found":
                counts["not_found_fragments"] += 1
            elif result["status"] == "insufficient_context":
                counts["insufficient_context_fragments"] += 1
            if progress:
                progress({"run_id": run_id, "current": index+1, "total": len(hits), "cached": counts["cached_fragments"],
                          "errors": len(errors), "status": "running"})
    except KeyboardInterrupt:
        interrupted = True
    state = "interrupted" if interrupted else "with_errors" if errors else "complete"
    counts.update(covered_messages=len(covered), coverage_percent=round(100*len(covered)/len(messages), 2),
                  attempted_fragments=attempted, duration_seconds=round(time.monotonic()-started, 3), state=state)
    report = build_report(topic, config, identity, messages, findings, counts, errors, run_id)
    report["effective_config"] = actual_config.to_dict()
    if interrupted:
        report["limitations"].append("Запуск прерван. Повторите ту же команду, чтобы продолжить.")
    if counts["incomplete_context_fragments"]:
        report["limitations"].append("Часть контекстов разделена бюджетом или имеет отсутствующие связи ответов.")
    with connection:
        connection.execute("UPDATE runs SET status=?,report=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                           (state, json.dumps(report, ensure_ascii=False), run_id))
    return report


def get_report(store, run_id):
    ensure_job_tables(store)
    row = store.connection.execute("SELECT report FROM runs WHERE id=?", (run_id,)).fetchone()
    if row is None or not row[0]:
        raise ValueError("Отчёт не найден")
    return json.loads(row[0])


def save_feedback(store, run_id, finding_id, verdict, comment=""):
    report = get_report(store, run_id)
    if verdict not in {"correct", "incorrect", "missed"}:
        raise ValueError("Некорректная оценка")
    if verdict != "missed" and finding_id not in {f["id"] for f in report["findings"]}:
        raise ValueError("Находка не существует в этом запуске")
    if not isinstance(comment, str) or len(comment) > 4000:
        raise ValueError("Комментарий слишком длинный")
    with store.connection:
        store.connection.execute("INSERT INTO feedback(run_id,finding_id,verdict,comment) VALUES(?,?,?,?)",
                                 (run_id, finding_id, verdict, comment))
