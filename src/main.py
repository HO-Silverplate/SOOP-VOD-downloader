import copy
from typing import Annotated
from rich.progress import Progress
from rich.console import Console
import typer
import json
import os
import requests
import subprocess

from src.process import download_process, concat_process
from src.util import util
from src.SOOP import SOOP, LoginError
from src.model import Manifest


class ProcessError(Exception):
    """
    프로세스 실행 중 오류가 발생했을 때 사용되는 예외 클래스입니다.
    """


HELP = [
    "SOOP VOD를 다운로드할 수 있는 유틸리티입니다.",
    "|  목표 비디오 품질을 설정합니다.\n\n|  목표하는 품질이 존재하지 않을 경우 최고 품질로 다운로드합니다.\n\n|  Options: 1440p, 1080p, 720p, 540p, auto\n\n|",
    "|  설정 파일을 사용합니다. \n\n|  설정 파일이 존재하지 않으면 새로 생성합니다.\n\n|",
    "|  출력에 사용되는 ffmpeg.exe의 경로를 지정합니다. \n\n|",
    "|  FFmpeg의 -threads 0 옵션을 사용합니다.\n\n|  CPU 사용량이 증가할 수 있습니다.\n\n|",
]

FFMPEG_ERR = [
    "FFmpeg 경로가 잘못되었습니다: {ffmpeg_path}\nFFmpeg를 설치하거나 올바른 경로를 지정해주세요.",
    "FFmpeg를 찾는 데 실패하였습니다.\nFFmpeg를 설치하거나 직접 경로를 지정해주세요.\n-c 옵션으로 설정 파일을 불러오거나 -f 옵션으로 경로를 직접 지정할 수 있습니다.",
]

QUALITY_MAPPING = ["1440p", "1080p", "720p", "540p", "auto"]

