"""피드 페이지(HTML 파일 하나)를 쓴다 — "지금 인기" 모드 (명세 5번 '처음 2~4주', 7번).

기준선이 쌓이기 전이라 '평소 대비' 점수(z·가속)와 롤업은 없고, 오늘 어텐션 순으로만 보여 준다.
주제 묶기·실탐·LLM 요약이 붙기 전이라 카드 하나는 항목 하나다.
모양은 docs/sample 의 샘플 피드를 따른다. 숫자는 전부 rank.py 가 계산한 것이다.
"""

from __future__ import annotations

import random
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, rank
from .run import STATUS_LABEL

CSS = """
:root{color-scheme:light;--plane:#f9f9f7;--surface-1:#fcfcfb;--text-primary:#0b0b0b;--text-secondary:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--chip-bg:#f0efec;--band:rgba(42,120,214,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--good:#0ca30c;--warn:#fab219}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--plane:#0d0d0d;--surface-1:#1a1a19;--text-primary:#f0efec;--text-secondary:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--chip-bg:#2c2c2a;--band:rgba(57,135,229,.18);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#0ca30c}}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",sans-serif;font-size:14px;line-height:1.5;background:var(--plane);color:var(--text-primary);-webkit-text-size-adjust:100%}
h1,h2,h3,p{margin:0}
a{color:inherit;text-decoration:none}
a:hover{text-decoration:underline}
.page{max-width:1120px;margin:0 auto;padding:24px 16px 72px;display:flex;flex-direction:column;gap:36px}
header,section{display:flex;flex-direction:column;gap:14px}
h1{font-size:28px;line-height:1.2}
h2{font-size:22px;line-height:1.3}
h3{font-size:20px;line-height:1.35;overflow-wrap:anywhere}
.sub{font-size:13px;line-height:1.55;color:var(--text-secondary)}
.small{font-size:12px;color:var(--text-secondary)}
.row{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px}
.chip{display:inline-flex;align-items:center;gap:6px;padding:2px 10px;border-radius:999px;background:var(--chip-bg);font-size:12px;line-height:1.7;white-space:nowrap}
.chip.line{border:1px solid var(--axis)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;flex:0 0 auto;background:var(--muted)}
.dot[data-p="HN"]{background:var(--s1)}
.dot[data-p="GH"]{background:var(--s2)}
.dot[data-p="YT"]{background:var(--s3)}
.dot[data-p="HF"]{background:var(--s4)}
.dot[data-p="GN"]{background:var(--s5)}
.dot[data-p="WK"]{background:var(--s6)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(200px,100%),1fr));gap:8px}
.tile{display:flex;flex-direction:column;gap:2px;padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:var(--surface-1);min-width:0}
.tile b{font-size:14px}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:14px;min-width:0}
.cards{display:flex;flex-direction:column;gap:16px}
.cardhead{display:flex;flex-wrap:wrap;gap:12px 16px;align-items:flex-start;justify-content:space-between}
.cardhead>div:first-child{display:flex;flex-direction:column;gap:8px;min-width:0;flex:1 1 320px}
.score{display:flex;flex-direction:column;align-items:flex-end;gap:2px}
.score b{font-size:32px;line-height:1.1}
.nums{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(128px,100%),1fr));gap:8px}
.num{display:flex;flex-direction:column;gap:2px;padding:8px 10px;border-radius:8px;background:var(--chip-bg);min-width:0}
.num b{font-size:18px;line-height:1.3}
.bar{height:8px;border-radius:4px;background:var(--chip-bg);overflow:hidden}
.bar>i{display:block;height:100%;background:var(--s1);border-radius:4px}
.notice{background:var(--band);border-radius:12px;padding:14px 16px;display:flex;flex-direction:column;gap:10px}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr));gap:16px}
.list{gap:0;padding-top:4px;padding-bottom:4px}
.item{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:6px 12px;padding:10px 0;border-bottom:1px solid var(--grid)}
.item:last-child{border-bottom:0}
.item>div:first-child{display:flex;flex-direction:column;gap:3px;min-width:0;flex:1 1 260px}
.item .t{font-weight:600;overflow-wrap:anywhere}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;min-width:640px;font-size:13px}
th{text-align:left;font-size:12px;color:var(--text-secondary);font-weight:600;padding:6px 12px 6px 0;border-bottom:1px solid var(--grid)}
td{padding:10px 12px 10px 0;border-bottom:1px solid var(--grid);vertical-align:top}
.st{display:inline-flex;align-items:center;gap:6px;font-weight:600}
.st i{width:8px;height:8px;border-radius:50%;background:var(--good)}
.st.warn i{background:var(--warn)}
.st.empty i{background:transparent;border:1.5px solid var(--text-secondary)}
"""

# 막대 그래프 모양의 작은 그림: 샘플에서 "지금 인기" 표시에 쓰는 것
ICON_NOW = (
    '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">'
    '<path d="M3 9.5V6M6 9.5V3M9 9.5V5" style="fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round"/></svg>'
)

