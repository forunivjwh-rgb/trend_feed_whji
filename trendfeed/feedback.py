""""몰랐는데 흥미로움" 표시 (명세 1번 성공 기준 · 8번 feedback 표).

피드는 고정 페이지라 누른 것을 바로 저장할 곳이 없다. 그래서 카드의 링크가 제목이 채워진 GitHub 이슈
작성 화면을 열고, 매일 실행이 그 이슈를 읽어 기록한 뒤 닫는다.

- repo 주인이 만든 이슈만 읽는다(공개 repo 라 다른 사람이 만든 이슈는 무시한다).
- 이슈 제목 꼴: "[흥미로움] T-0012 2026-11-17" — 주제 번호와 그 피드의 날짜.
- 토큰은 .env 의 GITHUB_TOKEN 에서만 읽는다(Actions 가 실행마다 새로 주는 것). 없으면 건너뛴다.
"""

from __future__ import annotations

import os
import re
from urllib.parse import quote, urlencode

from . import config, db

_TITLE = re.compile(r"(T-\d{4,})\s+(\d{4}-\d{2}-\d{2})")


def repo_name(settings: dict) -> str | None:
    """'소유자/저장소'. 설정에 없으면 Actions 가 알려 주는 값(GITHUB_REPOSITORY)."""
    return settings["feedback"].get("repo") or os.environ.get("GITHUB_REPOSITORY") or None


def new_issue_url(settings: dict, code: str, day: str, name: str) -> str | None:
    repo = repo_name(settings)
    if not repo or not settings["feedback"]["enabled"]:
        return None
    title = f"{settings['feedback']['title_prefix']} {code} {day}"
    body = (f"주제: {name}\n\n이 이슈를 그대로 만들면(Submit) 다음 자동 실행이 "
            f"'몰랐는데 흥미로움'으로 기록하고 이 이슈를 닫습니다.")
    return f"https://github.com/{quote(repo)}/issues/new?" + urlencode({"title": title, "body": body})


def sync(conn, settings: dict, fetch, say=print) -> dict:
    """열린 표시 이슈를 읽어 기록하고 닫는다. {"recorded", "note"}."""
    cfg = settings["feedback"]
    result = {"recorded": 0, "note": ""}
    repo, token = repo_name(settings), config.secret("GITHUB_TOKEN")
    if not cfg["enabled"] or not repo or not token:
        result["note"] = "GitHub 이슈를 읽을 수 없어 건너뜀(Actions 에서만 돈다)"
        return result
    owner = repo.split("/")[0]
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    api = f"https://api.github.com/repos/{repo}"
    try:
        issues = fetch.get_json(f"{api}/issues?" + urlencode({"state": "open", "creator": owner, "per_page": 100}),
                                headers=headers)
    except Exception as e:
        result["note"] = f"표시 이슈를 읽지 못함 ({getattr(e, 'code', None) or type(e).__name__})"
        say(f"  흥미로움 표시: {result['note']}")
        return result
    for issue in issues:
        title = str(issue.get("title", ""))
        if "pull_request" in issue or not title.startswith(cfg["title_prefix"]):
            continue
        if (issue.get("user") or {}).get("login", "").lower() != owner.lower():
            continue  # 주인이 만든 것만
        m = _TITLE.search(title)
        if not m:
            continue
        code, day = m.groups()
        if not conn.execute("SELECT 1 FROM topics WHERE code = ?", (code,)).fetchone():
            continue
        with conn:
            db.save_feedback(conn, code, day, issue=issue["number"])
        try:
            fetch.send_json("PATCH", f"{api}/issues/{issue['number']}", {"state": "closed", "state_reason": "completed"},
                            headers=headers)
        except Exception:
            pass  # 닫기에 실패해도 기록은 남는다. 다음 실행에서 같은 이슈를 다시 읽어도 결과는 같다
        result["recorded"] += 1
    if result["recorded"]:
        say(f"  흥미로움 표시: {result['recorded']}건 기록")
    return result