console = Console()
app = typer.Typer(
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


def get_app() -> typer.Typer:
    return app


@app.command(name=None, help=HELP[0])
def main(
    quality: Annotated[
        str,
        typer.Option("-q", "--quality", help=HELP[1], show_default=False),
    ] = "auto",
    use_config: Annotated[
        bool,
        typer.Option("-c", "--config", help=HELP[2], show_default=False, is_flag=True),
    ] = False,
    ffmpeg_path: Annotated[
        str,
        typer.Option("-f", "--ffmpeg", help=HELP[3], show_default=False),
    ] = "ffmpeg",
    turbo: Annotated[
        bool,
        typer.Option("-t", "--turbo", help=HELP[4], show_default=False, is_flag=True),
    ] = False,
):
    console.print("프로그램을 강제종료하려면 Ctrl+C를 입력하세요.", style="yellow")
    if turbo:
        console.print("고성능 모드가 활성화되었습니다.", style="magenta")

    # Basic Config & ffmpeg flag
    quality = quality.strip().lower()
    if quality not in QUALITY_MAPPING:
        console.print(
            f"지원하지 않는 품질입니다.\n지원하는 품질: {QUALITY_MAPPING}",
            style="yellow",
        )
        console.print("자동으로 최고 품질로 설정합니다.", style="yellow")

    ffmpeg_path = ffmpeg_path.strip().replace("\\", "/")
    ffmpeg_changed = ffmpeg_path != "ffmpeg"
    config = {
        "username": "",
        "password": "",
        "second_password": "",
        "ffmpeg_path": ffmpeg_path,
    }

    try:
        # Load & overwrite config if given -c Flag
        if use_config:
            config = handle_config(config)
            ffmpeg_path = config["ffmpeg_path"]

        # Check if ffmpeg_path is valid
        # if unvalid, raise Exception with error message
        print()
        if check_ffmpeg_path(ffmpeg_path):
            if ffmpeg_changed and typer.confirm(
                f"FFmpeg 경로 설정이 감지되었습니다. 설정 파일을 덮어쓸까요?"
            ):
                dump_config(config)
        else:
            msg = (
                FFMPEG_ERR[0].format(ffmpeg_path=ffmpeg_path)
                if use_config
                else FFMPEG_ERR[1]
            )
            raise Exception(msg)

        # If ffmpeg_path is set & valid, ask to overwrite config

        # handle login
        # If use_config is True, try to login with config
        # If not, ask for login credentials
        # when login fails, ask for retry
        changed = set()
        if typer.confirm("로그인하시겠습니까?"):
            print()
            if use_config:
                res = try_login(config)
            else:
                config, changed = get_credential_input(config, changed)
                res = try_login(config)
                print()
            while not res and typer.confirm("로그인을 다시 시도할까요?"):
                print()
                config, changed = get_credential_input(config, changed)
                res = try_login(config)
                print()
        else:
            res = SOOP.check_auth()

        # If Login was successful & Auth params changed, ask to save config
        __flag = res and (len(changed) > 0)
        if __flag and typer.confirm(
            f"설정을 저장할까요? 다음과 같은 설정이 변경되었습니다: {', '.join(changed)}"
        ):
            print()
            dump_config(config)

        # main download loop
        print()
        while True:
            download(
                quality,
                ffmpeg_path=config["ffmpeg_path"],
                turbo=turbo,
            )

    # Handle KeyboardInterrupt gracefully
    except KeyboardInterrupt:
        console.print("프로그램이 중단되었습니다.", style="blue")
        typer.Exit(code=0)
        return

    # If any exception occurs, print the error message and exit
    except Exception as e:
        console.print(f"{e}", style="red")
        console.print("프로그램을 종료합니다.", style="red")
        typer.Exit(code=1)
        return


def dump_config(config: dict[str, str]) -> None:
    """설정 파일을 현재 작업 디렉토리에 저장합니다."""

    with open(os.path.join(os.getcwd(), "config.json"), "w") as f:
        json.dump(config, f, indent=4)
    console.print(f"설정 파일을 저장했습니다", style="green")


def handle_config(default: dict[str, str]) -> dict[str, str]:
    """
    설정 파일을 불러옵니다.
    설정 파일이 존재하지 않으면 새로 생성합니다.

    :param default: 기본 설정 값이 담긴 딕셔너리
    :return: 설정 파일에서 불러온 설정 값이 담긴 딕셔너리
    """
    print()
    config_path = os.path.join(os.getcwd(), "config.json")
    if not os.path.exists(config_path):
        console.print("설정 파일을 찾을 수 없습니다. 새로 생성합니다.", style="green")
        try:
            dump_config(default)
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


def download(quality: str, ffmpeg_path: str, turbo: bool):
    """
    지정된 해상도를 목표로 다운로드를 시작합니다 .
    만약 목표 해상도가 존재하지 않으면 최고 해상도로 다운로드합니다.

    :param quality: 다운로드할 비디오의 목표 해상도
    :param ffmpeg_path: FFmpeg 실행 파일의 경로
    :param turbo: 고성능 모드 활성화 여부
    :raises ProcessError: 중대한 오류가 발생하여 프로그램을 종료해야 하는 경우
    """
    url = get_url_input()
    manifest = get_manifest_wrap(url, quality)

    print()
    console.print(f"다운로드를 시작하는 중: ", style="yellow", end="")
    console.print(manifest.title)
    console.print("다운로드를 중단하려면 Q를 입력하세요.", style="yellow")

    with Progress() as progress:
        total_duration, tmp_list = download_parts(
            progress, ffmpeg_path, manifest, turbo
        )

        path = concat_parts(
            progress,
            ffmpeg_path,
            manifest.title,
            turbo,
            tmp_list,
            total_duration,
        )

        remove_temp_files(progress, tmp_list)
        progress.stop()

    console.print()
    console.print(f"다운로드가 완료되었습니다: ", style="green", end="")
    console.print(path.replace("\\", "/"), end="\n\n")


def get_credential_input(config: dict[str, str], changed: set) -> tuple[str, str]:
    """
    사용자로부터 로그인 정보를 입력받습니다.

    :param config: 현재 설정을 담고 있는 딕셔너리
    :param changed: 변경된 설정 항목을 담는 집합
    :return: 업데이트된 설정 딕셔너리와 변경된 항목의 집합
    :raises KeyboardInterrupt: 사용자가 입력을 중단한 경우
    """
    prev_conf = copy.deepcopy(config)

    config["username"] = typer.prompt("아이디")
    config["password"] = typer.prompt("비밀번호")
    config["second_password"] = typer.prompt(
        "2차 비밀번호 (없으면 Enter)", default="", show_default=False
    )

    if config["second_password"] != prev_conf["second_password"]:
        changed.add("2차 비밀번호")
    if config["username"] != prev_conf["username"]:
        changed.add("닉네임")
    if config["password"] != prev_conf["password"]:
        changed.add("비밀번호")

    return config, changed


def try_login(config: dict[str, str]) -> bool:
    """
    SOOP에 로그인을 시도합니다.
    """
    username = config.get("username", "").strip()
    password = config.get("password", "").strip()
    second_password = config.get("second_password", "").strip()

    try:
        SOOP.login(username, password, second_password)
        console.print("로그인 성공", style="green")
        return True
    except LoginError as e:
        console.print(f"로그인 실패: {e}", style="yellow")
        return False


def check_ffmpeg_path(ffmpeg_path: str) -> bool:
    """
    FFmpeg 경로가 올바른지 확인합니다.

    :param ffmpeg_path: FFmpeg 실행 파일의 경로
    :return: FFmpeg가 설치되어 있고, 경로가 올바른 경우 True, 그렇지 않으면 False
    """
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            check=True,
        )
        return "ffmpeg" in result.stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def download_parts(
    progress: Progress, ffmpeg_path: str, manifest: Manifest, turbo: bool
) -> tuple[float, list[str]]:
    """
    지정된 Manifest의 각 구간을 다운로드합니다.

    :param progress: Rich Progress 객체
    :param ffmpeg_path: FFmpeg 실행 파일의 경로
    :param manifest: 다운로드할 Manifest 객체
    :param turbo: 고성능 모드 활성화 여부
    :return: 다운로드된 구간의 총 길이 (밀리초 단위)와 임시 파일 목록
    :raises ProcessError: 중대한 오류가 발생하여 프로그램을 종료해야 하는 경우
    """
    session = SOOP.session()
    i = 0
    total_parts = manifest.count()
    total_duration = 0.0
    tmp_list = []

    for url, duration in manifest.items:
        i += 1
        tmp_list.append(
            tmp_path := util.get_unique_filename(
                os.path.join(os.getcwd(), "tmp", f"{manifest.title}.mp4")
            )
        )

        task = progress.add_task(
            f"{i}/{total_parts}구간 다운로드 중...", total=duration
        )
        _proc = download_process(
            ffmpeg_path, url, tmp_path, session=session, turbo=turbo
        )

        for out_time in util.read_out_time(_proc):
            if out_time == -1:
                break
            progress.update(task, completed=out_time)

        total_duration += progress._tasks[task].completed
        _proc.wait()
        if _proc.returncode != 0:
            progress.update(
                task, description=f"{i}/{total_parts}구간 다운로드 중단", refresh=False
            )
            raise ProcessError(
                "구간 다운로드 중 오류가 발생하였습니다. FFmpeg 경로가 올바른지 확인해 주세요."
            )

        if progress._tasks[task].completed < duration - 1:
            progress.update(
                task,
                description=f"{i}/{total_parts}구간 다운로드 중단",
                refresh=False,
            )
            break
        else:
            progress.update(
                task,
                completed=1,
                total=1,
                description=f"{i}/{total_parts}구간 다운로드 완료",
                refresh=False,
            )

    return total_duration, tmp_list


