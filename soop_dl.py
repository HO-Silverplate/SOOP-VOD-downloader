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

# Login Status
LOGGED_IN = 1
LOGGED_OUT = -1

class title(str): ...
class url(str): ...
class duration(int): ...

console = Console()
app = typer.Typer(context_settings={"help_option_names": ["-h", "--help"]},add_completion=False,)


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

def read_out_time(proc: subprocess.Popen) -> Generator[int, None, None]:
    """
    FFmpeg 프로세스의 stdout에서 out_time_ms 값을 읽어 밀리초 단위로 반환합니다.
    """
    while True:
        line = proc.stdout.readline()
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

def _parse_title_no(url: str) -> int:
    """
    주어진 URL에서 VOD의 고유번호를 추출합니다.
    """
    url_args = urllib.parse.urlparse(url.strip())

    if (not "vod.sooplive.co.kr" in url_args.netloc) or (not "player" in url_args.path):
        raise ValueError()
    try:
        return int(url_args.path.split("/")[1])
    except:
        raise ValueError()

def _get_manifest_urls(
    session: requests.Session, title_no: int, quality: str | None = None
) -> tuple[title | None, list[tuple[url,duration]] | None]:
    """
    VOD 정보를 요청하고, 원하는 품질의 마니페스트 URL 리스트를 반환합니다.
    """
    
    vod_url_list: list[str] = []
    res = session.post(
        VOD_API,
        data={
            "nTitleNo": title_no,
            "nApiLevel": "10",
            "nPlaylistidx": "0",
        },
    )
    res.raise_for_status()
    data: dict = res.json().get("data", None)

    if (quality == "auto" or quality is None or quality == "자동") or (
        quality not in QUALITY_MAPPING
    ):
        desired_quality = f'{data["file_resolution"].split("x")[-1]}p'
    elif quality in QUALITY_MAPPING:
        desired_quality = quality

    objlist = data["files"]
    for file_dict in objlist:
        for fileset in file_dict["quality_info"]:
            if fileset["label"] == desired_quality:
                vod_url_list.append((fileset["file"], file_dict["duration"]))

    title: str = data["title"]

    return title, vod_url_list


def get_download_process(
    ffmpeg_path: str,
    url: str,
    dir,file,
    session: requests.Session | None = requests.Session(),
):
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
        "-v","quiet",
        "-stats",
        "-progress",
        "pipe:1",
        "-threads",
        "0",
        path,
    ]

    proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=sys.stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return path,proc


