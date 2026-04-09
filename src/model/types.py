from dataclasses import dataclass
import urllib.parse

from src.util.i18n import t


class TitleType(str): ...


class UrlType:
    def __init__(self, value: str):
        parsed = urllib.parse.urlparse(value)
        self.__netloc = parsed.netloc
        self.__path = parsed.path
        self.__path_parts = parsed.path.split("/")

    @property
    def netloc(self) -> str:
        return self.__netloc

    @property
    def path(self) -> str:
        return self.__path

    @property
    def path_parts(self) -> list[str]:
        return self.__path_parts


class PlayerUrl(UrlType):
    __title_no: int = None

    def __init__(self, value: str):
        super().__init__(value)
        self.__validate__()
        try:
            player_idx = self.path_parts.index("player")
            self.__title_no = int(self.path_parts[player_idx + 1])
        except (ValueError, IndexError):
            raise ValueError(t("error.vod_id_not_found"))

    def __validate__(self) -> None:
        """유효한 player_url인지 확인합니다."""
        if "player" not in self.path_parts or "vod.sooplive" not in self.netloc:
            raise ValueError(t("error.invalid_player_url"))

    @property
    def title_no(self) -> int:
        return self.__title_no


class VodUrl(UrlType): ...


class DurationType(int): ...


class ResolutionType(str): ...
