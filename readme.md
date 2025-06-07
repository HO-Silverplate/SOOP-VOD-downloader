# SOOP VOD 다운로더

SOOP VOD를 다운로드하는 유틸리티 프로그램입니다.
윈도우 외의 실행 환경에서는 테스트되지 않았습니다.

개발자에게 메일 보내기 : [headonsilverplate@gmail.com](mailto:headonsilverplate@gmail.com)

## 다운로드

![Github Release](https://img.shields.io/github/v/release/HO-silverplate/SOOP-VOD-downloader?link=https://github.com/HO-Silverplate/SOOP-VOD-downloader/releases/latest)

[여기](https://github.com/HO-Silverplate/SOOP-VOD-downloader/releases/latest)에서 최신 버전 빌드를 다운받을 수 있습니다.

## Prerequisites

- `FFmpeg`

## 실행파일로 사용하기

```shell
soop_dl -h

soop_dl -c
# 설정 파일 사용하기

soop_dl -f '/path/to/ffmpeg.exe'
# ffmpeg 경로 지정하기

soop_dl -q 720p
# 720p 화질로 저장하기

soop_dl -c -q 720p -f '/path/to/ffmpeg.exe'
# 설정 파일 사용, 목표해상도 720p, FFmpeg 경로 갱신하기 

```

CMD 또는 PowerShell에서 실행하세요.

## 소스코드로 사용하기

### 소스 코드 클론 및 환경 셋업

```shell
python --version
# python 3.13.4

git clone https://github.com/HO-Silverplate/SOOP-VOD-downloader.git
cd SOOP-VOD-downloader

python -m venv venv
venv/scripts/activate
pip install -r requirements.txt
```

코드 수정, 빌드, 실행을 위해 필요합니다.

```shell
python soop_dl.py
```

소스코드 실행은 파이썬 3.12 이상의 버전을 요구합니다.

### 패키징

실행 파일로 패키징하여 사용할 수 있습니다.

```shell
pyinstaller soop_dl.py --onefile --disable-windowed-traceback
```

실행 파일은 `/dist` 폴더에 저장됩니다.
