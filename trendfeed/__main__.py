"""명령줄 입구.

    python -m trendfeed collect            오늘 치를 모아 저장한다
    python -m trendfeed status             쌓인 기록과 오늘 모은 것을 보여 준다
    python -m trendfeed install-schedule   매일 자동 실행을 등록한다(맥)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config, db, schedule
from .run import STATUS_LABEL, collect_all
from .sources import registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trendfeed", description="분야별 유행 감지 피드")
    parser.add_argument("--config", type=Path, help="설정 파일 경로 (기본: config/settings.toml)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("collect", help="오늘 치를 모아 저장한다")
    p.add_argument("--source", choices=sorted(registry()), help="이 소스만 돌린다")

    p = sub.add_parser("status", help="쌓인 기록과 오늘 모은 것을 보여 준다")
    p.add_argument("--top", type=int, default=5, help="소스마다 보여 줄 항목 수")

    p = sub.add_parser("install-schedule", help="매일 자동 실행을 등록한다(맥)")
    p.add_argument("--print", action="store_true", dest="print_only", help="등록하지 않고 내용만 본다")
    sub.add_parser("uninstall-schedule", help="매일 자동 실행을 해제한다(맥)")

    args = parser.parse_args(argv)
    settings = config.load(args.config)

    if args.command == "collect":
        return _collect(settings, args.source)
    if args.command == "status":
        return _status(settings, args.top)
    if args.command == "install-schedule":
        return _install_schedule(settings, args.print_only)
    if args.command == "uninstall-schedule":
        try:
            schedule.uninstall()
        except RuntimeError as e:
            print(e)
            return 1
        print("자동 실행을 해제했습니다.")
        return 0
    return 2


def _collect(settings: dict, only: str | None) -> int:
    day = config.today(settings)
    conn = db.connect(config.db_path(settings))
    summaries = collect_all(settings, conn, day, only=only)
    print(f"[{day}] 수집")
    for s in summaries:
        print("  " + _run_line(s))
    if not summaries:
        print("  켜져 있는 소스가 없습니다.")
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


_METRIC_LABEL = {"views": "조회", "stars": "별", "score": "점수", "comments": "댓글", "likes": "좋아요"}
_EXTRA_LABEL = {"forks": "포크", "stars_daily": "오늘 +별", "stars_weekly": "이번 주 +별"}


def _numbers(row) -> str:
    parts = [f"{label} {row[key]:,}" for key, label in _METRIC_LABEL.items() if row[key] is not None]
    extra = json.loads(row["extra"])
    parts += [f"{label} {extra[key]:,}" for key, label in _EXTRA_LABEL.items() if key in extra]
    return " · ".join(parts)


def _install_schedule(settings: dict, print_only: bool) -> int:
    if print_only:
        print(schedule.build_plist(settings).decode())
        return 0
    try:
        path = schedule.install(settings)
    except RuntimeError as e:
        print(e)
        return 1
    s = settings["schedule"]
    print(f"매일 {s['hour']:02d}:{s['minute']:02d}에 자동으로 수집합니다.")
    print(f"예약 파일: {path}")
    print("실행 기록(로그): data/logs/daily.log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
