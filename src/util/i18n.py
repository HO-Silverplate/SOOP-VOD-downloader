from __future__ import annotations

import json
import locale
import sys
from functools import lru_cache
from pathlib import Path


def _sanitize_locale_tag(language: str | None) -> str:
    return (language or "").strip()


def _get_system_language() -> str | None:
    try:
        locale_name = locale.getdefaultlocale()[0]
    except (ValueError, TypeError):
        locale_name = None

    resolved = _sanitize_locale_tag(locale_name)
    return resolved or None


DEFAULT_LANGUAGE = _get_system_language()


def get_assets_root() -> Path:
    """현재 실행 환경에 맞는 assets 루트를 반환합니다."""

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).resolve().parents[2] / "assets"


@lru_cache(maxsize=None)
def load_messages(language: str | None = None) -> dict[str, str]:
    """지정한 언어의 메시지 사전을 불러옵니다."""

    requested = _sanitize_locale_tag(language or DEFAULT_LANGUAGE)
    assets_root = get_assets_root()
    candidates: list[Path] = []

    if requested:
        candidates.append(assets_root / "lang" / f"{requested}.json")

    candidates.append(assets_root / "lang" / "en_US.json")

    for path in candidates:
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                return json.load(file)

    raise FileNotFoundError("언어 파일을 찾을 수 없습니다.")


class Translator:
    def __init__(self, language: str | None = None):
        self.set_language(language)

    def set_language(self, language: str | None) -> None:
        self._language = _sanitize_locale_tag(language or DEFAULT_LANGUAGE) or "en_US"
        self._messages = load_messages(self._language)

    @property
    def language(self) -> str:
        return self._language

    def text(self, key: str, **kwargs) -> str:
        message = self._messages.get(key, key)
        if kwargs:
            return message.format(**kwargs)
        return message


translator = Translator()


def set_language(language: str | None) -> None:
    translator.set_language(language)


def t(key: str, **kwargs) -> str:
    return translator.text(key, **kwargs)
