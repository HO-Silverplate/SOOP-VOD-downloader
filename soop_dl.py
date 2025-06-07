import copy
from dataclasses import dataclass
import re
import sys
from typing import Annotated, Generator
from rich.progress import Progress
from rich.console import Console
import typer
import json
import os
import requests
import urllib.parse
import tempfile
import subprocess

VOD_API = "https://api.m.sooplive.co.kr/station/video/a/view"
LOGIN_API = "https://login.sooplive.co.kr/app/LoginAction.php"
LOGOUT_API = "https://login.sooplive.co.kr/app/LogOut.php"
CHECK_API = "https://afevent2.sooplive.co.kr/api/get_private_info.php"

QUALITY_MAPPING = {
    "1440p": 5,
    "1080p": 4,
    "720p": 3,
    "540p": 2,
    "360p": 1,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://play.sooplive.co.kr/",
    "Origin": "https://play.sooplive.co.kr",
}

HELP_STRINGS = [
    "SOOP VOD를 다운로드할 수 있는 유틸리티입니다.",
    "목표 비디오 품질을 설정합니다.\n목표하는 품질이 존재하지 않을 경우 최고 품질로 다운로드합니다.\noptions: 1440p, 1080p, 720p, 540p, auto",
    "설정 파일을 사용합니다. \n설정 파일이 존재하지 않으면 새로 생성합니다.",
    "출력에 사용되는 ffmpeg.exe의 경로를 지정합니다.",
    "FFmpeg의 -threads 0 옵션을 사용합니다.\nCPU 사용량이 증가할 수 있습니다.",
]

# Login Status
LOGGED_IN = 1
LOGGED_OUT = -1


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


