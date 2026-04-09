# SOOP VOD 다운로더

Simple CLI Utility tool for downloading VODs from SOOP - S.Korean Video Streaming platform.
Tested only in `Windows`.

Send a mail to Developer : [headonsilverplate@gmail.com](mailto:headonsilverplate@gmail.com)

#### English / [한국어](readme.md)

## Install

![Github Release](https://img.shields.io/github/v/release/HO-silverplate/SOOP-VOD-downloader?link=https://github.com/HO-Silverplate/SOOP-VOD-downloader/releases/latest)

Download latest build from [here](https://github.com/HO-Silverplate/SOOP-VOD-downloader/releases/latest).

## Localization

Translation files are saved in `assets/lang` as `JSON` format.
Default System Language will be used if translation exists, and can be overriden with `--lang` Option.

Defaults to `en_US`.

```shell
python soop_dl.py --lang en_US
```

## Prerequisite

- `FFmpeg`
> Non-Release builds are NOT recommended.

## Set PATH environmental variable

Adding `soop_dl` to system PATH allows you to run from any command-line terminal without typing full path of executable file. 

Go to `System > About > Advanced system settings`.
You can open the same window by searching `Edit the system environment variable` on Windows Search Bar.

![환경 변수 설정_1](images/setting_path_1.png)
> Image is for reference only.

Click `Environmental Variables`.

![환경 변수 설정_3](images/setting_path_2.png)
> Image is for reference only.

Find `Path` variable in `System variables`and click `Edit` to enter edit window.
Click `New` and add path for the directory of `soop_dl.exe` as shown above.

Run `soop_dl -h` after restarting terminal to check installation.

|         `CMD`          |             `PowerShell`             |
| :--------------------: | :----------------------------------: |
| ![CMD](images/cmd.png) | ![PowerShell](images/PowerShell.png) |


## Run as Executable

```shell
soop_dl -h
```
> help message
```shell
soop_dl -c
```
> Use pre-configured config file
```shell
soop_dl -f '/path/to/ffmpeg.exe'
```
> Override FFmpeg path - defaults to "ffmpeg".
```shell
soop_dl -q 720p
```
> Download as 720p quality
```shell
soop_dl -c -q 720p -f '/path/to/ffmpeg.exe'
```
> Use config file, target quality of 720p, Override FFmpeg path. 
```shell
soop_dl -c -q 720p -f '/path/to/ffmpeg.exe' -k 
```
> Use config file, target quality of 720p, Override FFmpeg path, Do not remove temp files after download. 

---
기타 사용 가능한 옵션 플래그들은 `soop_dl -h`를 참고하세요.
> 빌드된 실행파일을 사용할 시 Python을 설치하지 않아도 실행이 가능합니다.

### Batch Mode

```shell
soop_dl -c -b batch.txt
```
> Use Config file, automatic quality selection, download files from 'batch.txt' first.
> 
`-b` flag enables Batch mode.
Program will read given .txt file and attempt to download from URLs included in said file.

Write Batch manifest as below:

```text
https://vod.sooplive.com/player/********
https://vod.sooplive.com/player/********
https://vod.sooplive.com/player/********
vod.sooplive.com/player/********
https://vod.sooplive.com/player/********
vod.sooplive.com/player/********
...
```

---

## Run from Source Code

> WARNING: Use Executable for general purposes.

### Prerequisite

Python 3.12+

### Clone and Configure Environment

```shell
python --version

git clone https://github.com/HO-Silverplate/SOOP-VOD-downloader.git
cd SOOP-VOD-downloader

python -m venv venv
venv/scripts/activate
pip install -r requirements.txt
```

Activate Python venv to Edit/Run source code.

```shell
python soop_dl.py
```

### Packaging


```shell
pyinstaller soop_dl.spec
```