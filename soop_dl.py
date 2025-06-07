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
        return int(url_args.path.split("/")[2])
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
            if fileset["resolution"].split("x")[-1] == desired_quality[:-1]:
                vod_url_list.append((fileset["file"], file_dict["duration"]))

    title: str = data["title"]

    return title, vod_url_list


def get_download_process(
    ffmpeg_path: str,
    url: str,
    dir,file,
    session: requests.Session | None = requests.Session(),
    turbo: bool = False
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
        "-v","quiet",
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
    return path,proc


def get_concat_process(ffmpeg_path: str, dir: str, file:str, part_list: list[str],turbo:bool = False) -> tuple[str, subprocess.Popen]:
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
    return export_path,proc

def load_config(path: str) -> dict[str, str]:
    """
    설정 파일을 불러옵니다.
    """
    if not os.path.exists(path) or not os.path.exists(os.path.join(os.getcwd(),path)):
        raise FileNotFoundError()
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
                return _sec_login(session, username, sec_password)

            case _:
                console.print("로그인 실패: SOOP에 로그인할 수 없습니다.",style="yellow")
                return False


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
    except:
        console.print("서버에 연결할 수 없습니다.", style="yellow")
        return False
    if response.status_code == 200 and response.json().get("RESULT", 0) == 1:
        return True
    else:
        console.print("2차 인증에 실패했습니다.", style="yellow")
        return False


def session_setup(config: dict[str, str]) -> tuple[requests.Session, bool]:
    """
    세션 기본 정보를 설정하고 로그인합니다.
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    username, password, second_password = (
        config.get(k, "") for k in ["username", "password", "second_password"]
    )

    res = True
    if username != "" and password != "":
        if res:=_login(session, username, password, second_password):
            console.print("로그인 성공", style="green")

    return session, res

@app.command(name=None,help="SOOP VOD를 다운로드할 수 있는 유틸리티입니다.")
def main(
    quality:
        Annotated[
            str,
            typer.Option(
                "-q",
                "--quality",
                help="""
            목표 비디오 품질을 설정합니다.\n
            목표하는 품질이 존재하지 않을 경우 최고 품질로 다운로드합니다.\n
            options: 1440p, 1080p, 720p, 540p, auto
            """,
                show_default=False,
            ),
        ]
        = "auto",
    use_config:
        Annotated[
            bool,
            typer.Option("-c","--config", help="설정 파일을 사용합니다.\n설정파일이 존재하지 않으면 새로 생성합니다.", show_default=False,is_flag=True),
        ]
        = False,
    ffmpeg_path: Annotated[
        str,
        typer.Option("-f","--ffmpeg", help="출력에 사용되는 ffmpeg.exe의 경로를 지정합니다.",show_default=False),
    ] = "ffmpeg",
    turbo: Annotated[
        bool,
        typer.Option(
            "-t",
            "--turbo",
            help="FFmpeg의 -threads 0 옵션을 사용합니다. \nCPU 사용량이 증가할 수 있습니다.",
            show_default=False,
            is_flag=True,
        ),] = False,
):
    try:
        config = {
            "username": "",
            "password": "",
            "second_password": "",
            "ffmpeg_path": ffmpeg_path,
        }
        
        if turbo:
            console.print("고성능 모드가 활성화되었습니다.", style="magenta")
        
        if use_config:
            try:
                config = load_config("config.json")
                console.print(f"설정 파일을 성공적으로 불러왔습니다.", style="green")
            except FileNotFoundError:
                console.print("설정 파일을 찾을 수 없습니다. 새로 생성합니다.", style="green")
                use_config = os.path.join(os.getcwd(), "config.json")
                with open(use_config, "w") as f:
                    json.dump(config, f, indent=4)
            except Exception as e:
                console.print(f"설정 파일을 불러오는 중 오류가 발생하였습니다: {e}", style="red")
                console.print("프로그램을 종료합니다.", style="red")
                typer.Exit(code=1)
                return
        
            if ffmpeg_path != "ffmpeg":
                typer.confirm(f"FFmpeg 경로 설정이 감지되었습니다. 설정 파일을 덮어쓸까요?\n\n설정 정보는 config.json 파일에 저장됩니다.")
                with open(os.path.join(os.getcwd(), "config.json"), "w") as f:
                    json.dump(config, f, indent=4)
        
        try:
            ffmpeg_path = config.get("ffmpeg_path","ffmpeg").replace("\\", "/")
            result = subprocess.run(
                [ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
            )
            if "ffmpeg" not in result.stdout:
                raise RuntimeError()
        except (RuntimeError,FileNotFoundError, subprocess.CalledProcessError) as e:
            if use_config:
                console.print(f"FFmpeg 경로가 잘못되었습니다: {ffmpeg_path}", style="red")
                console.print("FFmpeg를 설치하거나 올바른 경로를 지정해주세요.", style="red")
                typer.Exit(code=1)
                return
            else:
                console.print("FFmpeg를 찾는 데 실패하였습니다.", style="red")
                console.print("FFmpeg를 설치하거나 직접 경로를 지정해주세요.", style="red")
                console.print("config.json 파일을 이용하거나 -f 옵션을 이용해 경로를 지정할 수 있습니다.", style="red")
                typer.Exit(code=1)
                return

        saved:set = set()
        if not use_config:
            console.print("프로그램을 종료하려면 Ctrl+C를 입력하세요.", style="yellow")
            print()
            doLogin = typer.confirm("로그인하시겠습니까?")

            if doLogin:
                saved.add("닉네임")
                saved.add("비밀번호")
                config = login_form(config)

                if config["second_password"] != "":
                    saved.add("2차 비밀번호")

        if config.get(ffmpeg_path,"ffmpeg") != "ffmpeg":
            saved.add("FFmpeg 경로")
        
        print()
        while not (res := session_setup(config))[1] and typer.confirm("로그인을 다시 시도할까요?"):
            print()
            saved.add("닉네임")
            saved.add("비밀번호")
            sec_tmp = config.get("second_password", "")
            config = login_form(config)
            if config["second_password"] != sec_tmp and config["second_password"] != "":
                saved.add("2차 비밀번호")
            print()
        session = res[0]
        print()
        
        if saved.__len__() != 0 and typer.confirm(f"설정을 저장할까요? 다음과 같은 설정이 변경되었습니다: {', '.join(saved)}"):
            use_config = os.path.join(os.getcwd(), "config.json")
            with open(use_config, "w") as f:
                json.dump(config, f, indent=4)
            print()
        
        while True:
            url = typer.prompt(
                "다운로드할 VOD의 URL을 입력하세요 (종료하려면 Enter)",
                default="",
                show_default=False,
            ).strip()
            if url == "":
                print()
                console.print("프로그램을 종료합니다.", style="Blue")
                typer.Exit(code=0)
                return
            if download(
                url,
                ffmpeg_path=config["ffmpeg_path"],
                quality=quality,
                session=session,
                turbo=turbo,
            ) == True:
                return
    except Exception as e:
        console.print(f"{e}", style="red")
        console.print("프로그램을 종료합니다.", style="red")
        typer.Exit(code=1)
        return
        
def download(url:str, ffmpeg_path: str, quality: str, session: requests.Session, turbo:bool):
    print()
    console.print("다운로드를 시작하는 중...", style="yellow")
    console.print("다운로드를 중단하려면 Q를 입력하세요.",style="yellow")
    print()
    try:
        title_no = _parse_title_no(url)
    except:
        console.print("유효하지 않은 URL입니다.", style="red")
        console.print("SOOP VOD 플레이어 URL이 맞는지 확인해 주세요.", style="red")
        print()
        return
    try:
        title, vod_list = _get_manifest_urls(session, title_no, quality)
    except KeyError as e:
        console.print("VOD 정보가 잘못되었습니다.", style="red")
        console.print("1. URL이 올바른지 확인해주세요.", style="red")
        console.print("2. 로그인 상태를 확인해주세요.", style="red")
        print()
        return
    except requests.exceptions.RequestException as e:
        console.print("서버에 연결할 수 없습니다.", style="red")
        console.print("네트워크 연결을 확인해주세요.", style="red")
        print()
        return
    
    dir = os.getcwd()
    file = _delete_spec_char(f"{title}.mp4")

    part_list = []
    total_parts = len(vod_list)
    total_duration = 0
    i = 0
    with Progress() as progress:
        try:
            if total_parts == 0:
                raise ValueError()
        except ValueError:
            console.print("VOD 정보가 없습니다. 로그인, 성인인증 여부를 확인해 주세요.", style="yellow")
            return
            
        try:
            for (url,duration) in vod_list:
                i+=1
                _path, _proc = get_download_process(ffmpeg_path, url, dir,file, session=session, turbo=turbo)
                part_list.append(_path)
                
                task = progress.add_task(f"{i}/{total_parts}구간 다운로드 중...", total=duration)
                out_time = 0.0

                for out_time in read_out_time(_proc):
                    if out_time == -1:
                        break
                    progress.update(task, completed=out_time)

                if progress._tasks[task].completed < duration - 1:
                    total_duration += progress._tasks[task].completed
                    progress.update(task, description=f"{i}/{total_parts}구간 다운로드 중단", refresh=False)
                    break
                else:
                    progress.update(task, completed=duration, total = duration, description=f"{i}/{total_parts}구간 다운로드 완료",refresh=False)
        except Exception as e:
            print()
            console.print(f"{i}/{total_parts} 구간 다운로드 중 오류가 발생하였습니다.", style="red")
            console.print(e, style="red")
            console.print("프로그램을 종료합니다.",style="red")
            typer.Exit(code=1)
            return True

        try:
            _path, _proc = get_concat_process(ffmpeg_path, dir, file, part_list, turbo=turbo)
        except Exception as e:
            console.print(f"영상을 병합하는 중 오류가 발생하였습니다: {e}", style="red")
            console.print("프로그램을 종료합니다.", style="red")
            typer.Exit(code=1)
            return True
        
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
            
        task = progress.add_task("임시 파일 정리 중...", total=len(part_list))
        for part in part_list:
            try:
                os.remove(part)
                progress.update(task, advance=1)
            except OSError as e:
                console.print(f"임시 파일 제거 중 오류가 발생하였습니다. 직접 제거해 주세요.", style="red")
                typer.Exit(code=1)
                return True
        progress.update(task, completed=len(part_list), description="임시 파일 정리 완료", refresh=False)
        progress.stop()
        console.print()
        console.print(f"다운로드가 완료되었습니다: ",style="green",end="")
        console.print(os.path.abspath(_path).replace("\\",'/'))
        console.print()

def login_form(config:dict[str, str]) -> dict[str, str]:
    config["username"] = typer.prompt("아이디")
    config["password"] = typer.prompt("비밀번호")
    
    config["second_password"] = typer.prompt(
        "2차 비밀번호 (없으면 Enter)", default="", show_default=False
    )
    return config

if __name__ == "__main__":
    app(prog_name="")