def concat_parts(
    progress: Progress,
    ffmpeg_path: str,
    title: str,
    turbo: bool,
    list: list[str],
    total_duration: float = 0.0,
) -> str:
    """
    지정된 비디오 파트들을 병합하여 하나의 비디오 파일로 만듭니다.

    :param progress: Rich Progress 객체
    :param ffmpeg_path: FFmpeg 실행 파일의 경로
    :param title: 최종 비디오 파일의 제목
    :param turbo: 고성능 모드 활성화 여부
    :param list: 병합할 비디오 파트들의 경로 리스트
    :param total_duration: 전체 비디오의 총 길이 (밀리초 단위)
    :return: 병합된 비디오 파일의 경로
    :raises ProcessError: 중대한 오류가 발생하여 프로그램을 종료해야 하는 경우
    """
    task = progress.add_task("영상 합치는 중...", total=total_duration)
    path = util.get_unique_filename(os.path.join(os.getcwd(), f"{title}.mp4"))

    try:
        _proc = concat_process(ffmpeg_path, path, list, turbo=turbo)
    except Exception as e:
        raise ProcessError("영상을 병합하는 중 오류가 발생하였습니다.")

    for out_time in util.read_out_time(_proc):
        if out_time == -1:
            break
        progress.update(task, completed=out_time)

    _proc.wait()
    if _proc.returncode != 0:
        progress.update(task, description="영상 병합 중단", refresh=False)
        raise ProcessError(
            "영상 병합 중 오류가 발생하였습니다. FFmpeg 경로가 올바른지 확인해 주세요."
        )

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
        return path


