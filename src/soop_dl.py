import copy
import sys
from typing import Annotated
from rich.progress import Progress
from rich.console import Console
import typer
import json
import os
import requests
import tempfile
import subprocess

from util import util
from SOOP import SOOP, LoginError
from model import Manifest

HELP_STRINGS = [
    "SOOP VOD를 다운로드할 수 있는 유틸리티입니다.",
    "목표 비디오 품질을 설정합니다.\n목표하는 품질이 존재하지 않을 경우 최고 품질로 다운로드합니다.\noptions: 1440p, 1080p, 720p, 540p, auto",
    "설정 파일을 사용합니다. \n설정 파일이 존재하지 않으면 새로 생성합니다.",
    "출력에 사용되는 ffmpeg.exe의 경로를 지정합니다.",
    "FFmpeg의 -threads 0 옵션을 사용합니다.\nCPU 사용량이 증가할 수 있습니다.",
]


console = Console()
app = typer.Typer(
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


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
    path = util.get_unique_filename(os.path.join(dir, "tmp", file))

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

    export_path = util.get_unique_filename(os.path.join(dir, file))

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


def try_login(config: dict[str, str], doLogin: bool) -> bool:
    """
    SOOP에 로그인을 시도합니다.
    """
    username, password, second_password = (
        config.get(k, "").strip() for k in ["username", "password", "second_password"]
    )

    res = True
    if doLogin:
        try:
            res = SOOP.login(username, password, second_password)
            console.print("로그인 성공", style="green")
        except LoginError as e:
            console.print(f"로그인 실패: {e}", style="yellow")
            res = False

    return res


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
                print()

        # Try setting up session
        print()
        while not (res := try_login(config, doLogin)) and typer.confirm(
            "로그인을 다시 시도할까요?"
        ):
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

            if res := try_login(config, doLogin):
                break

        print()
        if (
            res
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
            if url == "":
                console.print("프로그램을 종료합니다.", style="blue")
                typer.Exit(code=0)
                return

            try:
                manifest = SOOP.get_manifest(url, quality)
            except ValueError as e:
                print()
                console.print(f"ValueError: {e}", style="red")
                console.print(
                    "SOOP VOD 플레이어 URL이 맞는지 확인해 주세요.", style="red"
                )
                return
            except KeyError as e:
                print()
                console.print(f"VOD 정보가 잘못되었습니다: {e}", style="red")
                console.print("로그인 또는 성인인증 상태를 확인해주세요.", style="red")
                return
            except requests.exceptions.RequestException as e:
                print()
                console.print(
                    f"정보를 불러오는 중 오류가 발생했습니다: {e}", style="red"
                )
                console.print("네트워크 연결을 확인해주세요.", style="red")
                return

            download(
                manifest,
                ffmpeg_path=config["ffmpeg_path"],
                turbo=turbo,
            )
    except Exception as e:
        console.print(f"{e}", style="red")
        console.print("프로그램을 종료합니다.", style="red")
        typer.Exit(code=1)
        return


def download(manifest: Manifest, ffmpeg_path: str, turbo: bool) -> bool:
    """
    다운로드를 수행합니다.
    """
    session = SOOP.session()

    print()
    console.print("다운로드를 시작하는 중...", style="yellow")
    console.print("다운로드를 중단하려면 Q를 입력하세요.", style="yellow")

    dir = os.getcwd()
    file = util.delete_spec_char(f"{manifest.title}.mp4")

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

                for out_time in util.read_out_time(_proc):
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
        for out_time in util.read_out_time(_proc):
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
