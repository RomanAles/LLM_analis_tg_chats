from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .local_api import LocalAPI

STOPWORDS = set("и в во на по с со а но или для к ко из о об от до у это как что какие какой "
                "опыт обсуждение обсуждения тема домашних домашний использование использования".split())
SUFFIXES = sorted(("иями", "ями", "ами", "ого", "ему", "ому", "ыми", "ими", "ость", "ение",
                   "ения", "ов", "ев", "ам", "ям", "ах", "ях", "ый", "ий", "ой", "ая", "яя",
                   "ое", "ее", "ые", "ие", "ом", "ем", "а", "я", "ы", "и", "у", "ю", "е"), key=len, reverse=True)


def words(text):
    return re.findall(r"[a-zа-я0-9]+", text.casefold().replace("ё", "е"))


def stem(word):
    if len(word) < 5 or not re.search("[а-я]", word):
        return word
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[:-len(suffix)]
    return word


def phrase_matches(text, phrase):
    tokens, pattern = [stem(w) for w in words(text)], [stem(w) for w in words(phrase)]
    return bool(pattern) and any(all(tokens[i + j].startswith(part) for j, part in enumerate(pattern))
        for i in range(len(tokens) - len(pattern) + 1))


def topic_terms(topic):
    base = topic.keywords or [w for w in words(topic.name + " " + topic.description) if w not in STOPWORDS and len(w) > 2]
    return list(dict.fromkeys([*base, *topic.synonyms, *(s for values in topic.synonyms.values() for s in values)]))


def excluded(text, topic):
    return any(phrase_matches(text, term) for term in topic.exclude_keywords)


def relevant_messages(messages, topic):
    """Lexical baseline plus explicit reply inheritance, never unlinked neighbours."""
    direct = {}
    terms = topic_terms(topic)
    for message in messages:
        if not excluded(message.text, topic):
            direct[message.key] = max(direct.get(message.key, 0),
                sum(phrase_matches(message.text, term) for term in terms))
    scores = {key: float(value) for key, value in direct.items() if value}
    by_key = {m.key: m for m in messages}
    changed = True
    while changed:
        changed = False
        for message in messages:
            if message.key in scores or not message.text.strip() or excluded(message.text, topic):
                continue
            parent = f"{message.chat_id}:{message.reply_to}"
            if parent in by_key and parent in scores:
                scores[message.key] = 0.35
                changed = True
    return scores


def cosine(left, right):
    if len(left) != len(right) or not left:
        raise ValueError("Несовместимые размерности embeddings")
    if any(not isinstance(v, (float, int)) or not math.isfinite(v) for v in [*left, *right]):
        raise ValueError("Некорректные значения embeddings")
    scale = math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
    return sum(x*y for x, y in zip(left, right)) / scale if scale else 0.0


class OllamaEmbedder:
    def __init__(self, model, base_url="http://127.0.0.1:11434", timeout=180):
        self.model = model
        self.api = LocalAPI(base_url, timeout)

    def __call__(self, texts):
        result = self.api.request("/api/embed", {"model": self.model, "input": texts, "truncate": False})
        vectors = result.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ValueError("Runtime вернул неверное число embeddings")
        return vectors


@dataclass(frozen=True)
class SearchHit:
    fragment: object
    score: float
    lexical: float
    semantic: float | None


def rank_fragments(fragments, topic, mode="overview", top_k=12, embed=None):
    scores = relevant_messages([m for f in fragments for m in f.messages], topic)
    lexical = [sum(scores.get(key, 0) for key in f.target_keys) for f in fragments]
    semantic = None
    if embed and fragments:
        # Bounded batches avoid sending the whole corpus in one HTTP request.
        query = embed([topic.name + ". " + topic.description])[0]
        semantic = []
        for i in range(0, len(fragments), 16):
            vectors = embed([f.text for f in fragments[i:i+16]])
            semantic.extend(cosine(query, vector) for vector in vectors)
    combined = list(lexical)
    if semantic is not None:
        combined = [0.0] * len(fragments)
        for ranking in ([i for i in sorted(range(len(fragments)), key=lambda i: lexical[i], reverse=True) if lexical[i] > 0],
                        sorted(range(len(fragments)), key=lambda i: semantic[i], reverse=True)):
            for rank, i in enumerate(ranking, 1):
                combined[i] += 1 / (60 + rank)
    hits = [SearchHit(f, combined[i], lexical[i], semantic[i] if semantic is not None else None)
            for i, f in enumerate(fragments)]
    hits.sort(key=lambda hit: (-hit.score, hit.fragment.id))
    return hits if mode == "overview" else [h for h in hits if h.score > 0][:top_k]
