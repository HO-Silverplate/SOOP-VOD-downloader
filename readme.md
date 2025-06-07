# SOOP VOD 다운로더

SOOP VOD를 다운로드하는 유틸리티 프로그램입니다.
윈도우 외의 실행 환경에서는 테스트되지 않았습니다.

개발자에게 메일 보내기 : [headonsilverplate@gmail.com](mailto:headonsilverplate@gmail.com)

## Prerequisites

- `Python 3.12`
- `FFmpeg`

## 다운로드

![Github Release](https://img.shields.io/github/v/release/HO-silverplate/SOOP-VOD-downloader?link=https://github.com/HO-Silverplate/SOOP-VOD-downloader/releases/latest)

[여기](https://github.com/HO-Silverplate/SOOP-VOD-downloader/releases/latest)에서 최신 버전 빌드를 다운받을 수 있습니다.

## 사용법

```shell
soop_dl -h
```

자세한 사용법은 `soop_dl -h`를 참고하세요.

## 소스 코드 클론 및 환경 셋업

```shell
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

파이썬 3.12 이상의 버전에서 실행 가능합니다.

## 패키징

실행 파일로 패키징할 수 있습니다.

```shell
pyinstaller soop_dl.py --onefile --disable-windowed-traceback
```

실행 파일은 `/dist` 폴더에 저장됩니다.