def remove_temp_files(progress: Progress, tmp_list: list[str]):
    """
    임시 파일을 제거합니다. 제거에 실패할 경우 경고 메시지를 출력하고, 사용자가 직접 제거하도록 안내합니다.
    :param progress: Rich Progress 객체
    :param tmp_list: 제거할 임시 파일 목록
    """
    task = progress.add_task("임시 파일 정리 중...", total=len(tmp_list))
    try:
        for part in tmp_list:
            os.remove(part)
            progress.update(task, advance=1)
        progress.update(
            task,
            completed=len(tmp_list),
            description="임시 파일 정리 완료",
            refresh=False,
        )
    except OSError as e:
        progress.update(task, description="임시 파일 정리 실패", refresh=False)
        console.print(f"임시 파일 제거 중 오류가 발생하였습니다: {e}", style="yellow")
        console.print("/tmp 폴더의 임시 파일을 직접 제거해 주세요.", style="yellow")


def get_url_input():
    """
    사용자로부터 다운로드할 VOD의 URL을 입력받습니다.

    :return: 입력받은 URL
    :raises KeyboardInterrupt: 사용자가 입력을 중단한 경우
    """

    url = str(
        typer.prompt(
            "다운로드할 VOD의 URL을 입력하세요. (종료하려면 Enter)",
            default="",
            show_default=False,
        )
    ).strip()
    if url == "":
        raise KeyboardInterrupt
    else:
        return url


def get_manifest_wrap(url, quality):
    """
    Manifest를 가져오는 래퍼 함수입니다.

    :param url: VOD의 player_url
    :param quality: 원하는 비디오 품질 (예: "1080p", "auto")
    :return: Manifest 객체
    """
    try:
        return SOOP.get_manifest(url, quality)
    except ValueError as e:
        console.print(f"ValueError: {e}", style="red")
        console.print("SOOP VOD 플레이어 URL이 맞는지 확인해 주세요.", style="red")
        raise Exception()
    except KeyError as e:
        console.print(f"VOD 정보가 잘못되었습니다: {e}", style="red")
        console.print("로그인 또는 성인인증 상태를 확인해주세요.", style="red")
        raise Exception()
    except requests.exceptions.RequestException as e:
        console.print(f"정보를 불러오는 중 오류가 발생했습니다: {e}", style="red")
        console.print("네트워크 연결을 확인해주세요.", style="red")
        raise Exception()


if __name__ == "__main__":
    app(prog_name="")
