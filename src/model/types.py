from dataclasses import dataclass
import urllib.parse


class Types:
    class title(str): ...

    @dataclass
    class url(str):
        __parsed: urllib.parse.ParseResult = None
        __netloc: str = None
        __path: str = None
        __path_parts: list[str] = None

        def __new__(cls, value: str):
            return super().__new__(cls, value.strip())

        def __init__(self, value: str):
            super().__init__()
            self.__parsed = urllib.parse.urlparse(value.strip())
            self.__netloc = self.__parsed.netloc
            self.__path = self.__parsed.path
            self.__path_parts = self.__parsed.path.split("/")

        @property
        def parsed(self) -> urllib.parse.ParseResult:
            return self.__parsed

        @property
        def netloc(self) -> str:
            return self.__netloc

        @property
        def path(self) -> str:
            return self.__path

        @property
        def path_parts(self) -> list[str]:
            return self.__path_parts

    @dataclass
    class player_url(url):
        __title_no: int = None

        def __init__(self, value: str):
            super().__init__(value)
            self.__validate__()
            try:
                player_idx = self.path_parts.index("player")
                self.__title_no = int(self.path_parts[player_idx + 1])
            except (ValueError, IndexError):
                raise ValueError("VOD 고유번호를 찾을 수 없습니다.")

        def __validate__(self) -> None:
            """유효한 player_url인지 확인합니다."""
            if (
                "player" not in self.path_parts
                or "vod.sooplive.co.kr" not in self.netloc
            ):
                raise ValueError("유효하지 않은 URL입니다.")

        @property
        def title_no(self) -> int:
            return self.__title_no

    @dataclass
    class vod_url(url): ...

    class duration(int): ...
