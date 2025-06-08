from dataclasses import dataclass, field
from src.model import Types


@dataclass
class Manifest:
    title: Types.title | None = ""
    url_list: list[Types.player_url] = field(default_factory=list)
    duration_list: list[Types.duration] = field(default_factory=list)

    def set_title(self, value: Types.title):
        """
        매니페스트의 제목을 설정합니다.

        :param value: VOD의 제목
        """
        self.title = value

    def add_vod(self, url: Types.player_url, duration: Types.duration):
        """
        매니페스트에 VOD를 추가합니다.

        :param url: VOD의 URL
        :param duration: VOD의 길이 (밀리초 단위)
        """
        self.url_list.append(url)
        self.duration_list.append(duration)

    def count(self) -> int:
        """
        매니페스트에 포함된 VOD의 개수를 반환합니다.
        """
        return min(len(self.duration_list), len(self.url_list))

    def is_empty(self) -> bool:
        """
        매니페스트가 비어있는지 확인합니다.
        """
        return self.count() == 0

    def duration(self) -> Types.duration:
        """
        전체 VOD의 총 길이를 반환합니다.
        """
        return sum(self.duration_list)

    @property
    def items(self) -> list[tuple[Types.url, Types.duration]]:
        """
        URL과 Duration의 튜플 리스트를 반환합니다.
        """
        return list(zip(self.url_list, self.duration_list))