_METRIC_LABEL = {"score": "점수", "stars": "전체 별", "comments": "댓글", "views": "조회", "likes": "좋아요"}


_EXTRA_LABEL = {"forks": "포크", "downloads": "다운로드(최근 한 달)"}


def _n(x: float) -> str:
    return f"{x:,.0f}"


def _link(e: dict) -> str:
    """제목을 링크로. http(s) 주소가 아니면 링크를 걸지 않는다."""
    title = escape(e["title"])
    if e["url"].startswith(("https://", "http://")):
        return f'<a href="{escape(e["url"], quote=True)}" target="_blank" rel="noopener noreferrer">{title}</a>'
    return title


def _source_tag(e: dict, sources: dict) -> str:
    src = sources[e["source"]]
    return f'<span class="row small" style="gap:6px"><span class="dot" data-p="{escape(src["code"])}"></span>{escape(src["label"])}</span>'


def _numbers_line(e: dict) -> str:
    parts = [f"하루 +{_n(e['velocity'])}{e['unit']}"]
    parts += [f"{label} {_n(e[key])}" for key, label in _METRIC_LABEL.items() if e.get(key) is not None]
    return " · ".join(parts)


def _card(e: dict, sources: dict) -> str:
    src = sources[e["source"]]
    nums = [("하루 증가량", f"+{_n(e['velocity'])}{e['unit']}"), ("이 소스의 보통 항목", f"+{_n(e['typical'])}{e['unit']}")]
    nums += [(label, _n(e[key])) for key, label in _METRIC_LABEL.items() if e.get(key) is not None]
    nums += [(label, _n(e["extra"][key])) for key, label in _EXTRA_LABEL.items() if key in e["extra"]]
    tiles = "".join(f'<div class="num"><span class="small">{escape(l)}</span><b>{escape(v)}</b></div>' for l, v in nums)
    desc = e["item_extra"].get("description")
    desc_html = f'<p class="sub" style="color:var(--text-primary)">{escape(desc)}</p>' if desc else ""
    discuss = e["item_extra"].get("discuss_url")
    discuss_html = (
        f' · <a href="{escape(discuss, quote=True)}" target="_blank" rel="noopener noreferrer">댓글 보기</a>'
        if discuss and discuss != e["url"]
        else ""
    )
    return f"""
<article class="card">
  <div class="cardhead">
    <div>
      <div class="row">
        <b>#{e['place']}</b>
        <span class="chip line">{ICON_NOW} 지금 인기</span>
        {_source_tag(e, sources)}
        <span class="small">{escape(src['field'])}</span>
      </div>
      <h3>{_link(e)}</h3>
      {desc_html}
      <div class="small">출처 {escape(e['item_extra'].get('channel_title') or e['origin'] or '알 수 없음')} · 처음 본 날 {escape(e['first_seen'])}{discuss_html}</div>
    </div>
    <div class="score"><span class="small">오늘 어텐션 · 보통의</span><b>{e['times_typical']:.1f}배</b></div>
  </div>
  <div>
    <div class="small" style="font-weight:600;margin-bottom:8px">왜 올랐나 (수치) — {escape(e['basis'])}</div>
    <div class="nums">{tiles}</div>
  </div>
</article>"""


def _row(e: dict, sources: dict, show_source: bool = True) -> str:
    head = _source_tag(e, sources) if show_source else f'<span class="small">#{e["place"]} (전체 순위)</span>'
    return f"""
<div class="item">
  <div>{head}<div class="t">{_link(e)}</div></div>
  <div class="row"><span style="font-size:13px">{escape(_numbers_line(e))}</span><span class="chip">보통의 {e['times_typical']:.1f}배</span></div>
</div>"""


