from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime

from .config import AnalysisConfig, fingerprint
from .models import Fragment


def build_fragments(messages, config=None):
    """Partition target coverage; add reply ancestors when the budget permits.

    Explicit threads/replies take precedence over time-based guesses. Huge
    messages are split without dropping text, keeping their original source ID.
    """
    config = config or AnalysisConfig()
    chats = defaultdict(list)
    for message in messages:
        chats[message.chat_id].append(message)
    fragments = []
    for chat_id, chat in sorted(chats.items()):
        chat.sort(key=lambda m: (m.date, m.id))
        by_id = {m.id: m for m in chat}
        referenced = {m.reply_to for m in chat if m.reply_to in by_id}

        def root(message):
            visited, current = [], message
            while current.reply_to in by_id:
                if current.id in visited:
                    return min(visited), "reply_cycle"
                visited.append(current.id)
                current = by_id[current.reply_to]
                if current.thread_id:
                    return current.thread_id, "thread"
            return current.id, "reply_missing" if current.reply_to else "reply"

        groups = defaultdict(list)
        session, previous = 0, None
        for message in chat:
            if message.thread_id:
                key = ("thread", message.thread_id)
            elif message.reply_to or message.id in referenced:
                origin, relation = root(message)
                key = (relation, origin)
            else:
                moment = datetime.fromisoformat(message.date)
                if previous is None or (moment - previous).total_seconds() > config.gap_minutes * 60:
                    session += 1
                previous = moment
                key = ("time_heuristic", session)
            groups[key].append(message)

        for (relation, _), group in groups.items():
            units = []
            for message in group:
                width = max(1, config.context_chars - len(f"[{message.key}] {message.author}: ") - 2)
                pieces = [message.text[i:i + width] for i in range(0, len(message.text), width)] or [""]
                units.extend((replace(message, text=piece), len(pieces) > 1) for piece in pieces)
            batches, batch, cost = [], [], 0
            for message, split in units:
                size = len(f"[{message.key}] {message.author}: {message.text}\n")
                if batch and (cost + size > config.context_chars or len(batch) >= config.max_messages):
                    batches.append(batch)
                    batch, cost = [], 0
                batch.append((message, split))
                cost += size
            if batch:
                batches.append(batch)
            for batch in batches:
                targets = [m for m, _ in batch]
                context = list(targets)
                included = {m.id for m in context}
                incomplete = any(split for _, split in batch)
                for target in targets:
                    parent_id, visited = target.reply_to, {target.id}
                    while parent_id in by_id and parent_id not in visited:
                        visited.add(parent_id)
                        parent = by_id[parent_id]
                        if parent_id not in included:
                            candidate = [parent] + context
                            size = sum(len(f"[{m.key}] {m.author}: {m.text}\n") for m in candidate)
                            if size > config.context_chars or len(candidate) > config.max_messages:
                                incomplete = True
                                break
                            context.insert(0, parent)
                            included.add(parent_id)
                        parent_id = parent.reply_to
                    if parent_id is not None and parent_id not in by_id:
                        incomplete = True
                context.sort(key=lambda m: (m.date, m.id))
                identity = fingerprint({"messages": [(m.key, m.content_hash, m.text) for m in context],
                                        "targets": [m.key for m in targets], "relation": relation})
                fragments.append(Fragment(identity, chat_id, tuple(context),
                    tuple(dict.fromkeys(m.key for m in targets)), relation, incomplete))
    return sorted(fragments, key=lambda f: (f.chat_id, min(m.date for m in f.messages)))
