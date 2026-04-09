import copy
import shutil
from typing import Annotated
from rich.progress import Progress
from rich.console import Console
import typer
import json
import os
import requests
import subprocess

from src.process import download_process, concat_process, create_concat_list
from src.util import util
from src.util.i18n import set_language, t
from src.SOOP import SOOP, LoginError
from src.model import Manifest


class ProcessError(Exception):
    """
    프로세스 실행 중 오류가 발생했을 때 사용되는 예외 클래스입니다.
    """


QUALITY_MAPPING = ["1440p", "1080p", "720p", "540p", "auto"]
CONFIG_FILENAME = "config.json"
TMP_DIRNAME = "tmp"

console = Console()
app = typer.Typer(
    context_settings={"help_option_names": ["-h", "--help"]},
    add_completion=False,
)


def get_app() -> typer.Typer:
    return app


def say(
    message_key: str, *, style: str | None = None, end: str = "\n", **kwargs
) -> None:
    console.print(t(message_key, **kwargs), style=style, end=end)


def ask(message_key: str, **kwargs) -> bool:
    return typer.confirm(t(message_key, **kwargs))


def prompt_text(message_key: str, **kwargs) -> str:
    return str(typer.prompt(t(message_key, **kwargs), **kwargs))


def normalize_quality(quality: str) -> str:
    normalized = quality.strip().lower()
    if normalized not in QUALITY_MAPPING:
        say(
            "quality.unsupported",
            style="yellow",
            quality_options=", ".join(QUALITY_MAPPING),
        )
        say("quality.fallback", style="yellow")
        return "auto"
    return normalized


def init_config(ffmpeg_path: str) -> dict[str, str]:
    return {
        "username": "",
        "password": "",
        "second_password": "",
        "ffmpeg_path": ffmpeg_path,
    }


def resolve_ffprobe_path(ffmpeg_path: str) -> str | None:
    if ffmpeg_path == "ffmpeg":
        return "ffprobe"

    ffprobe_path = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe")
    if os.path.exists(ffprobe_path):
        return ffprobe_path
    return None


def login_flow(
    config: dict[str, str], use_config: bool
) -> tuple[bool, set[str], dict[str, str]]:
    changed: set[str] = set()

    if not ask("auth.login_prompt"):
        return SOOP.check_auth(), changed, config

    # print()
    if use_config:
        is_logged_in = try_login(config)
    else:
        config, changed_once = get_credential_input(config)
        changed.update(changed_once)
        is_logged_in = try_login(config)

    # print()
    while not is_logged_in and ask("auth.retry_prompt"):
        config, changed_once = get_credential_input(config)
        changed.update(changed_once)
        is_logged_in = try_login(config)
        # print()

    return is_logged_in, changed, config


def select_merge_list() -> str:
    cwd = os.getcwd()
    candidates = sorted(
        [
            os.path.join(root, filename)
            for (root, dir, files) in os.walk(cwd)
            for filename in files
            if filename.startswith("list")
            and filename.endswith(".txt")
            and os.path.isfile(os.path.join(root, filename))
        ]
    )

    if not candidates:
        raise Exception(t("merge.no_list_files"))

    say("merge.list_header")
    for idx, filename in enumerate(candidates, start=1):
        console.print(f"[{idx}] {filename}")

    while True:
        selected = prompt_text("merge.select_prompt")
        try:
            selected_idx = int(selected)
            if 1 <= selected_idx <= len(candidates):
                return os.path.join(cwd, candidates[selected_idx - 1])
        except ValueError:
            pass
        say("merge.invalid_selection", style="yellow")


def resolve_merge_path() -> str:
    while True:
        output_name = prompt_text("merge.output_prompt").strip()
        if output_name:
            break
        say("merge.invalid_output", style="yellow")

    output_path = (
        output_name
        if os.path.isabs(output_name)
        else os.path.join(os.getcwd(), output_name)
    )
    root, ext = os.path.splitext(output_path)
    if not ext:
        output_path = f"{output_path}.mp4"

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    return output_path


