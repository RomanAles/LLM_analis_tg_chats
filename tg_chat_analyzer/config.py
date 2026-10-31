from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Topic:
    name: str
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    synonyms: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or not isinstance(value.get("name"), str) or not value["name"].strip():
            raise ValueError("Тема должна содержать непустое name")
        for key in ("keywords", "exclude_keywords"):
            if key in value and (not isinstance(value[key], list) or
                                 any(not isinstance(x, str) or not x.strip() for x in value[key])):
                raise ValueError(f"Некорректный список {key}")
        aliases = value.get("synonyms", {})
        if not isinstance(aliases, dict) or any(not isinstance(k, str) or not isinstance(v, list)
                or any(not isinstance(x, str) or not x.strip() for x in v) for k, v in aliases.items()):
            raise ValueError("Некорректный synonyms")
        if not isinstance(value.get("description", ""), str):
            raise ValueError("description должен быть строкой")
        return cls(**{key: value[key] for key in cls.__dataclass_fields__ if key in value})

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class AnalysisConfig:
    backend: str = "extractive"
    model: str = "qwen3.5:9b"
    base_url: str = "http://127.0.0.1:11434"
    mode: str = "overview"
    top_k: int = 12
    context_chars: int = 12000
    max_messages: int = 30
    gap_minutes: int = 20
    max_output_tokens: int = 2048
    context_tokens: int = 8192
    temperature: float = 0.0
    timeout: int = 180
    embedding_model: str = ""
    quantize: bool = False

    def __post_init__(self):
        for name in ("backend", "model", "base_url", "mode", "embedding_model"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} должен быть строкой")
        if self.backend not in {"extractive", "ollama", "transformers"}:
            raise ValueError("Неизвестный backend")
        if self.mode not in {"overview", "question"}:
            raise ValueError("Неизвестный mode")
        for name in ("top_k", "max_messages", "gap_minutes", "max_output_tokens", "context_tokens", "timeout"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} должен быть положительным целым")
        if type(self.context_chars) is not int or self.context_chars < 256:
            raise ValueError("context_chars должен быть >= 256")
        if self.max_output_tokens >= self.context_tokens:
            raise ValueError("Бюджет ответа должен быть меньше контекста")
        if self.max_messages > 32:
            raise ValueError("max_messages не должен превышать 32")
        if type(self.quantize) is not bool:
            raise ValueError("quantize должен быть логическим значением")
        if type(self.temperature) not in (float, int) or not 0 <= self.temperature <= 2:
            raise ValueError("temperature должна быть в диапазоне 0–2")

    def to_dict(self):
        return asdict(self)
