from dataclasses import dataclass, field
from src.model import UrlType, DurationType, ResolutionType, TitleType, PlayerUrl


@dataclass
class Manifest:
    title: TitleType | None = ""
    _items: list[tuple[UrlType, DurationType, ResolutionType]] = field(
        default_factory=list
    )
    # url_list: list[Types.player_url] = field(default_factory=list)
    # duration_list: list[Types.duration] = field(default_factory=list)

    def set_title(self, value: TitleType):
        """
        매니페스트의 제목을 설정합니다.

        :param value: VOD의 제목
        """
        self.title = value

    def add_vod(
        self,
        url: PlayerUrl,
        duration: DurationType,
        resolution: ResolutionType,
    ):
        """
        매니페스트에 VOD를 추가합니다.

        :param url: VOD의 URL
        :param duration: VOD의 길이 (밀리초 단위)
        :param resolution: VOD의 해상도
        """
        self._items.append((url, duration, resolution))

    def count(self) -> int:
        """
        매니페스트에 포함된 VOD의 개수를 반환합니다.
        """
        return len(self._items)

    def is_empty(self) -> bool:
        """
        매니페스트가 비어있는지 확인합니다.
        """
        return len(self._items) == 0

    def duration(self) -> DurationType:
        """
        전체 VOD의 총 길이를 반환합니다.
        """
        return sum(duration for _, duration, _ in self._items)

    @property
    def items(self) -> list[tuple[UrlType, DurationType, ResolutionType]]:
        """
        URL, Duration, Resolution의 튜플 리스트를 반환합니다.
        """
        return self._items