@app.command(name=None, help=t("help.app"))
def main(
    language: Annotated[
        str,
        typer.Option(
            "-l",
            "--lang",
            help=t("help.lang"),
            show_default=False,
        ),
    ] = "",
    quality: Annotated[
        str,
        typer.Option("-q", "--quality", help=t("help.quality"), show_default=False),
    ] = "auto",
    use_config: Annotated[
        bool,
        typer.Option(
            "-c", "--config", help=t("help.config"), show_default=False, is_flag=True
        ),
    ] = False,
    ffmpeg_path: Annotated[
        str,
        typer.Option("-f", "--ffmpeg", help=t("help.ffmpeg"), show_default=False),
    ] = "ffmpeg",
    batch: Annotated[
        str,
        typer.Option("-b", "--batch", help=t("help.batch"), show_default=False),
    ] = "",
    keep_temp: Annotated[
        bool,
        typer.Option(
            "-k", "--keep", help=t("help.keep"), show_default=False, is_flag=True
        ),
    ] = False,
    merge: Annotated[
        bool,
        typer.Option(
            "-m",
            "--merge",
            help=t("help.merge"),
            show_default=False,
            is_flag=True,
            # is_eager=True,
            # callback=merge_mode_callback,
        ),
    ] = False,
):
    set_language(language or None)
    say("cli.force_quit", style="yellow")

    # Basic Config & ffmpeg flag
    quality = normalize_quality(quality)
    ffmpeg_path = ffmpeg_path.strip().replace("\\", "/")
    ffmpeg_changed = ffmpeg_path != "ffmpeg"
    config = init_config(ffmpeg_path)

    try:
        if use_config:
            config = handle_config(config)
            ffmpeg_path = config.get("ffmpeg_path", "ffmpeg")

        # print()
        try:
            version = check_ffmpeg_path(ffmpeg_path)
            if "git" in version:
                say("ffmpeg.not_release", style="yellow")
        except ValueError:
            msg = (
                t("ffmpeg.invalid_path", ffmpeg_path=ffmpeg_path)
                if use_config or ffmpeg_changed
                else t("ffmpeg.not_found")
            )
            raise Exception(msg)

        if ffmpeg_changed and ask("ffmpeg.overwrite_config"):
            dump_config(config)

        if merge:
            keep_temp = True
            list_file_path = select_merge_list()
            output_path = resolve_merge_path()

            say("merge.start", list_file=list_file_path)
            proc = concat_process(ffmpeg_path, output_path, list_file_path)
            for _ in util.read_out_time(proc):
                pass
            proc.wait()

            if proc.returncode != 0:
                raise ProcessError(t("error.concat_end"))

            say(
                "merge.complete",
                style="green",
                output_path=output_path.replace("\\", "/"),
            )

            return

        res, changed, config = login_flow(config, use_config)

        if (
            res
            and changed
            and ask(
                "config.save_prompt",
                changed=", ".join(t(item) for item in changed),
            )
        ):
            dump_config(config)

        if batch.strip() != "":
            handle_batch(batch, quality, ffmpeg_path, version, keep_temp=keep_temp)

        # main download loop
        while True:
            url, quality = get_url_input(quality)
            try:
                manifest = get_manifest_wrap(url, quality)
            except (
                ValueError,
                KeyError,
                requests.exceptions.RequestException,
            ):
                # print()
                continue

            download(manifest, ffmpeg_path, version, keep_temp=keep_temp)

    # Handle KeyboardInterrupt gracefully
    except KeyboardInterrupt:
        say("exit.interrupted", style="blue")
        raise typer.Exit(code=0)

    # If any exception occurs, print the error message and exit
    except Exception as e:
        console.print(f"{e}", style="red")
        say("exit.program", style="red")
        raise typer.Exit(code=1)

    finally:
        if not keep_temp:
            tmp_path = os.path.join(os.getcwd(), TMP_DIRNAME)
            if os.path.exists(tmp_path):
                shutil.rmtree(tmp_path)


