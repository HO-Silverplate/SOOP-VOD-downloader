import os
import re
import subprocess
from typing import Generator


def get_unique_filename(file_path: str) -> str:
    """
    중복되는 파일명을 회피하고 파일명으로 사용할 수 없는 특수문자를 제거합니다.
    """
    # 파일 경로를 디렉토리, 파일명, 확장자로 분리
    directory, filename = os.path.split(file_path)
    name, ext = os.path.splitext(filename)

    name = delete_spec_char(name)

    counter = 1
    unique_path = file_path
    while os.path.exists(unique_path):
        unique_path = os.path.join(directory, f"{name}({counter}){ext}")
        counter += 1

    return unique_path


def delete_spec_char(string: str):
    return re.sub(r'[\/:*?"<>|]', "", string)


def read_out_time(proc: subprocess.Popen) -> Generator[int, None, None]:
    """
    FFmpeg 프로세스의 stdout에서 out_time_ms 값을 읽어 밀리초 단위로 반환합니다.
    """
    while True:
        line: str = proc.stdout.readline()
        line = line.strip()
        if not line:
            yield -1
            break
        if "error" in line.lower():
            yield -1
            break
        if line.startswith("out_time_ms"):
            out_time = int(line.split("=")[1]) // 1000
            yield out_time
        elif line.startswith("progress") and "end" in line:
            yield -1
            break


def get_duration_ms(input_path, ffprobe_path="ffprobe") -> int:
    try:
        result = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                input_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        seconds = float(result.stdout.strip())
    except:
        return None
    return int(seconds * 1000)


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