def get_concat_process(ffmpeg_path: str, dir: str, file:str, part_list: list[str]):
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
        "-v","quiet",
        "-stats",
        "-progress",
        "pipe:1",
        "-threads",
        "0",
        export_path,
    ]

    proc = subprocess.Popen(
        concat_cmd, 
        stdin=sys.stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return export_path,proc

def load_config(path: str) -> dict[str, str]:
    """
    설정 파일을 불러옵니다.
    """
    if not os.path.exists(path) or not os.path.exists(os.path.join(os.getcwd(),path)):
        raise OSError()
    with open(path, "r") as f:
        config = json.load(f)

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
    SOOP에 로그인합니다.
    """
    if _check_auth(session):
        return True

    else:
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
        except:
            console.print("로그인 실패: 서버에 연결할 수 없습니다.",style="yellow")
            return False

        match response.json().get("RESULT", 1024):
            case 1:
                return _check_auth(session)

            case -1:
                console.print(
                    "로그인 실패: 등록되지 않은 아이디이거나, 아이디 또는 비밀번호를 잘못 입력하셨습니다.", style="yellow"
                )
                return False

            case -3:
                console.print("로그인 실패: 아이디/패스워드 입력이 잘못되었습니다.",style="yellow")
                return False

            case -10:
                console.print(
                    "로그인 실패: 아이디의 비정상적인 로그인(대량 접속 등)이 확인되어 접속이 차단되었습니다.",style="yellow"
                )
                return False

            case -11:
                return _sec_login(session, username, password, sec_password)

            case _:
                console.print("로그인 실패: SOOP에 로그인할 수 없습니다.",style="yellow")
                return False


def _sec_login(session: requests.Session, username: str, password: str) -> bool:
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
                "szPassword": password,
                "szScriptVar": "oLoginRet",
                "isSaveId": "false",
                "isLoginRetain": "Y",
            },
        )
        response.raise_for_status()
    except:
        console.print("서버에 연결할 수 없습니다.")
        return False
    if response.status_code == 200 and response.json().get("RESULT", 0) == 1:
        return True
    else:
        console.print("2차 인증에 실패했습니다.")
        return False


def session_setup(config: dict[str, str]) -> requests.Session:
    """
    세션 기본 정보를 설정하고 로그인합니다.
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    username, password, second_password = (
        config.get(k, "") for k in ["username", "password", "second_password"]
    )

    if username != "" and password != "":
        if _login(session, username, password, second_password):
            console.print("로그인 성공", style="green")

    return session

@app.command(name=None,help="SOOP VOD를 다운로드할 수 있는 유틸리티입니다.")
def main(
    url: Annotated[str, typer.Argument(help="SOOP VOD URL",show_default=False)],
    output_path: Annotated[str, typer.Option("-p","--path",help="영상의 저장 경로 (.mp4)", show_default=False,file_okay=True, dir_okay=True)]=None,
    quality:
        Annotated[
            str,
            typer.Option(
                "-q",
                "--quality",
                help="""
            목표 비디오 품질\n
            목표하는 품질이 존재하지 않을 경우 최고 품질로 다운로드합니다.\n
            auto: 최고 품질\n
            options: 1440p, 1080p, 720p, 540p, 360p, auto
            """,
                show_default=False,
            ),
        ]
        = "auto",
    config_path:
        Annotated[
            str,
            typer.Option("-c","--config", help="설정 파일(config.json) 경로 (.json)", show_default=False),
        ]
        = None,
    ffmpeg_path: Annotated[
        str,
        typer.Option("-f","--ffmpeg", help="FFmpeg.exe 경로",show_default=False),
    ] = "ffmpeg",
):
    config = {
        "username": "",
        "password": "",
        "second_password": "",
        "ffmpeg_path": ffmpeg_path,
    }

    print()
    if config_path is None:
        doLogin = typer.confirm("로그인하시겠습니까?")

        if doLogin:
            saved = ["닉네임","비밀번호"]
            config["username"] = typer.prompt("아이디")
            config["password"] = typer.prompt("비밀번호")
            
            config["second_password"] = typer.prompt(
                "2차 비밀번호 (없으면 Enter)", default="", show_default=False
            )
            if config["second_password"] != "":
                saved.append("2차 비밀번호")
            if ffmpeg_path != "ffmpeg":
                saved.append("FFmpeg 경로")

            print()
            if typer.confirm(f"설정을 저장할까요? 다음과 같은 설정이 변경되었습니다: {', '.join(saved)}"):
                config_path = os.path.join(os.getcwd(), "config.json")
                with open(config_path, "w") as f:
                    json.dump(config, f, indent=4)
    else:
        try:
            config = load_config(config_path)
        except Exception as e:
            console.print(f"설정 파일을 불러오는 중 오류가 발생하였습니다: {e}", style="red")
            console.print("프로그램을 종료합니다.", style="red")
            typer.Exit(code=1)
            return
    
        if ffmpeg_path != "ffmpeg":
            typer.confirm(f"FFmpeg 경로 설정이 감지되었습니다. 설정 파일을 덮어쓸까요?\n\n설정 정보는 config.json 파일에 저장됩니다.")
    
    print()
    session = session_setup(config)
    print()
    console.print("다운로드를 시작하는 중...", style="yellow")
    console.print("다운로드를 중단하시려면 Q를 입력하세요.",style="yellow")
    console.print("또는 Ctrl+C를 입력하여 프로그램을 강제 종료할 수 있습니다.",style="yellow")
    print()

    if output_path:
        output_path = os.path.abspath(os.path.join(os.getcwd(),output_path))
        dir = os.path.dirname(output_path)
        file = os.path.basename(output_path)
    else:
        dir = os.getcwd()
        file = f"{title}.mp4"
    
    try:
        title_no = _parse_title_no(url)
    except:
        console.print("유효하지 않은 URL입니다.", err=True)
        console.print("SOOP VOD 플레이어 URL이 맞는지 확인해 주세요.")
        console.print("프로그램을 종료합니다.")
        typer.Exit(code=1)
        return
    try:
        title, vod_list = _get_manifest_urls(session, title_no, quality)
    except KeyError as e:
        console.print("VOD 정보가 잘못되었습니다.", err=True)
        console.print("1. URL이 올바른지 확인해주세요.")
        console.print("2. 로그인 상태를 확인해주세요.")
        console.print("프로그램을 종료합니다.")
        typer.Exit(code=1)
        return
    except requests.exceptions.RequestException as e:
        console.print("서버에 연결할 수 없습니다.", err=True)
        console.print("네트워크 연결을 확인해주세요.")
        console.print("프로그램을 종료합니다.")
        typer.Exit(code=1)
        return

    part_list = []
    total_parts = len(vod_list)
    total_duration = 0
    i = 0
    with Progress() as progress:
        try:
            for (url,duration) in vod_list:
                i+=1
                _path, _proc = get_download_process(ffmpeg_path, url, dir,file, session=session)
                part_list.append(_path)
                
                task = progress.add_task(f"{i}/{total_parts}구간 다운로드 중...", total=duration)
                out_time = 0.0

                for out_time in read_out_time(_proc):
                    if out_time == -1:
                        break
                    progress.update(task, completed=out_time)
                if out_time != -1 and out_time < duration - 1:
                    progress.update(task, description=f"{i}/{total_parts}구간 다운로드 중단", refresh=False)
                    total_duration += progress.tasks[i-1].completed
                    break
                else:
                    progress.update(task, completed=duration, total = duration, description=f"{i}/{total_parts}구간 다운로드 완료",refresh=False)
            _proc.wait()
            _proc.terminate()
            
            if _proc.returncode != 0:
                raise RuntimeError()
        except:
            console.print(f"{i}/{total_parts} 구간 다운로드 중 오류가 발생하였습니다.", style="red")
            console.print("프로그램을 종료합니다.",style="red")
            typer.Exit(code=1)
            return

        try:
            _path, _proc = get_concat_process(ffmpeg_path, dir, file, part_list)
        except Exception as e:
            console.print(f"영상을 병합하는 중 오류가 발생하였습니다: {e}", style="red")
            console.print("프로그램을 종료합니다.", style="red")
            typer.Exit(code=1)
            return
        
        task = progress.add_task("영상 합치는 중...", total=total_duration)
        out_time = 0.0
        for out_time in read_out_time(_proc):
            if out_time == -1:
                break
            progress.update(task, completed=out_time)
            
        if out_time != -1 and out_time < total_duration - 1:
            progress.update(task, description="영상 병합 중단", refresh=False)
        else:
            progress.update(
                task,
                completed = 100,
                total = 100,
                description=f"영상 병합 완료",
                refresh=False
            )
        
        _proc.wait()
        _proc.terminate()
        if _proc.returncode != 0:
            console.print("영상을 합치는 중 오류가 발생하였습니다.", style="red")
            
        task = progress.add_task("임시 파일 정리 중...", total=len(part_list))
        for part in part_list:
            try:
                os.remove(part)
                progress.update(task, advance=1)
            except OSError as e:
                console.print(f"임시 파일 제거 중 오류가 발생하였습니다. 직접 제거해 주세요.", style="red")
                typer.Exit(code=1)
                return
        progress.update(task, completed=len(part_list), description="임시 파일 정리 완료", refresh=False)
        progress.stop()
        console.print()
        console.print(f"다운로드가 완료되었습니다: {os.path.abspath(_path)}",style="green")
        console.print()

if __name__ == "__main__":
    app(prog_name="")