def handle_batch(
    batch: str, quality: str, ffmpeg: str, version: str, keep_temp: bool = False
) -> bool:
    if not os.path.exists(batch):
        say("batch.file_missing", style="yellow", batch=batch)
        say("batch.exit", style="yellow")
        if not ask("batch.continue_prompt"):
            raise typer.Exit(code=0)

    with open(batch, "r", encoding="utf-8") as f:
        urls = [url.strip() for url in f.readlines() if url.strip()]

    if len(urls) == 0:
        say("batch.empty", style="yellow")
    else:
        for url in urls:
            try:
                manifest = get_manifest_wrap(url, quality)
            except ValueError as e:
                say("error.url_value", style="yellow", error=e)
                say("batch.invalid_url_error", style="yellow", url=url)
                say("batch.next_url", style="yellow")
                continue

            download(manifest, ffmpeg, version, keep_temp=keep_temp)
        # print()
        say("batch.complete")

    return ask("batch.continue_prompt")


def dump_config(config: dict[str, str]) -> None:
    """설정 파일을 현재 작업 디렉토리에 저장합니다."""

    with open(os.path.join(os.getcwd(), CONFIG_FILENAME), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)


def handle_config(default: dict[str, str]) -> dict[str, str]:
    """
    설정 파일을 불러옵니다.
    설정 파일이 존재하지 않으면 새로 생성합니다.

    :param dict default: 기본 설정 값이 담긴 딕셔너리
    :return: 설정 파일에서 불러온 설정 값이 담긴 딕셔너리
    """
    # print()
    config_path = os.path.join(os.getcwd(), CONFIG_FILENAME)
    if not os.path.exists(config_path):
        say("config.missing", style="green")
        try:
            dump_config(default)
            say("config.created", style="green")
        except Exception as e:
            say("config.create_error", style="yellow", error=e)
            if os.path.exists(config_path):
                os.remove(config_path)
        finally:
            return default

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        say("config.loaded", style="green")
        return config


def download(
    manifest: Manifest,
    ffmpeg_path: str,
    version: str = "7.1.1",
    keep_temp: bool = False,
):
    """
    지정된 해상도를 목표로 다운로드를 시작합니다 .
    만약 목표 해상도가 존재하지 않으면 최고 해상도로 다운로드합니다.

    :param manifest: 다운로드할 매니페스트 객체
    :param ffmpeg_path: FFmpeg 실행 파일의 경로
    :param version: FFmpeg 버전 (기본값: "7.1.1")
    :raises ProcessError: 중대한 오류가 발생하여 프로그램을 종료해야 하는 경우
    """

    # print()
    console.print(t("download.start"), style="yellow", end="")
    console.print(manifest.title)
    say("download.stop_hint", style="yellow")
    completed_paths = []

    with Progress() as progress:
        total_duration, tmp_nested_list = download_parts(
            progress, ffmpeg_path, manifest, version
        )

        current_concat = 0
        for partial_duration, tmp_list in tmp_nested_list:
            current_concat += 1
            path = concat_parts(
                progress,
                ffmpeg_path,
                manifest.title,
                tmp_list,
                partial_duration if len(tmp_nested_list) > 1 else total_duration,
                current_concat=current_concat,
                total_concats=len(tmp_nested_list),
            )
            completed_paths.append(path.replace("\\", "/"))

        if not keep_temp:
            for _, tmp_list in tmp_nested_list:
                remove_temp_files(progress, tmp_list)
        progress.stop()

    # console.print()
    console.print(t("download.complete"), style="green", end="")
    for path in completed_paths:
        console.print(path, end="\n")


def get_credential_input(config: dict[str, str]) -> tuple[str, set[str]]:
    """
    사용자로부터 로그인 정보를 입력받습니다.

    :param dict config: 현재 설정을 담고 있는 딕셔너리
    :return: 업데이트된 설정 딕셔너리와 변경된 항목의 집합
    :raises KeyboardInterrupt: 사용자가 입력을 중단한 경우
    """
    changed: set[str] = set()

    prev_conf = copy.deepcopy(config)

    config["username"] = prompt_text("prompt.username")
    config["password"] = prompt_text("prompt.password")
    config["second_password"] = prompt_text(
        "prompt.second_password", default="", show_default=False
    )

    if config["second_password"] != prev_conf["second_password"]:
        changed.add("changed.second_password")
    if config["username"] != prev_conf["username"]:
        changed.add("changed.username")
    if config["password"] != prev_conf["password"]:
        changed.add("changed.password")

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
        say("login.success", style="green")
        return True
    except LoginError as e:
        say("login.failure", style="yellow", error=e)
        return False


