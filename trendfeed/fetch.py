"""웹에서 글자를 받아 오는 얇은 도구. 실패하면 설정한 횟수만큼만 다시 시도한다."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

# 다시 시도해 볼 만한 응답: 서버가 바쁘거나 잠깐 고장 난 경우뿐이다.
# 403 같은 거절은 다시 두드리지 않고 그대로 실패로 남긴다.
_RETRY_STATUS = {429, 500, 502, 503, 504}


class Fetcher:
    def __init__(self, http_cfg: dict):
        self.timeout = http_cfg["timeout_sec"]
        self.retries = http_cfg["retries"]
        self.backoff = http_cfg["backoff_sec"]
        self.user_agent = http_cfg["user_agent"]

    def get_text(self, url: str, headers: dict | None = None) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, **(headers or {})})
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                if e.code not in _RETRY_STATUS or attempt == self.retries:
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == self.retries:
                    raise
            time.sleep(self.backoff * (2**attempt))
        raise AssertionError("unreachable")

    def get_json(self, url: str, headers: dict | None = None):
        return json.loads(self.get_text(url, headers))