@dataclass
class Manifest:
    title: Types.title
    url_list: list[Types.player_url] = (None,)
    duration_list: list[Types.duration] = (None,)

    def set_title(self, value: Types.title):
        """매니페스트의 제목을 설정합니다.
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
    def list(self) -> list[tuple[Types.url, Types.duration]]:
        """
        URL과 Duration의 튜플 리스트를 반환합니다.
        """
        return list(zip(self.url_list, self.duration_list))


class LoginError(Exception):
    """
    로그인 오류를 나타내는 예외 클래스입니다.
    """


console = Console()
app = typer.Typer(
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


def get_unique_filename(file_path: str) -> str:
    """
    중복되는 파일명을 회피하고 파일명으로 사용할 수 없는 특수문자를 제거합니다.
    """
    # 파일 경로를 디렉토리, 파일명, 확장자로 분리
    directory, filename = os.path.split(file_path)
    name, ext = os.path.splitext(filename)

    name = _delete_spec_char(name)

    counter = 1
    unique_path = file_path
    while os.path.exists(unique_path):
        unique_path = os.path.join(directory, f"{name}({counter}){ext}")
        counter += 1

    return unique_path


def _delete_spec_char(string: str):
    return re.sub(r'[\/:*?"<>|]', "", string)


def _read_out_time(proc: subprocess.Popen) -> Generator[int, None, None]:
    """
    FFmpeg 프로세스의 stdout에서 out_time_ms 값을 읽어 밀리초 단위로 반환합니다.
    """
    while True:
        line: str = proc.stdout.readline()
        line = line.strip()
        if not line:
            yield -1
            break
        line = line.strip()
        if line.startswith("out_time_ms"):
            out_time = int(line.split("=")[1]) // 1000
            yield out_time
        elif line.startswith("progress") and "end" in line:
            yield -1
            break


def _get_manifest_urls(
    session: requests.Session, url: str, quality: str | None = None
) -> Manifest:
    """
    VOD 정보를 요청하고, 원하는 품질의 URL 매니페스트를 반환합니다.\n
    매니페스트가 비었거나 파싱에 실패하면 KeyError를 발생시킵니다.\n
    유효하지 않은 URL이라면 ValueError를 발생시킵니다.

    :param session: requests.Session 객체
    :param url: VOD의 player_url
    :param quality: 원하는 비디오 품질 (예: "1080p", "auto")
    :return: Manifest 객체, VOD 제목과 URL 리스트가 포함됨
    :raises KeyError: VOD 정보가 비어있거나 파싱에 실패한 경우
    :raises ValueError: 유효하지 않은 URL인 경우
    :raises requests.exceptions.RequestException: 서버에 연결할 수 없는 경우
    """

    url = Types.player_url(url)

    manifest = Manifest()
    res = session.post(
        VOD_API,
        data={
            "nTitleNo": url.title_no,
            "nApiLevel": "10",
            "nPlaylistidx": "0",
        },
    )
    res.raise_for_status()
    data: dict = res.json().get("data", None)

    if (quality == "auto" or quality is None or quality == "자동") or (
        quality not in QUALITY_MAPPING
    ):
        desired_quality = f'{str(data["file_resolution"]).split("x")[-1]}p'
    elif quality in QUALITY_MAPPING:
        desired_quality = quality

    objlist = data["files"]
    for file_dict in objlist:
        for fileset in dict(file_dict["quality_info"]):
            if str(fileset["resolution"]).split("x")[-1] == desired_quality[:-1]:
                manifest.add_vod(fileset["file"], file_dict["duration"])

    manifest.set_title(data["title"])

    if manifest.count() == 0:
        raise KeyError("Manifest Empty.")

    return manifest


def _get_download_process(
    ffmpeg_path: str,
    url: str,
    dir,
    file,
    session: requests.Session | None = requests.Session(),
    turbo: bool = False,
) -> tuple[str, subprocess.Popen]:
    """
    다운로드 프로세스를 생성하고, 임시 파일 경로와 프로세스를 반환합니다.
    """
    path = get_unique_filename(os.path.join(dir, "tmp", file))

    headers = {}
    cookies = session.cookies.get_dict()
    if not os.path.exists(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))

    for k, v in session.headers.items():
        if k.lower() not in ["content-length", "content-encoding"]:
            headers[k] = v

    header_args = []
    for k, v in headers.items():
        header_args.extend(["-headers", f"{k}: {v}"])
    for k, v in cookies.items():
        header_args.extend(["-headers", f"Cookie: {k}={v}"])

    ffmpeg_cmd = [
        ffmpeg_path,
        *header_args,
        "-i",
        url,
        "-c",
        "copy",
        "-movflags",
        "faststart+frag_keyframe",
        "-f",
        "mp4",
        "-v",
        "quiet",
        "-stats",
        "-progress",
        "pipe:1",
        path,
    ]

    if turbo:
        ffmpeg_cmd.append("-threads")
        ffmpeg_cmd.append("0")

    proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=sys.stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return path, proc


def _get_concat_process(
    ffmpeg_path: str, dir: str, file: str, part_list: list[str], turbo: bool = False
) -> tuple[str, subprocess.Popen]:
    """
    병합 프로세스를 생성하고, 최종 파일 경로와 프로세스를 반환합니다.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".txt", encoding="utf-8"
    ) as tmp:
        for part in part_list:
            tmp.write(f"file '{os.path.abspath(part)}'\n")
        tmp_path = tmp.name

    if not os.path.exists(dir):
        os.makedirs(dir)

    export_path = get_unique_filename(os.path.join(dir, file))

    concat_cmd = [
        ffmpeg_path,
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        tmp_path,
        "-c",
        "copy",
        "-threads",
        "0",
        "-y",
        "-v",
        "quiet",
        "-stats",
        "-progress",
        "pipe:1",
        export_path,
    ]

    if turbo:
        concat_cmd.append("-threads")
        concat_cmd.append("0")

    proc = subprocess.Popen(
        concat_cmd,
        stdin=sys.stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return export_path, proc


def handle_config(
    default: dict | None = {
        "username": "",
        "password": "",
        "second_password": "",
        "ffmpeg_path": "ffmpeg",
    }
) -> dict[str, str]:
    """
    설정 파일을 불러옵니다.
    """
    print()
    config_path = os.path.join(os.getcwd(), "config.json")
    if not os.path.exists(config_path):
        console.print("설정 파일을 찾을 수 없습니다. 새로 생성합니다.", style="green")
        try:
            with open(config_path, "w") as f:
                json.dump(default, f, indent=4)
            console.print("설정 파일을 성공적으로 생성했습니다.", style="green")
        except Exception as e:
            console.print(
                f"설정 파일을 생성하는 중 오류가 발생했습니다: {e}", style="yellow"
            )
            if os.path.exists(config_path):
                os.remove(config_path)
            return default
    else:
        with open(config_path, "r") as f:
            config = json.load(f)
            console.print(f"설정 파일을 성공적으로 불러왔습니다.", style="green")
            return config


def _check_auth(session: requests.Session) -> bool:
    """
    세션이 SOOP에 로그인되어 있는지 확인합니다.
    """
    try:
        res = session.get(CHECK_API, timeout=2)
        res.raise_for_status()
        return res.json()["CHANNEL"]["IS_LOGIN"] == LOGGED_IN
    except:
        return False


def _login(
    session: requests.Session,
    username: str | None = "",
    password: str | None = "",
    sec_password: str | None = "",
) -> bool:
    """
    SOOP에 로그인하고 결과를 반환합니다.
    로그인에 성공하면 True를 반환하고, 실패하면 LoginError 예외를 발생시킵니다.

    :param session: requests.Session 객체
    :param username: SOOP 아이디
    :param password: SOOP 비밀번호
    :param sec_password: SOOP 2차 비밀번호 (선택 사항)

    :return: 로그인 성공 여부 (True/False)
    :raises LoginError: 로그인 실패 시 예외를 발생시킵니다.

    """
    if _check_auth(session):
        return True

    response = session.post(
        LOGIN_API,
        data={
            "szWork": "login",
            "szType": "json",
            "szUid": username,
            "szPassword": password,
            "szScriptVar": "oLoginRet",
            "isSaveId": "false",
            "isSavePw": "false",
            "isSaveJoin": "false",
            "isLoginRetain": "Y",
        },
    )
    try:
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        msg = f"서버에 연결할 수 없습니다 - {e}"

    match response.json().get("RESULT", 1024):
        case 1:
            return _check_auth(session)
        case -1:
            msg = "등록되지 않은 아이디이거나, 아이디 또는 비밀번호를 잘못 입력하셨습니다."
        case -3:
            msg = "아이디가 비활성화되었습니다."
        case -10:
            msg = "아이디의 비정상적인 로그인(대량 접속 등)이 확인되어 접속이 차단되었습니다."
        case -11:
            return _sec_login(session, username, sec_password)
        case _:
            msg = "SOOP에 로그인할 수 없습니다."
    raise LoginError(msg)


def _sec_login(session: requests.Session, username: str, sec_password: str) -> bool:
    """
    2차 인증을 수행합니다.
    """
    try:
        response = session.post(
            LOGIN_API,
            data={
                "szWork": "second_login",
                "szType": "json",
                "szUid": username,
                "szPassword": sec_password,
                "szScriptVar": "oLoginRet",
                "isSaveId": "false",
                "isLoginRetain": "Y",
            },
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        msg = f"서버에 연결할 수 없습니다 - {e}"

    if response.status_code == 200 and response.json().get("RESULT", 0) == 1:
        return True
    else:
        msg = "2차 인증에 실패했습니다."

    raise LoginError(msg)


def session_setup(
    config: dict[str, str], doLogin: bool
) -> tuple[requests.Session, bool]:
    """
    세션 기본 정보를 설정하고 로그인합니다.
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    username, password, second_password = (
        config.get(k, "") for k in ["username", "password", "second_password"]
    )

    res = True
    if doLogin:
        try:
            res = _login(session, username, password, second_password)
            console.print("로그인 성공", style="green")
        except LoginError as e:
            console.print(f"로그인 실패: {e}", style="yellow")
            res = False

    return session, res


@app.command(name=None, help=HELP_STRINGS[0])
def main(
    quality: Annotated[
        str,
        typer.Option("-q", "--quality", help=HELP_STRINGS[1], show_default=False),
    ] = "auto",
    use_config: Annotated[
        bool,
        typer.Option(
            "-c", "--config", help=HELP_STRINGS[2], show_default=False, is_flag=True
        ),
    ] = False,
    ffmpeg_path: Annotated[
        str, typer.Option("-f", "--ffmpeg", help=HELP_STRINGS[3], show_default=False)
    ] = "ffmpeg",
    turbo: Annotated[
        bool,
        typer.Option(
            "-t", "--turbo", help=HELP_STRINGS[4], show_default=False, is_flag=True
        ),
    ] = False,
):
    try:
        # Basic Config
        config = {
            "username": "",
            "password": "",
            "second_password": "",
            "ffmpeg_path": ffmpeg_path.replace("\\", "/"),
        }
        console.print("프로그램을 강제종료하려면 Ctrl+C를 입력하세요.", style="yellow")

        if turbo:
            console.print("고성능 모드가 활성화되었습니다.", style="magenta")

        # Load & overwrite config if given -c Flag
        if use_config:
            config = handle_config(config)

        try:
            # Check if ffmpeg_path is valid
            ffmpeg_path = config.get("ffmpeg_path", "ffmpeg").replace("\\", "/")
            result = subprocess.run(
                [ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
            )

            if "ffmpeg" not in result.stdout:
                raise RuntimeError()

        except (RuntimeError, FileNotFoundError, subprocess.CalledProcessError):
            if use_config:
                console.print(
                    f"FFmpeg 경로가 잘못되었습니다: {ffmpeg_path}\nFFmpeg를 설치하거나 올바른 경로를 지정해주세요.",
                    style="red",
                )
            else:
                console.print(
                    """
                    FFmpeg를 찾는 데 실패하였습니다.\n
                    FFmpeg를 설치하거나 직접 경로를 지정해주세요.\n
                    -c 옵션으로 설정 파일을 불러오거나 -f 옵션으로 경로를 직접 지정할 수 있습니다.
                    """,
                    style="red",
                )

            typer.Exit(code=1)
            return

        # If ffmpeg_path is set & valid, ask to overwrite config
        if ffmpeg_path != "ffmpeg":
            print()
            typer.confirm(f"FFmpeg 경로 설정이 감지되었습니다. 설정 파일을 덮어쓸까요?")
            with open(os.path.join(os.getcwd(), "config.json"), "w") as f:
                json.dump(config, f, indent=4)

        saved: set = set()
        if use_config:
            # if config used, automatically try logging in
            doLogin = True
        else:
            # if config is not used, ask for login info
            print()
            if doLogin := typer.confirm("로그인하시겠습니까?"):
                print()
                saved.add("닉네임")
                saved.add("비밀번호")
                config = login_form(config)

                if config["second_password"] != "":
                    saved.add("2차 비밀번호")

        # Try setting up session
        print()
        session, res = session_setup(config, doLogin)
        while not res and typer.confirm("로그인을 다시 시도할까요?"):
            print()
            config_tmp = copy.deepcopy(config)

            _translate_matrix = {
                "username": "아이디",
                "password": "비밀번호",
                "second_password": "2차 비밀번호",
            }
            config = login_form(config)
            for k in config_tmp:
                if config_tmp[k] != config[k]:
                    saved.add(_translate_matrix[k])

            session, res = session_setup(config)
            if res:
                break

        print()
        if (
            res[1]
            and len(saved) > 0
            # If Login was successful & Auth params changed, ask to save config
            and typer.confirm(
                f"설정을 저장할까요? 다음과 같은 설정이 변경되었습니다: {', '.join(saved)}"
            )
        ):
            print()
            with open(os.path.join(os.getcwd(), "config.json"), "w") as f:
                json.dump(config, f, indent=4)
            console.print(f"설정 파일을 저장했습니다", style="green")

        while True:
            print()
            url = typer.prompt(
                "다운로드할 VOD의 URL을 입력하세요. (종료하려면 Enter)",
                default="",
                show_default=False,
            )

            try:
                manifest = _get_manifest_urls(session, url, quality)
            except ValueError as e:
                print()
                console.print(e, style="red")
                console.print(
                    "SOOP VOD 플레이어 URL이 맞는지 확인해 주세요.", style="red"
                )
                console.print("프로그램을 종료합니다.", style="Blue")
                typer.Exit(code=0)
                raise
            except KeyError as e:
                print()
                console.print(f"VOD 정보가 잘못되었습니다: {e}", style="red")
                console.print("로그인 또는 성인인증 상태를 확인해주세요.", style="red")
                raise
            except requests.exceptions.RequestException as e:
                print()
                console.print(
                    f"정보를 불러오는 중 오류가 발생했습니다: {e}", style="red"
                )
                console.print("네트워크 연결을 확인해주세요.", style="red")
                raise

            download(
                manifest,
                ffmpeg_path=config["ffmpeg_path"],
                session=session,
                turbo=turbo,
            )
    except Exception as e:
        console.print(f"{e}", style="red")
        console.print("프로그램을 종료합니다.", style="red")
        typer.Exit(code=1)
        return


def download(
    manifest: Manifest, ffmpeg_path: str, session: requests.Session, turbo: bool
) -> bool:
    """
    다운로드를 수행합니다.
    """

    print()
    console.print("다운로드를 시작하는 중...", style="yellow")
    console.print("다운로드를 중단하려면 Q를 입력하세요.", style="yellow")

    dir = os.getcwd()
    file = _delete_spec_char(f"{manifest.title}.mp4")

    part_list = []
    total_parts = manifest.count()
    total_duration = 0
    i = 0
    with Progress() as progress:
        try:
            for url, duration in manifest.list:
                i += 1
                _path, _proc = _get_download_process(
                    ffmpeg_path, url, dir, file, session=session, turbo=turbo
                )
                part_list.append(_path)

                task = progress.add_task(
                    f"{i}/{total_parts}구간 다운로드 중...", total=duration
                )
                out_time = 0.0

                for out_time in _read_out_time(_proc):
                    if out_time == -1:
                        break
                    progress.update(task, completed=out_time)

                if progress._tasks[task].completed < duration - 1:
                    total_duration += progress._tasks[task].completed
                    progress.update(
                        task,
                        description=f"{i}/{total_parts}구간 다운로드 중단",
                        refresh=False,
                    )
                    break
                else:
                    progress.update(
                        task,
                        completed=duration,
                        total=duration,
                        description=f"{i}/{total_parts}구간 다운로드 완료",
                        refresh=False,
                    )
        except Exception as e:
            print()
            console.print(
                f"{i}/{total_parts} 구간 다운로드 중 오류가 발생하였습니다.",
                style="red",
            )
            console.print(e, style="red")
            console.print("프로그램을 종료합니다.", style="red")
            typer.Exit(code=1)
            return True

        try:
            _path, _proc = _get_concat_process(
                ffmpeg_path, dir, file, part_list, turbo=turbo
            )
        except Exception as e:
            console.print(f"영상을 병합하는 중 오류가 발생하였습니다: {e}", style="red")
            console.print("프로그램을 종료합니다.", style="red")
            typer.Exit(code=1)
            return True

        task = progress.add_task("영상 합치는 중...", total=total_duration)
        out_time = 0.0
        for out_time in _read_out_time(_proc):
            if out_time == -1:
                break
            progress.update(task, completed=out_time)

        if progress._tasks[task].completed < total_duration - 1:
            progress.update(task, description="영상 병합 중단", refresh=False)
        else:
            progress.update(
                task,
                completed=100,
                total=100,
                description=f"영상 병합 완료",
                refresh=False,
            )

        task = progress.add_task("임시 파일 정리 중...", total=len(part_list))
        try:
            for part in part_list:
                os.remove(part)
                progress.update(task, advance=1)
            progress.update(
                task,
                completed=len(part_list),
                description="임시 파일 정리 완료",
                refresh=False,
            )
        except OSError as e:
            console.print(
                f"임시 파일 제거 중 오류가 발생하였습니다. 직접 제거해 주세요.",
                style="red",
            )
            progress.update(task, description="임시 파일 정리 실패", refresh=False)
            typer.Exit(code=1)
            return True
        finally:
            progress.stop()

        console.print()
        console.print(f"다운로드가 완료되었습니다: ", style="green", end="")
        console.print(os.path.abspath(_path).replace("\\", "/"))
        console.print()


def login_form(config: dict[str, str]) -> dict[str, str]:
    config["username"] = typer.prompt("아이디")
    config["password"] = typer.prompt("비밀번호")

    config["second_password"] = typer.prompt(
        "2차 비밀번호 (없으면 Enter)", default="", show_default=False
    )
    return config


if __name__ == "__main__":
    app(prog_name="")