def check_ffmpeg_path(ffmpeg_path: str) -> int:
    """
    FFmpeg 경로가 올바른지 확인합니다.

    :param str ffmpeg_path: FFmpeg 실행 파일의 경로
    :return version: FFmpeg가 설치되어 있을 경우 빌드의 버전을 반환합니다.
    :raises ValueError: FFmpeg가 설치되어 있지 않거나 경로가 잘못된 경우
    """
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            check=True,
        )
        version_info = result.stdout.split("\n")[0]
        if "ffmpeg" in version_info:
            if "git" in version_info:
                return version_info.split(" ")[2]
            return version_info.split(" ")[2].split("-")[0]
        raise ValueError
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise ValueError


def download_parts(
    progress: Progress,
    ffmpeg_path: str,
    manifest: Manifest,
    version: str = "7.1.1",
) -> tuple[float, list[tuple[float, list[str]]]]:
    """
    지정된 Manifest의 각 구간을 다운로드합니다.

    :param Progress progress: Rich Progress 객체
    :param str ffmpeg_path: FFmpeg 실행 파일의 경로
    :param Manifest manifest: 다운로드할 Manifest 객체
    :param str version: FFmpeg 버전 (기본값: "7.1.1")
    :return out: 다운로드된 구간의 총 길이 (밀리초 단위)와 임시 파일 목록
    :raises ProcessError: 중대한 오류가 발생하여 프로그램을 종료해야 하는 경우
    """
    session = SOOP.session()
    i = 0
    total_parts = manifest.count()
    total_duration = 0.0
    tmp_nested_tuple_list: list[tuple[float, list[str]]] = []
    tmp_list: list[str] = []

    def _hash(str: str) -> str:
        return abs(hash(str)) % (10**8)

    prev_resolution = None
    partial_duration = 0
    for url, duration, resolution in manifest.items:
        i += 1

        print(resolution, prev_resolution)
        if resolution != prev_resolution and prev_resolution is not None:
            tmp_nested_tuple_list.append((partial_duration, tmp_list))
            partial_duration = 0
            tmp_list = []

        prev_resolution = resolution
        tmp_list.append(
            tmp_path := util.get_unique_filename(
                os.path.join(os.getcwd(), "tmp", f"{_hash(manifest.title)}.ts")
            )
        )

        task = progress.add_task(
            t("process.segment_downloading", current=i, total=total_parts),
            total=duration,
        )
        _proc = download_process(
            ffmpeg_path, url, tmp_path, session=session, version=version
        )

        for out_time in util.read_out_time(_proc):
            if out_time == -1:
                break
            progress.update(task, completed=out_time)

        total_duration += progress._tasks[task].completed
        partial_duration += progress._tasks[task].completed
        _proc.wait()
        ffprobe_path = resolve_ffprobe_path(ffmpeg_path)

        vid_len = (
            util.get_duration_ms(tmp_path, ffprobe_path)
            or progress._tasks[task].completed
        )
        if _proc.returncode != 0:
            progress.update(
                task,
                description=t("process.segment_stopped", current=i, total=total_parts),
                refresh=False,
            )
            raise ProcessError(t("error.download_segment"))

        if vid_len < duration - 300:
            progress.update(
                task,
                description=t("process.segment_stopped", current=i, total=total_parts),
                refresh=False,
            )
            break
        else:
            progress.update(
                task,
                completed=1,
                total=1,
                description=t("process.segment_complete", current=i, total=total_parts),
                refresh=False,
            )

    if tmp_list:
        tmp_nested_tuple_list.append((partial_duration, tmp_list))

    return total_duration, tmp_nested_tuple_list


