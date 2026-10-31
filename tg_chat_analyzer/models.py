from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Message:
    chat_id: str
    id: int
    date: str
    author: str
    author_id: str | None
    text: str
    reply_to: int | None = None
    thread_id: int | None = None
    attachment: str | None = None
    content_hash: str = ""

    @property
    def key(self):
        return f"{self.chat_id}:{self.id}"

    @property
    def anchor(self):
        from .config import fingerprint
        return "source-" + fingerprint([self.chat_id, self.id])[:20]

    def to_dict(self):
        return {**asdict(self), "key": self.key, "anchor": self.anchor}


@dataclass(frozen=True)
class Fragment:
    id: str
    chat_id: str
    messages: tuple[Message, ...]
    target_keys: tuple[str, ...]
    relation: str
    truncated: bool = False

    @property
    def text(self):
        return "\n".join(f"[{m.key}] {m.author}: {m.text}" for m in self.messages)

    def to_dict(self):
        return {"id": self.id, "chat_id": self.chat_id, "target_keys": list(self.target_keys),
                "relation": self.relation, "truncated": self.truncated,
                "messages": [m.to_dict() for m in self.messages]}
