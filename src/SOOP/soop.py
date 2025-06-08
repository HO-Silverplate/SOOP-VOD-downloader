import requests
from model import Types, Manifest

VOD_API = "https://api.m.sooplive.co.kr/station/video/a/view"
LOGIN_API = "https://login.sooplive.co.kr/app/LoginAction.php"
LOGOUT_API = "https://login.sooplive.co.kr/app/LogOut.php"
CHECK_API = "https://afevent2.sooplive.co.kr/api/get_private_info.php"

QUALITY_MAPPING = {
    "1440p": 5,
    "1080p": 4,
    "720p": 3,
    "540p": 2,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://play.sooplive.co.kr/",
    "Origin": "https://play.sooplive.co.kr",
}

# Login Status
LOGGED_IN = 1
LOGGED_OUT = -1


class LoginError(Exception): ...


class SOOP:
    __session: requests.Session | None = None

    @classmethod
    def session(cls) -> requests.Session:
        if cls.__session is None:
            cls.__session = requests.Session()
            cls.__session.headers.update(HEADERS)
        return cls.__session

    @classmethod
    def check_auth(cls) -> bool:
        """
        세션이 SOOP에 로그인되어 있는지 확인합니다.
        """
        try:
            res = cls.session().get(CHECK_API, timeout=4)
            res.raise_for_status()
            return res.json()["CHANNEL"]["IS_LOGIN"] == LOGGED_IN
        except:
            return False

    @classmethod
    def login(
        cls,
        username: str | None = "",
        password: str | None = "",
        sec_password: str | None = "",
    ) -> bool:
        """
        SOOP에 로그인하고 결과를 반환합니다.
        로그인에 성공하면 True를 반환하고, 실패하면 LoginError 예외를 발생시킵니다.

        :param session: requests.Session 객체
        :param username: SOOP 아이디
        :param password: SOOP 비밀번호
        :param sec_password: SOOP 2차 비밀번호 (선택 사항)

        :return: 로그인 성공 여부 (True/False)
        :raises LoginError: 로그인 실패 시 예외를 발생시킵니다.

        """
        session = cls.session()
        if cls.check_auth():
            return True

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
                "isLoginRetain": "N",
            },
        )
        try:
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            msg = f"서버에 연결할 수 없습니다 - {e}"

        match response.json().get("RESULT", 1024):
            case 1:
                return cls.check_auth()
            case -1:
                msg = "등록되지 않은 아이디이거나, 아이디 또는 비밀번호를 잘못 입력하셨습니다."
            case -3:
                msg = "아이디가 비활성화되었습니다."
            case -10:
                msg = "아이디의 비정상적인 로그인(대량 접속 등)이 확인되어 접속이 차단되었습니다."
            case -11:
                return cls.sec_login(username, sec_password)
            case _:
                msg = "SOOP에 로그인할 수 없습니다."
        raise LoginError(msg)

    @classmethod
    def sec_login(cls, username: str, sec_password: str) -> bool:
        """
        2차 인증을 수행합니다.
        """
        session = cls.session()
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
                    "isLoginRetain": "N",
                },
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            msg = f"서버에 연결할 수 없습니다 - {e}"

        if response.status_code == 200 and response.json().get("RESULT", 0) == 1:
            return True
        else:
            msg = "2차 인증에 실패했습니다."

        raise LoginError(msg)

    @classmethod
    def logout(cls):
        """
        SOOP에서 로그아웃합니다.
        """
        session = cls.session()
        try:
            response = session.get(LOGOUT_API, timeout=3)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise LoginError(f"SOOP에서 로그아웃할 수 없습니다 : {e}")

    @classmethod
    def get_manifest(cls, url: str, quality: str | None = None) -> Manifest:
        """
        VOD 정보를 요청하고, 원하는 품질의 URL 매니페스트를 반환합니다.\n
        매니페스트가 비었거나 파싱에 실패하면 KeyError를 발생시킵니다.\n
        유효하지 않은 URL이라면 ValueError를 발생시킵니다.

        :param url: VOD의 player_url
        :param quality: 원하는 비디오 품질 (예: "1080p", "auto")
        :return: Manifest 객체, VOD 제목과 URL 리스트가 포함됨
        :raises KeyError: VOD 정보가 비어있거나 데이터 파싱에 실패함
        :raises ValueError: 유효하지 않은 URL
        :raises requests.exceptions.RequestException: 요청 실패
        """

        url = Types.player_url(url)
        manifest = Manifest()
        session = cls.session()

        res = session.post(
            VOD_API,
            data={
                "nTitleNo": url.title_no,
                "nApiLevel": "10",
                "nPlaylistidx": "0",
            },
        )
        res.raise_for_status()
        data: dict = res.json().get("data", None)

        if (quality == "auto" or quality is None or quality == "자동") or (
            quality not in QUALITY_MAPPING
        ):
            desired_quality = f'{str(data["file_resolution"]).split("x")[-1]}p'
        elif quality in QUALITY_MAPPING:
            desired_quality = quality

        objlist = data["files"]
        for file_dict in objlist:
            for fileset in file_dict["quality_info"]:
                if str(fileset["resolution"]).split("x")[-1] == desired_quality[:-1]:
                    manifest.add_vod(fileset["file"], file_dict["duration"])

        manifest.set_title(data["title"])

        if manifest.count() == 0:
            raise KeyError("Manifest Empty.")

        return manifest