def build(conn, day: str, settings: dict) -> str:
    cfg, sources = settings["feed"], settings["sources"]
    tz = ZoneInfo(settings["general"]["timezone"])
    ranked = rank.now_popular(conn, day, settings)
    days = rank.baseline_days(conn, day)
    need = cfg["baseline_days"]
    runs = [dict(r) for r in conn.execute("SELECT * FROM source_runs WHERE date = ? ORDER BY source", (day,))]

    top = ranked[: cfg["top_n"]]
    shown = {e["item_id"] for e in top}

    # 분야 → 소스 → 위에서 몇 개
    fields: dict[str, list[str]] = {}
    for name, src in sources.items():
        if src.get("enabled"):
            fields.setdefault(src["field"], []).append(name)
    field_html = []
    for field, names in fields.items():
        cols = []
        for name in names:
            picks = [e for e in ranked if e["source"] == name][: cfg["per_source_n"]]
            shown.update(e["item_id"] for e in picks)
            body = "".join(_row(e, sources, show_source=False) for e in picks) or '<p class="sub" style="padding:10px 0">오늘 모은 것이 없어요.</p>'
            cols.append(
                f'<div class="card list"><div class="row small" style="padding:10px 0 4px;font-weight:600">'
                f'<span class="dot" data-p="{escape(sources[name]["code"])}"></span>{escape(sources[name]["label"])}</div>{body}</div>'
            )
        field_html.append(f'<h3 style="font-size:17px">{escape(field)}</h3><div class="cols">{"".join(cols)}</div>')

    # 탐색 슬롯: 위에 나오지 않은 항목 중 무작위. 같은 날 다시 만들어도 같은 것이 뽑힌다.
    rest = [e for e in ranked if e["item_id"] not in shown]
    explore = random.Random(day).sample(rest, min(cfg["explore_n"], len(rest)))

    ok = sum(r["item_count"] > 0 for r in runs)
    total_items = sum(r["item_count"] for r in runs)
    started = min((r["started_at"] for r in runs), default=None)
    run_line = "오늘 실행 기록이 없어요."
    if started:
        local = datetime.fromisoformat(started).astimezone(tz)
        run_line = f"{local:%H:%M} 시작 · 수집 {sum(r['duration_sec'] for r in runs):.0f}초 · {day}"

    stats = [
        ("수집", f"{total_items}건 · 소스 {len(runs)}곳 중 {ok}곳 수집됨"),
        ("순위에 든 항목", f"{len(ranked)}개 (주제로 묶기 전)"),
        ("기준선", f"{min(days, need)}/{need}일"),
        ("실탐 · 요약", "아직 없음 (나중 단계)"),
    ]
    stats_html = "".join(f'<div class="tile"><span class="small">{escape(l)}</span><b>{escape(v)}</b></div>' for l, v in stats)

    status_rows = []
    for r in runs:
        src = sources.get(r["source"], {})
        note = r["memo"] or ("목록 밖 " + str(r["followed_count"]) + "건은 숫자만 다시 적음" if r["followed_count"] else "")
        status_rows.append(
            f'<tr><td><span class="row" style="gap:8px;font-weight:600"><span class="dot" data-p="{escape(src.get("code", ""))}"></span>'
            f'{escape(src.get("label", r["source"]))}</span></td><td>{escape(src.get("field", ""))}</td>'
            f'<td>{r["item_count"]}건</td><td>{src.get("weight", "")}</td>'
            f'<td><span class="st {escape(r["status"])}"><i></i>{STATUS_LABEL[r["status"]]}</span></td><td>{escape(note)}</td></tr>'
        )

    pct = round(100 * min(days, need) / need)
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>오늘의 유행 피드 · {escape(day)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="page">
  <header>
    <div class="row">
      <h1>오늘의 유행 피드</h1>
      <span class="small">가동 {days}일차</span>
    </div>
    <p class="sub">{escape(run_line)}</p>
    <div class="tiles">{stats_html}</div>
    <div class="notice">
      <p><b>기준선이 쌓이는 중이에요 ({min(days, need)}/{need}일).</b> 지금은 "평소 대비" 없이 오늘 어텐션 순으로만 보여 줘요.
      {need}일이 차면 평소 대비 점수(z)와 가속이 켜지고 롤업(일·주·월 요약)이 나타나요.</p>
      <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="{need}" aria-valuenow="{min(days, need)}"><i style="width:{pct}%"></i></div>
    </div>
  </header>

  <section>
    <div><h2>지금 인기 Top {cfg['top_n']}</h2>
    <p class="sub">오늘 어텐션이 높은 순서예요. 어텐션 = 하루 증가량이 그 소스의 보통(가운데) 항목의 몇 배인가.
    탐색에서 올라오는 1건은 고르는 규칙을 정한 뒤에 붙어요.</p></div>
    <div class="cards">{"".join(_card(e, sources) for e in top) or '<p class="sub">오늘 순위에 올릴 항목이 없어요.</p>'}</div>
  </section>

  <section>
    <div><h2>분야별 Top {cfg['per_source_n']}</h2>
    <p class="sub">분야 안에서 소스마다 {cfg['per_source_n']}개씩이에요. 전부 수치만 본 것("메타만")이고, 원문을 읽은 요약은 아직 없어요.</p></div>
    {"".join(field_html)}
  </section>

  <section>
    <div><h2>탐색 슬롯</h2>
    <p class="sub">위에 나오지 않은 항목 중에서 순위와 상관없이 무작위로 뽑은 {len(explore)}건이에요.</p></div>
    <div class="card list">{"".join(_row(e, sources) for e in explore) or '<p class="sub" style="padding:10px 0">뽑을 항목이 없어요.</p>'}</div>
  </section>

  <section>
    <div><h2>수집 상태와 오늘의 실행</h2>
    <p class="sub">소스마다 오늘 몇 건을 가져왔는지, 막힌 곳은 없는지 보여 줘요.</p></div>
    <div class="card"><div class="scroll"><table>
      <tr><th>소스</th><th>분야</th><th>수집</th><th>가중치</th><th>상태</th><th>비고</th></tr>
      {"".join(status_rows) or '<tr><td colspan="6">오늘 실행 기록이 없어요.</td></tr>'}
    </table></div></div>
  </section>
</div>
</body>
</html>
"""


def write(conn, day: str, settings: dict) -> Path:
    path = Path(settings["feed"]["path"])
    path = path if path.is_absolute() else config.ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(conn, day, settings), encoding="utf-8")
    return path
