# SOOP VOD 다운로더

SOOP VOD를 다운로드하는 유틸리티 프로그램입니다.
윈도우 외의 실행 환경에서는 테스트되지 않았습니다.

## Prerequisites

- `Python 3.12`
- `FFmpeg`

## 다운로드

![Github Release](https://img.shields.io/github/v/release/HO-silverplate/SOOP-VOD-downloader?link=https://github.com/HO-Silverplate/SOOP-VOD-downloader/releases/latest)

[여기](https://github.com/HO-Silverplate/SOOP-VOD-downloader/releases/latest)에서 최신 버전 빌드를 다운받을 수 있습니다.

## 소스 코드 설치 및 셋업

```shell
git clone https://github.com/HO-Silverplate/SOOP-VOD-downloader.git
cd SOOP-VOD-downloader

# Python Venv setup
python -m venv venv
venv/scripts/activate
pip install -r requirements.txt
```

## 사용

### Python (powershell)

```shell
#도움말
python soop_dl.py -h
```

### Executable (CMD)

```shell
#도움말
soop_dl -h
```

## 패키징

실행 파일로 패키징할 수 있습니다.

```shell
pyinstaller soop_dl.py --onefile --disable-windowed-traceback
```

실행 파일은 `/dist` 폴더에 저장됩니다.
