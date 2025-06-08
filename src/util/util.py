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
        if line.startswith("out_time_ms"):
            out_time = int(line.split("=")[1]) // 1000
            yield out_time
        elif line.startswith("progress") and "end" in line:
            yield -1
            break
