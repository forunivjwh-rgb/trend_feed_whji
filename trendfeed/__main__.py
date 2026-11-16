"""명령줄 입구.

    python -m trendfeed daily              매일 하는 일 전부(자동 실행이 부르는 명령)
    python -m trendfeed collect            오늘 치를 모아 저장한다
    python -m trendfeed feed --open        피드 페이지를 만들어 브라우저로 연다
    python -m trendfeed status             쌓인 기록과 오늘 모은 것을 보여 준다
    python -m trendfeed install-schedule   매일 자동 실행을 등록한다(윈도우·맥)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import webbrowser
import traceback
from datetime import datetime
from pathlib import Path

from . import archive, config, db, deepread, feed, rank, schedule, topics, topicstore
from .fetch import Fetcher
from .run import STATUS_LABEL, collect_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trendfeed", description="분야별 유행 감지 피드")
    parser.add_argument("--config", type=Path, help="설정 파일 경로 (기본: config/settings.toml)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("daily", help="매일 하는 일 전부(자동 실행이 부르는 명령)")

    p = sub.add_parser("collect", help="오늘 치를 모아 저장한다")
    p.add_argument("--source", help="이 소스만 돌린다 (설정 파일의 [sources.이름])")

    p = sub.add_parser("status", help="쌓인 기록과 오늘 모은 것을 보여 준다")
    p.add_argument("--top", type=int, default=5, help="소스마다 보여 줄 항목 수")

    p = sub.add_parser("rank", help='"지금 인기" 순위를 글자로 본다')
    p.add_argument("--top", type=int, default=10, help="보여 줄 항목 수")
    p.add_argument("--date", help="이 날짜 기준 (기본: 오늘)")

    p = sub.add_parser("topics", help="비슷한 항목을 묶은 주제 후보를 글자로 본다")
    p.add_argument("--top", type=int, default=15, help="보여 줄 주제 수")
    p.add_argument("--date", help="이 날짜 기준 (기본: 가장 최근에 모은 날)")
    p.add_argument("--review", action="store_true", help="LLM으로 이름 붙이기·합치기·떼어 내기까지 한다(키 필요)")
    p.add_argument("--save", action="store_true", help="주제에 번호를 붙여 저장한다")

    p = sub.add_parser("feed", help="피드 페이지를 만든다")
    p.add_argument("--open", action="store_true", dest="open_page", help="만든 뒤 브라우저로 연다")
    p.add_argument("--date", help="이 날짜 기준 (기본: 가장 최근에 모은 날)")

    p = sub.add_parser("import", help="날짜별 기록 파일로 저장 파일을 되살린다 (GitHub Actions 용)")
    p.add_argument("--dir", type=Path, required=True, help="days/ 폴더가 들어 있는 곳")
    p = sub.add_parser("export", help="하루치 기록을 날짜별 파일로 쓴다 (GitHub Actions 용)")
    p.add_argument("--dir", type=Path, required=True, help="days/ 폴더를 둘 곳")
    p.add_argument("--date", help="이 날짜 치 (기본: 오늘)")

    p = sub.add_parser("install-schedule", help="매일 자동 실행을 등록한다(윈도우·맥)")
    p.add_argument("--print", action="store_true", dest="print_only", help="등록하지 않고 내용만 본다")
    p.add_argument("--os", choices=["windows", "mac"], help="--print 와 함께: 어느 쪽 내용을 볼지")
    sub.add_parser("uninstall-schedule", help="매일 자동 실행을 해제한다")

    args = parser.parse_args(argv)
    settings = config.load(args.config)
    # 윈도우에서 한글·특수문자 때문에 출력이 깨지거나 멈추지 않게 한다.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if args.command == "daily":
        return _daily(settings)
    if args.command == "collect":
        return _collect(settings, args.source)
    if args.command == "status":
        return _status(settings, args.top)
    if args.command == "rank":
        return _rank(settings, args.top, args.date)
    if args.command == "topics":
        return _topics(settings, args.top, args.date, args.review, args.save)
    if args.command == "feed":
        return _feed(settings, args.date, args.open_page)
    if args.command == "import":
        conn = db.connect(config.db_path(settings))
        print(f"기록 파일 {archive.import_all(conn, args.dir)}일 치를 읽어 저장 파일을 되살렸습니다.")
        return 0
    if args.command == "export":
        conn = db.connect(config.db_path(settings))
        print(f"기록 파일: {archive.export_day(conn, args.date or config.today(settings), args.dir)}")
        return 0
    if args.command == "install-schedule":
        return _install_schedule(settings, args.print_only, args.os)
    if args.command == "uninstall-schedule":
        try:
            schedule.uninstall()
        except (schedule.Unsupported, subprocess.CalledProcessError) as e:
            print(f"해제하지 못했습니다: {e}")
            return 1
        print("자동 실행을 해제했습니다.")
        return 0
    return 2


def _daily(settings: dict) -> int:
    """매일 하는 일. 화면에도 쓰고 data/logs/daily.log 에도 남긴다.

    자동 실행은 창 없이 돌기 때문에, 무슨 일이 있었는지는 이 파일로 확인한다.
    """
    log_path = config.ROOT / "data" / "logs" / "daily.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def say(text: str) -> None:
        print(text)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(text + "\n")

    say(f"--- {datetime.now().astimezone().isoformat(timespec='seconds')} 시작")
    code = 0
    steps = (
        lambda: _collect(settings, None, say),
        lambda: _deepread(settings, say),  # LLM 키가 없으면 이 단계만 건너뛴다
        lambda: _feed(settings, config.today(settings), False, say),
    )
    for step in steps:
        try:  # 수집이 전부 실패한 날에도 피드는 만든다(막힌 이유가 화면에 보이게)
            code = step() or code
        except Exception:
            say(traceback.format_exc())
            code = 1
    say("--- 끝" if code == 0 else "--- 끝 (문제 있음)")
    return code


def _deepread(settings: dict, say=print) -> int:
    conn = db.connect(config.db_path(settings))
    deepread.run(conn, config.today(settings), settings, Fetcher(settings["http"]), say=say)
    return 0  # 실탐이 안 돼도 수집과 피드는 정상으로 친다


def _collect(settings: dict, only: str | None, say=print) -> int:
    day = config.today(settings)
    conn = db.connect(config.db_path(settings))
    summaries = collect_all(settings, conn, day, only=only)
    say(f"[{day}] 수집")
    for s in summaries:
        say("  " + _run_line(s))
    if not summaries:
        say("  켜져 있는 소스가 없습니다.")
    # 전부 실패했을 때만 실패로 끝낸다.
    return 0 if any(s["status"] != "empty" for s in summaries) else 1


def _run_line(s) -> str:
    line = f"{s['source']:<16} {STATUS_LABEL[s['status']]:<6} {s['item_count']:>3}건"
    if s["followed_count"]:
        line += f" (+다시 확인 {s['followed_count']}건)"
    line += f"  {s['duration_sec']:.1f}초"
    if s["memo"]:
        line += f"  — {s['memo']}"
    return line


def _status(settings: dict, top: int) -> int:
    path = config.db_path(settings)
    if not path.exists():
        print("아직 저장된 것이 없습니다. 먼저 `python -m trendfeed collect` 를 돌려 주세요.")
        return 0
    conn = db.connect(path)
    days = conn.execute("SELECT COUNT(DISTINCT date) FROM source_runs").fetchone()[0]
    n_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    n_snaps = conn.execute("SELECT COUNT(*) FROM item_snapshots").fetchone()[0]
    print(f"저장 파일: {path}")
    print(f"쌓인 날: {days}일 · 항목 {n_items}개 · 숫자 스냅샷 {n_snaps}줄")

    print("\n최근 실행 기록")
    for r in conn.execute(
        "SELECT * FROM source_runs WHERE date IN "
        "(SELECT DISTINCT date FROM source_runs ORDER BY date DESC LIMIT 7) ORDER BY date DESC, source"
    ):
        print(f"  {r['date']}  " + _run_line(r))

    latest = conn.execute("SELECT MAX(date) FROM item_snapshots").fetchone()[0]
    if latest is None:
        return 0
    for (source,) in conn.execute("SELECT DISTINCT source FROM items ORDER BY source").fetchall():
        rows = conn.execute(
            """
            SELECT i.title, i.origin, s.* FROM item_snapshots s JOIN items i ON i.id = s.item_id
            WHERE i.source = ? AND s.date = ? AND s.listed = 1 ORDER BY s.rank LIMIT ?
            """,
            (source, latest, top),
        ).fetchall()
        if not rows:
            continue
        print(f"\n{source} · {latest} · 목록 위에서 {len(rows)}개")
        for r in rows:
            print(f"  {r['rank']:>2}. {r['title'][:70]}")
            print(f"      {_numbers(r)} · 출처 {r['origin']}")
    return 0


def _feed(settings: dict, day: str | None, open_page: bool, say=print) -> int:
    conn = db.connect(config.db_path(settings))
    day = day or conn.execute("SELECT MAX(date) FROM source_runs").fetchone()[0]
    if day is None:
        say("아직 저장된 것이 없습니다. 먼저 `python -m trendfeed collect` 를 돌려 주세요.")
        return 1
    path = feed.write(conn, day, settings)
    say(f"[{day}] 피드 페이지: {path}")
    if open_page:
        webbrowser.open(path.as_uri())
    return 0


def _topics(settings: dict, top: int, day: str | None, review: bool = False, save: bool = False) -> int:
    conn = db.connect(config.db_path(settings))
    day = day or conn.execute("SELECT MAX(date) FROM item_snapshots").fetchone()[0]
    if day is None:
        print("아직 저장된 것이 없습니다.")
        return 0
    entries = rank.now_popular(conn, day, settings)
    try:
        texts = [topics.text_of(e, settings["sources"][e["source"]].get("phrase_ignore_chars", "")) for e in entries]
        vectors = topics.embed(texts, settings["topics"])
    except topics.Unavailable as e:
        print(f"{e} — `pip install fastembed` 뒤에 다시 돌려 주세요.")
        return 1
    found = topics.cluster(entries, vectors, settings)
    if review:
        found, notes, usage = topics.review(found, settings, vectors=vectors)
        if usage:
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            with conn:
                db.save_llm_call(conn, day, created_at=now, purpose="topics", ref=day,
                                 model=settings["llm"]["model"], **usage)
            print(f"LLM 검토 1회 (입력 {usage['input_tokens']:,} · 출력 {usage['output_tokens']:,} 토큰)")
        for line in notes:
            print("  " + line)
    if save:
        before = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
        found = topicstore.save_day(conn, day, found, settings)
        total = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
        print(f"주제 {len(found)}개를 저장했습니다 (새 번호 {max(total - before, 0)}개 · 이어받은 번호 {len(found) - max(total - before, 0)}개 · 전체 {total}개)")
    merged = [t for t in found if len(t["items"]) > 1]
    cross = [t for t in merged if len(t["platforms"]) > 1]
    print(f"[{day}] 항목 {len(entries)}개 → 주제 {len(found)}개 · 2건 이상 묶인 주제 {len(merged)}개 · 여러 플랫폼에 걸친 주제 {len(cross)}개")
    for t in (cross + [t for t in merged if t not in cross])[:top]:
        if t["named_by_llm"] or t.get("code"):
            print(f"\n■ {t.get('code', '')} {t['name']}".replace("■  ", "■ "), end="")
        print(f"\n● 플랫폼 {'·'.join(t['platforms'])} · 출처 {t['origins']}곳 · 항목 {len(t['items'])}건 · 어텐션 합 {t['attention']:.1f}")
        for e in t["items"][:6]:
            print(f"    [{settings['sources'][e['source']]['label']}] {e['title'][:70]}")
        if len(t["items"]) > 6:
            print(f"    … 외 {len(t['items']) - 6}건")
    return 0


def _rank(settings: dict, top: int, day: str | None) -> int:
    conn = db.connect(config.db_path(settings))
    day = day or conn.execute("SELECT MAX(date) FROM item_snapshots").fetchone()[0]
    if day is None:
        print("아직 저장된 것이 없습니다.")
        return 0
    ranked = rank.now_popular(conn, day, settings)
    print(f'[{day}] 지금 인기 · 기준선 {rank.baseline_days(conn, day)}일째 · 순위에 든 항목 {len(ranked)}개')
    for source in sorted({e["source"] for e in ranked}):
        e = next(x for x in ranked if x["source"] == source)
        print(f'  {settings["sources"][source]["label"]}: 가운데 항목은 하루 +{e["typical"]:,.0f}{e["unit"]}')
    print()
    for e in ranked[:top]:
        print(f'{e["place"]:>2}. 보통의 {e["times_typical"]:.1f}배  [{settings["sources"][e["source"]]["label"]}] {e["title"][:60]}')
        print(" · ".join(filter(None, [f'      하루 +{e["velocity"]:,.0f}{e["unit"]} ({e["basis"]})', _numbers(e)])))
    return 0


_METRIC_LABEL = {"views": "조회", "stars": "별", "score": "점수", "comments": "댓글", "likes": "좋아요"}
_EXTRA_LABEL = {"forks": "포크", "stars_daily": "오늘 +별", "stars_weekly": "이번 주 +별", "downloads": "다운로드"}


def _numbers(row) -> str:
    parts = [f"{label} {row[key]:,}" for key, label in _METRIC_LABEL.items() if row[key] is not None]
    extra = row["extra"] if isinstance(row["extra"], dict) else json.loads(row["extra"])
    parts += [f"{label} {extra[key]:,}" for key, label in _EXTRA_LABEL.items() if key in extra]
    return " · ".join(parts)


def _install_schedule(settings: dict, print_only: bool, target: str | None) -> int:
    try:
        if print_only:
            print(schedule.preview(settings, target))
            return 0
        where = schedule.install(settings)
    except (schedule.Unsupported, subprocess.CalledProcessError) as e:
        print(f"등록하지 못했습니다: {e}")
        return 1
    s = settings["schedule"]
    print(f"매일 {s['hour']:02d}:{s['minute']:02d}에 자동으로 돌립니다.")
    if sys.platform == "win32" and s["windows"]["run_missed_asap"]:
        print("그 시각에 컴퓨터가 꺼져 있었으면, 켠 뒤 가능한 한 빨리 돌립니다.")
    print(f"등록한 곳: {where}")
    print("실행 기록: data/logs/daily.log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