def concat_parts(
    progress: Progress,
    ffmpeg_path: str,
    title: str,
    parts: list[str],
    total_duration: float = 0.0,
    current_concat: int = 1,
    total_concats: int = 1,
) -> str:
    """
    지정된 비디오 파트들을 병합하여 하나의 비디오 파일로 만듭니다.

    :param Progress progress: Rich Progress 객체
    :param str ffmpeg_path: FFmpeg 실행 파일의 경로
    :param str title: 최종 비디오 파일의 제목
    :param list parts: 병합할 비디오 파트들의 경로 리스트
    :param float total_duration: 전체 비디오의 총 길이 (밀리초 단위)
    :param int current_concat: 현재 병합 작업의 순서 (예: 1, 2, ...)
    :param int total_concats: 전체 병합 작업의 총 개수
    :return path: 병합된 비디오 파일의 경로
    :raises ProcessError: 중대한 오류가 발생하여 프로그램을 종료해야 하는 경우
    """

    task = progress.add_task(
        t("process.mergeing", current=current_concat, total=total_concats),
        total=total_duration,
    )
    path = util.get_unique_filename(
        os.path.join(os.getcwd(), f"{util.delete_spec_char(title)}.mp4")
    )

    try:
        list_file = create_concat_list(parts)
        _proc = concat_process(ffmpeg_path, path, list_file)
    except Exception:
        raise ProcessError(t("error.concat_failed"))

    for out_time in util.read_out_time(_proc):
        if out_time == -1:
            break
        progress.update(task, completed=out_time)

    _proc.wait()
    if _proc.returncode != 0:
        progress.update(
            task,
            description=t(
                "process.merge_stopped", current=current_concat, total=total_concats
            ),
            refresh=False,
        )
        raise ProcessError(t("error.concat_end"))

    if progress._tasks[task].completed < total_duration - 100:
        progress.update(
            task,
            description=t(
                "process.merge_stopped", current=current_concat, total=total_concats
            ),
            refresh=False,
        )
    else:
        progress.update(
            task,
            completed=100,
            total=100,
            description=t(
                "process.merge_complete", current=current_concat, total=total_concats
            ),
            refresh=False,
        )
    return path


def remove_temp_files(progress: Progress, tmp_list: list[str]):
    """
    임시 파일을 제거합니다. 제거에 실패할 경우 경고 메시지를 출력하고, 사용자가 직접 제거하도록 안내합니다.

    :param Progress progress: Rich Progress 객체
    :param list tmp_list: 제거할 임시 파일 목록
    """
    task = progress.add_task(t("process.cleanup"), total=len(tmp_list))
    try:
        for part in tmp_list:
            os.remove(part)
            progress.update(task, advance=1)
        progress.update(
            task,
            completed=len(tmp_list),
            description=t("process.cleanup_complete"),
            refresh=False,
        )
    except OSError as e:
        progress.update(task, description=t("process.cleanup_failed"), refresh=False)
        say("process.cleanup_error", style="yellow", error=e)
        say("process.cleanup_manual", style="yellow")


def get_url_input(quality_d: str | None = "auto"):
    """
    사용자로부터 다운로드할 VOD의 URL을 입력받습니다.

    :return url: 입력받은 URL
    :raises KeyboardInterrupt: 사용자가 입력을 중단한 경우
    """

    # print()
    url = str(
        typer.prompt(
            t("prompt.vod_input"),
            default="",
            show_default=False,
        )
    ).strip()
    if url == "":
        raise KeyboardInterrupt

    if len(url.split(maxsplit=1)) < 2:
        return url, quality_d

    if url.split()[1] in QUALITY_MAPPING:
        return url.split()[0], url.split()[1]

    say(
        "quality.unsupported_input",
        style="yellow",
        quality_options=", ".join(QUALITY_MAPPING),
    )
    return url.split()[0], quality_d


def get_manifest_wrap(url: str, quality: str) -> Manifest:
    """
    Manifest를 가져오는 래퍼 함수입니다.

    :param str url: VOD의 player_url
    :param str quality: 원하는 비디오 품질 (예: "1080p", "auto")
    :return: Manifest 객체
    """
    try:
        return SOOP.get_manifest(url, quality)
    except ValueError as e:
        say("error.url_value", style="yellow", error=e)
        say("manifest.invalid_url", style="yellow")
        raise
    except KeyError as e:
        say("manifest.vod_info_invalid", style="red", error=e)
        say("manifest.vod_no_access", style="red")
        say("manifest.login_state", style="red")
        raise
    except requests.exceptions.RequestException as e:
        say("manifest.network_error", style="red", error=e)
        say("manifest.network_check", style="red")
        raise


if __name__ == "__main__":
    app(prog_name="")
