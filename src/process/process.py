import os
import subprocess
import sys
import tempfile
import requests


def download_process(
    ffmpeg_path: str,
    url: str,
    path: str,
    session: requests.Session | None = None,
    turbo: bool = False,
) -> subprocess.Popen:
    """
    다운로드 프로세스를 생성하여 반환합니다.
    """
    headers = {}
    if session is None:
        session = requests.Session()
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
        "error",
        # "-stats",
        "-progress",
        "pipe:1",
    ]

    if turbo:
        ffmpeg_cmd.append("-threads")
        ffmpeg_cmd.append("0")

    ffmpeg_cmd.append(path)

    return subprocess.Popen(
        ffmpeg_cmd,
        stdin=sys.stdin,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
    )


def concat_process(
    ffmpeg_path: str,
    export_path: str,
    part_list: list[str],
    turbo: bool = False,
) -> subprocess.Popen:
    """
    병합 프로세스를 생성하고 반환합니다.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".txt", encoding="utf-8"
    ) as tmp:
        for part in part_list:
            tmp.write(f"file '{part}'\n")
        tmp_path = tmp.name

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
        "error",
        # "-stats",
        "-progress",
        "pipe:1",
        export_path,
    ]

    if turbo:
        concat_cmd.append("-threads")
        concat_cmd.append("0")

    return subprocess.Popen(
        concat_cmd,
        stdin=sys.stdin,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        # stderr=subprocess.STDOUT,
        text=True,
    )
