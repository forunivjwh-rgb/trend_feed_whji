"""피드 페이지(HTML 파일 하나)를 쓴다 (명세 7번). 카드 하나가 주제 하나다.

기준선이 14일 쌓이기 전에는 "지금 인기" 모드다: 오늘 어텐션 순으로 보여 주고, 평소 대비 점수와 롤업은 숨긴다.
14일이 차면 점수(z·가속·폭) 순이 되고 "임계 통과" 표시가 붙는다. 롤업(일·주·월 요약)은 아직 없다.
모양은 docs/sample 의 샘플 피드를 따른다. 숫자는 전부 코드(rank.py, score.py)가 계산한 것이다.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, db, feedback, llm, rank, rollup, score, topics
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
.read{display:flex;flex-direction:column;gap:6px;padding:12px 14px;border-radius:8px;background:var(--band)}
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
.curve{display:block;width:100%;height:56px}
.curve path{fill:none;stroke:var(--s1);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.curve circle{fill:var(--s1)}
.ev{display:flex;flex-direction:column;gap:2px;padding:8px 0;border-top:1px solid var(--grid)}
.ev:first-child{border-top:0}
.why{font-size:14px;line-height:1.6}
.chip.ex{border:1px dashed var(--axis)}
.meta{font-size:12px;color:var(--text-secondary)}
.multi{display:block;width:100%;height:140px}
.multi path{fill:none;stroke-width:2;stroke-linejoin:round}
.key{display:inline-block;width:14px;height:2px;border-radius:1px;background:var(--muted)}
.key[data-p="HN"],.multi .key-HN{background:var(--s1);stroke:var(--s1)}
.key[data-p="GH"],.multi .key-GH{background:var(--s2);stroke:var(--s2)}
.key[data-p="YT"],.multi .key-YT{background:var(--s3);stroke:var(--s3)}
.key[data-p="HF"],.multi .key-HF{background:var(--s4);stroke:var(--s4)}
.key[data-p="GN"],.multi .key-GN{background:var(--s5);stroke:var(--s5)}
.key[data-p="WK"],.multi .key-WK{background:var(--s6);stroke:var(--s6)}
ul{margin:6px 0 0;padding-left:18px}
details summary{cursor:pointer;margin-top:8px}
"""

# 작은 그림들: 샘플에서 쓰는 표시
ICON_NOW = ('<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">'
            '<path d="M3 9.5V6M6 9.5V3M9 9.5V5" style="fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round"/></svg>')
ICON_EX = ('<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4.2" '
           'style="fill:none;stroke:currentColor;stroke-width:1.4"/><circle cx="6" cy="6" r="1.2" style="fill:currentColor"/></svg>')
ICON_UP = ('<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">'
           '<path d="M3 9L9 3M4.5 3H9v4.5" style="fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round"/></svg>')

_METRIC_LABEL = {"score": "점수", "stars": "별", "comments": "댓글", "views": "조회", "likes": "좋아요"}


def _n(x: float) -> str:
    return f"{x:,.0f}"


def _link(e: dict) -> str:
    """제목을 링크로. http(s) 주소가 아니면 링크를 걸지 않는다."""
    title = escape(e["title"])
    if e["url"].startswith(("https://", "http://")):
        return f'<a href="{escape(e["url"], quote=True)}" target="_blank" rel="noopener noreferrer">{title}</a>'
    return title


def _platform_labels(sources: dict) -> dict:
    """플랫폼 기호 → 이름. 위키백과 한국어·영어처럼 한 플랫폼에 소스가 둘이면 괄호 앞 이름만 쓴다."""
    out: dict[str, str] = {}
    for s in sources.values():
        if "code" in s:
            out[s["code"]] = s["label"] if s["code"] not in out else s["label"].split(" (")[0]
    return out


def _dots(codes, sources_by_code: dict) -> str:
    return "".join(
        f'<span class="row small" style="gap:6px"><span class="dot" data-p="{escape(c)}"></span>{escape(sources_by_code.get(c, c))}</span>'
        for c in codes
    )


def _numbers_line(e: dict) -> str:
    parts = [f"하루 +{_n(e['velocity'])}{e['unit']}"]
    parts += [f"{label} {_n(e[key])}" for key, label in _METRIC_LABEL.items() if e.get(key) is not None]
    return " · ".join(parts)


def _summary(d: dict | None) -> str:
    """실탐 요약. LLM이 쓴 글이고, 아래에 어디까지 읽고 썼는지 적는다(명세 6번)."""
    if not d:
        return ""
    rows = [("무엇", d["what"]), ("왜 나왔나", d["why"]), ("어떻게 쓰이나", d["how"])]
    if d["comments_point"]:
        rows.append(("댓글 논점", d["comments_point"]))
    body = "".join(f'<p><b>{escape(l)}</b> · {escape(v)}</p>' for l, v in rows)
    return (
        f'<div class="read"><div class="small" style="font-weight:600">실탐 요약 — {escape(d["title"][:60])} (원문을 읽고 LLM이 씀)</div>'
        f'{body}<div class="small">읽은 범위: {escape(d["scope"])} · {escape(d["date"])} · {escape(d["model"])}</div></div>'
    )


def _curve(points: list[float]) -> str:
    """어텐션 곡선(작은 선 그래프). 점이 하나면 점 하나만 그린다."""
    if not points:
        return ""
    w, h, pad = 300, 56, 4
    top = max(points) or 1.0
    xs = [pad + (w - 2 * pad) * (i / max(len(points) - 1, 1)) for i in range(len(points))]
    ys = [h - pad - (h - 2 * pad) * (v / top) for v in points]
    if len(points) == 1:
        shape = f'<circle cx="{w / 2:.1f}" cy="{ys[0]:.1f}" r="3"/>'
    else:
        shape = '<path d="' + " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(zip(xs, ys))) + '"/>'
    return f'<svg class="curve" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" aria-label="어텐션 곡선">{shape}</svg>'


def _evidence(items: list[dict], n: int) -> list[tuple[str, dict]]:
    return topics.evidence(items, n)


def _ev_html(role: str, e: dict, sources: dict) -> str:
    src = sources[e["source"]]
    extra = ""
    repeated = e["extra"].get("comment_phrases")
    if repeated:  # 유튜브: 댓글 여러 개에 반복되는 말 (코드가 센 것)
        extra = f'<div class="meta">댓글에서 반복되는 말: {escape(" · ".join(p["text"] + " (" + str(p["count"]) + ")" for p in repeated))}</div>'
    who = e["item_extra"].get("channel_title") or e["origin"] or ""
    return (f'<div class="ev"><div class="row small" style="gap:6px"><b>{escape(role)}</b>'
            f'<span class="dot" data-p="{escape(src["code"])}"></span>{escape(src["label"])} · {escape(who)}</div>'
            f'<div class="t">{_link(e)}</div><div class="meta">{escape(_numbers_line(e))}</div>{extra}</div>')


def _label_chip(t: dict) -> str:
    if t["explore"]:
        return f'<span class="chip ex">{ICON_EX} 탐색</span>'
    if t["mode"] == "early":
        return f'<span class="chip line">{ICON_NOW} 지금 인기</span>'
    # 점수 모드: 처음 나타난 지 baseline_days 안이면 "신생", 아니면 "가속" (샘플 피드와 같다)
    if t.get("is_new"):
        return '<span class="chip line">＋ 신생</span>' + (' <span class="chip">임계 통과</span>' if t["passed"] else "")
    return f'<span class="chip line">{ICON_UP} 가속</span>' + (' <span class="chip">임계 통과</span>' if t["passed"] else "")


def _mark(t: dict, settings: dict, day: str) -> str:
    """'몰랐는데 흥미로움' 표시: 이미 했으면 표시만, 아니면 GitHub 이슈를 만드는 링크."""
    if t.get("interesting"):
        return '<span class="chip line">✓ 몰랐는데 흥미로움</span>'
    url = feedback.new_issue_url(settings, t["code"], day, t["name"])
    if not url:
        return ""
    return f'<a class="chip line" href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">몰랐는데 흥미로움</a>'


def _card(t: dict, place: int, sources: dict, cfg: dict, mark: str = "") -> str:
    by_code = _platform_labels(sources)
    if t["mode"] == "early" or t["score"] is None:
        big_label, big = "오늘 어텐션", f"{t['attention']:.1f}"
        nums = [("오늘 어텐션", f"{t['attention']:.1f}"), ("플랫폼 폭", f"{t['breadth']}곳"),
                ("출처", f"{t['origins']}곳"), ("항목", f"{t['item_count']}건")]
    else:
        big_label, big = "점수", f"{t['score']:.1f}"
        nums = [("평소 대비 z", f"{t['z']:.1f}"), ("가속", f"{t['accel']:.2f}배"),
                ("플랫폼 폭", f"{t['breadth']}곳"), ("출처", f"{t['origins']}곳")]
    tiles = "".join(f'<div class="num"><span class="small">{escape(l)}</span><b>{escape(v)}</b></div>' for l, v in nums)
    why = f'<p class="why">{escape(t["why"])}</p>' if t.get("why") else ""
    note = '<p class="sub">무작위 추첨으로 올라왔어요. 점수와 상관없어요.</p>' if t["explore"] else ""
    evidence = "".join(_ev_html(role, e, sources) for role, e in _evidence(t["items"], cfg["items_per_card"]))
    days_label = f"최근 {len(t['curve'])}일 어텐션"
    return f"""
<article class="card">
  <div class="cardhead">
    <div>
      <div class="row">
        <b>#{place}</b>
        {_label_chip(t)}
        <span class="small">{escape(t['field'])}</span>
        <span class="small">{escape(t['code'])}</span>
      </div>
      <h3>{escape(t['name'])}</h3>
      <div class="row">{"".join(f'<span class="chip">{escape(k)}</span>' for k in t.get("keywords", []))}</div>
      <div class="row">{_dots(t['platforms'], by_code)}</div>
      <div class="small">출처 {t['origins']}곳 · 항목 {t['item_count']}건 · 처음 나타난 날 {escape(t['first_seen'])}</div>
      {note}
      <div class="row">{mark}</div>
    </div>
    <div class="score"><span class="small">{escape(big_label)}</span><b>{escape(big)}</b></div>
  </div>
  <div class="cols">
    <div style="display:flex;flex-direction:column;gap:10px;min-width:0">
      <div class="small" style="font-weight:600">왜 올랐나</div>
      {why}
      <div class="nums">{tiles}</div>
      <div class="small">{escape(days_label)}</div>
      {_curve(t['curve'])}
    </div>
    <div style="display:flex;flex-direction:column;min-width:0">
      <div class="small" style="font-weight:600;margin-bottom:4px">근거</div>
      {evidence}
    </div>
  </div>
  {_summary(t.get("deepread"))}
</article>"""


def _row(t: dict, sources: dict, chip: str = "") -> str:
    by_code = _platform_labels(sources)
    value = f"점수 {t['score']:.1f}" if t["score"] is not None else f"어텐션 {t['attention']:.1f}"
    rank_txt = f"#{t['rank']}" if t["rank"] else "순위 밖"
    read = '<span class="chip">실탐</span>' if t.get("deepread") else '<span class="chip">메타만</span>'
    top_item = max(t["items"], key=lambda e: e["attention"])
    if t["name"] == top_item["title"]:  # 이름이 대표 글 제목 그대로면 한 번만 적고 그 제목에 링크를 건다
        name_html, meta_html = _link(top_item), escape(_numbers_line(top_item))
    else:
        name_html, meta_html = escape(t["name"]), f"{_link(top_item)} · {escape(_numbers_line(top_item))}"
    return f"""
<div class="item">
  <div><div class="row">{_dots(t['platforms'], by_code)}<span class="small">{rank_txt} · {escape(t['code'])}</span></div>
  <div class="t">{name_html}</div><div class="meta">{meta_html}</div></div>
  <div class="row"><span style="font-size:13px">{escape(value)} · 출처 {t['origins']}곳</span>{read}{chip}</div>
</div>"""


def _multi_curve(curves: dict[str, list[float]]) -> str:
    """플랫폼별 곡선(0~100)을 한 그림에. 플랫폼마다 색이 다르다."""
    w, h, pad = 600, 140, 6
    paths = []
    for p, values in curves.items():
        if not values:
            continue
        xs = [pad + (w - 2 * pad) * (i / max(len(values) - 1, 1)) for i in range(len(values))]
        ys = [h - pad - (h - 2 * pad) * (v / 100) for v in values]
        d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(zip(xs, ys)))
        paths.append(f'<path class="key-{escape(p)}" d="{d}"/>')
    return (f'<svg class="multi" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
            f'aria-label="플랫폼별 어텐션 곡선">{"".join(paths)}</svg>')


def _rollups(conn, day: str, settings: dict, top_code: str | None) -> str:
    """롤업 구역(명세 7번). 점수 모드에서만 부른다."""
    cfg = settings["rollup"]
    by_code = _platform_labels(settings["sources"])
    d, w, m = rollup.daily(conn, day, cfg), rollup.weekly(conn, day, cfg), rollup.monthly(conn, day, top_code, cfg)

    def rank_txt(r):
        return f"{r}위" if r else "순위 밖"

    def lines(rows, fmt):
        return "".join(f"<li>{fmt(r)}</li>" for r in rows) or "<li>없음</li>"

    day_html = (
        f'<h3 style="font-size:17px">일 — 어제와 오늘</h3><div class="cols">'
        f'<div><div class="small" style="font-weight:600">{cfg["daily_top"]}위 안에 새로 든 주제</div><ul>'
        + lines(d["entered"], lambda r: f"{escape(r[1])} ({rank_txt(r[2])} → {r[3]}위)") + "</ul></div>"
        f'<div><div class="small" style="font-weight:600">밖으로 나간 주제</div><ul>'
        + lines(d["left"], lambda r: f"{escape(r[1])} ({r[2]}위 → {rank_txt(r[3])})") + "</ul></div>"
        f'<div><div class="small" style="font-weight:600">가장 많이 오른 주제</div><ul>'
        + lines(d["risers"], lambda r: f"{escape(r[1])} ({r[2]}위 → {r[3]}위)") + "</ul></div></div>"
    )
    week_html = (
        f'<h3 style="font-size:17px">주 — 최근 7일</h3><div class="cols">'
        f'<div><div class="small" style="font-weight:600">지속 ({cfg["weekly_top"]}위 안에 든 날)</div><ul>'
        + lines(w["lasting"], lambda r: f"{escape(r[1])} ({r[2]}/{r[3]}일)") + "</ul></div>"
        f'<div><div class="small" style="font-weight:600">신규 (처음 나타난 지 {cfg["new_within_days"]}일 안 · 오늘 {cfg["new_top"]}위 안)</div><ul>'
        + lines(w["new"], lambda r: f"{escape(r[1])} ({r[2]}위)") + "</ul></div>"
        f'<div><div class="small" style="font-weight:600">이탈 ({cfg["weekly_top"]}위 안에 들었다가 오늘은 밖)</div><ul>'
        + lines(w["left"], lambda r: escape(r[1])) + "</ul></div></div>"
    )
    month_html = ""
    if m:
        legend = "".join(f'<span class="row small" style="gap:6px"><span class="key" data-p="{escape(p)}"></span>'
                         f'{escape(by_code.get(p, p))}</span>' for p in m["curves"])
        lag = " → ".join(f"{escape(by_code.get(p, p))} {first[5:]}" + (f" (+{gap}일)" if gap else "")
                         for p, first, gap in m["lags"])
        head = "<tr><th>날짜</th>" + "".join(f"<th>{escape(by_code.get(p, p))}</th>" for p in m["curves"]) + "</tr>"
        body = "".join(
            f"<tr><td>{escape(dd)}</td>" + "".join(f"<td>{m['curves'][p][i]:.0f}</td>" for p in m["curves"]) + "</tr>"
            for i, dd in enumerate(m["days"]))
        month_html = (
            f'<h3 style="font-size:17px">월 — {escape(m["name"])} ({escape(m["code"])})</h3>'
            f'<p class="sub">플랫폼별 최근 {len(m["days"])}일 어텐션(각 플랫폼 최대치 = 100). '
            f'각 플랫폼이 자기 최대치의 {int(cfg["lag_ratio"] * 100)}%를 처음 넘은 날: {lag}</p>'
            f'<div class="row">{legend}</div>{_multi_curve(m["curves"])}'
            f'<details><summary class="small">{len(m["days"])}일 값 표 펼치기</summary>'
            f'<div class="scroll"><table>{head}{body}</table></div></details>'
        )
    return f"""
  <section>
    <div><h2>롤업</h2>
    <p class="sub">일·주·월 요약이에요. 순위는 날마다 같은 점수식으로 계산한 것이에요.</p></div>
    <div class="card">{day_html}{week_html}{month_html}</div>
  </section>"""


def _llm_stat(conn, day: str) -> str:
    """맨 위 요약 칸: 오늘 실탐 몇 건, LLM을 몇 번 불렀고 토큰을 얼마나 썼나."""
    reads = conn.execute("SELECT COUNT(*) FROM deepreads WHERE date = ?", (day,)).fetchone()[0]
    calls, tin, tout = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0) FROM llm_calls WHERE date = ?",
        (day,),
    ).fetchone()
    if calls:
        return f"실탐 {reads}건 · LLM {calls}회 (입력 {tin:,} · 출력 {tout:,} 토큰)"
    if not config.secret(llm.KEY_NAME):
        return "LLM 키 없음 — 건너뜀"
    return "오늘은 새로 읽은 것 없음"


def load_topics(conn, day: str, settings: dict) -> dict[str, dict]:
    """그날의 주제들을 화면에 쓸 모양으로 모은다: 점수·항목·곡선·실탐·왜 올랐나."""
    entries = {e["item_id"]: e for e in rank.now_popular(conn, day, settings)
               + rank.now_popular(conn, day, settings, explore=True)}
    days = score.run_days(conn, day)[-settings["feed"]["curve_days"]:]
    out: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT s.*, t.name, t.field, t.first_seen, t.keywords, d.attention, d.platforms, d.item_count FROM topic_score s "
        "JOIN topics t ON t.code = s.topic_code JOIN topic_daily d ON d.topic_code = s.topic_code AND d.date = s.date "
        "WHERE s.date = ?", (day,)
    ):
        t = dict(r)
        t["code"] = r["topic_code"]
        t["platforms"] = sorted(json.loads(r["platforms"]))
        t["explore"] = False          # Top 5 다섯째 자리에 오른 탐색 주제만 True 가 된다
        t["from_explore"] = bool(r["explore"])
        t["keywords"] = json.loads(r["keywords"] or "[]")
        t["is_new"] = (date.fromisoformat(day) - date.fromisoformat(r["first_seen"])).days < settings["score"]["baseline_days"]
        t["items"] = []
        out[t["code"]] = t
    for item_id, code in conn.execute("SELECT item_id, topic_code FROM topic_items WHERE date = ?", (day,)):
        if code in out and item_id in entries:
            out[code]["items"].append(entries[item_id])
    history: dict[str, dict[str, float]] = {}
    if days:
        for code, d, att in conn.execute(
            "SELECT topic_code, date, attention FROM topic_daily WHERE date >= ? AND date <= ?", (days[0], day)
        ):
            history.setdefault(code, {})[d] = att
    for code, t in out.items():
        t["curve"] = [history.get(code, {}).get(d, 0.0) for d in days]
        t["why"] = None
    for code, sentence in conn.execute("SELECT topic_code, sentence FROM topic_why WHERE date = ?", (day,)):
        if code in out:
            out[code]["why"] = sentence
    for code, t in out.items():
        t["deepread"] = None
        ids = [e["item_id"] for e in t["items"]]
        if ids:
            row = conn.execute(
                f"SELECT d.*, i.title FROM deepreads d JOIN items i ON i.id = d.item_id "
                f"WHERE d.item_id IN ({','.join('?' * len(ids))}) AND d.date <= ? ORDER BY d.date DESC LIMIT 1",
                (*ids, day),
            ).fetchone()
            t["deepread"] = dict(row) if row else None
    return {c: t for c, t in out.items() if t["items"]}


def build(conn, day: str, settings: dict) -> str:
    cfg, sources = settings["feed"], settings["sources"]
    tz = ZoneInfo(settings["general"]["timezone"])
    topics_today = load_topics(conn, day, settings)
    ranked = sorted((t for t in topics_today.values() if t["rank"]), key=lambda t: t["rank"])
    mode = ranked[0]["mode"] if ranked else ("early" if len(score.run_days(conn, day)) < settings["score"]["baseline_days"] else "score")
    days = len(score.run_days(conn, day))
    need = settings["score"]["baseline_days"]
    runs = [dict(r) for r in conn.execute("SELECT * FROM source_runs WHERE date = ? ORDER BY source", (day,))]

    # Top 5 = 순위 위 (top_n − 1)건 + 탐색 1건
    top = ranked[: cfg["top_n"] - 1]
    shown = {t["code"] for t in top}
    picks = [topics_today[c] for c in score.explore_picks(conn, day, settings, shown) if c in topics_today]
    if picks:
        picks[0]["explore"] = True
    marked = {r[0] for r in conn.execute("SELECT topic_code FROM feedback WHERE date = ? AND interesting = 1", (day,))}
    top5 = top + picks[:1]
    for t in top5:
        t["interesting"] = t["code"] in marked
    cards = [_card(t, i, sources, cfg, _mark(t, settings, day)) for i, t in enumerate(top5, start=1)]
    liked = sum(t["interesting"] for t in top5)

    # 분야별 Top 3 (명세 5번: 분야마다 3건씩 따로 보여 준다)
    fields: list[str] = []
    for src in sources.values():
        if src.get("enabled") and src["field"] not in fields:
            fields.append(src["field"])
    field_html = []
    for field in fields:
        picks_f = [t for t in ranked if t["field"] == field][: cfg["per_field_n"]]
        body = "".join(_row(t, sources) for t in picks_f) or '<p class="sub" style="padding:10px 0">오늘 순위에 든 주제가 없어요.</p>'
        field_html.append(f'<h3 style="font-size:17px">{escape(field)}</h3><div class="card list">{body}</div>')

    explore_rows = "".join(
        _row(t, sources, '<span class="chip">Top 5로 올라감</span>' if i == 0 else "") for i, t in enumerate(picks)
    )

    ok = sum(r["item_count"] > 0 for r in runs)
    explore_by_source = {r["source"]: db.explore_count(conn, day, r["source"]) for r in runs}
    explore_total = sum(explore_by_source.values())
    total_items = sum(r["item_count"] for r in runs)
    run_row = conn.execute("SELECT started_at, finished_at FROM daily_runs WHERE date = ?", (day,)).fetchone()
    started = run_row["started_at"] if run_row and run_row["started_at"] else min((r["started_at"] for r in runs), default=None)
    run_line = "오늘 실행 기록이 없어요."
    if started:
        begin = datetime.fromisoformat(started).astimezone(tz)
        run_line = f"{begin:%H:%M} 시작 · {day}"
        if run_row and run_row["finished_at"]:
            end = datetime.fromisoformat(run_row["finished_at"]).astimezone(tz)
            minutes = max(1, round((end - begin).total_seconds() / 60))
            run_line = f"{begin:%H:%M} 시작 → {end:%H:%M} 완료 · 총 {minutes}분 · {day}"
    passed = sum(1 for t in topics_today.values() if t["passed"])
    reads = sum(1 for t in topics_today.values() if t.get("deepread"))
    stats = [
        ("수집", f"{total_items}건 + 탐색 {explore_total}건 · 소스 {len(runs)}곳 중 {ok}곳 수집됨"),
        ("주제", f"{len(topics_today)}개 · 순위에 든 주제 {len(ranked)}개"),
        ("기준선" if mode == "early" else "임계 통과", f"{min(days, need)}/{need}일" if mode == "early" else f"{passed}개"),
        ("실탐 · 요약", _llm_stat(conn, day)),
    ]
    stats_html = "".join(f'<div class="tile"><span class="small">{escape(l)}</span><b>{escape(v)}</b></div>' for l, v in stats)

    status_rows = []
    for r in runs:
        src = sources.get(r["source"], {})
        note = r["memo"] or ("목록 밖 " + str(r["followed_count"]) + "건은 숫자만 다시 적음" if r["followed_count"] else "")
        status_rows.append(
            f'<tr><td><span class="row" style="gap:8px;font-weight:600"><span class="dot" data-p="{escape(src.get("code", ""))}"></span>'
            f'{escape(src.get("label", r["source"]))}</span></td><td>{escape(src.get("field", ""))}</td>'
            f'<td>{r["item_count"]}건' + (f' + 탐색 {explore_by_source[r["source"]]}' if explore_by_source.get(r["source"]) else "")
            + f'</td><td>{src.get("weight", "")}</td>'
            f'<td><span class="st {escape(r["status"])}"><i></i>{STATUS_LABEL[r["status"]]}</span></td><td>{escape(note)}</td></tr>'
        )
    by_purpose = dict(conn.execute("SELECT purpose, COUNT(*) FROM llm_calls WHERE date = ? GROUP BY purpose", (day,)).fetchall())
    tin, tout = conn.execute("SELECT COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0) FROM llm_calls "
                             "WHERE date = ?", (day,)).fetchone()
    run_facts = (f"실탐 시간 예산 {settings['deepread']['budget_minutes']}분 · 임계 {settings['score']['threshold']}"
                 + (" (기준선 14일 뒤부터 씀)" if mode == "early" else "")
                 + f" · LLM {sum(by_purpose.values())}회(이름·병합 {by_purpose.get('topics', 0)} · 실탐 "
                 f"{by_purpose.get('deepread', 0)} · 왜 올랐나 {by_purpose.get('why', 0)}) · 토큰 입력 {tin:,} · 출력 {tout:,}"
                 f" · 모델 {settings['llm']['model']}")
    tool = conn.execute("SELECT deepread_tool FROM daily_runs WHERE date = ?", (day,)).fetchone()
    if tool and tool[0]:
        run_facts += f" · 실탐 도구: {tool[0]}"
    for name, field, memo in cfg.get("empty_slots", []):
        status_rows.append(
            f'<tr><td><span class="row" style="gap:8px;font-weight:600"><span class="dot"></span>{escape(name)}</span></td>'
            f'<td>{escape(field)}</td><td>—</td><td>—</td><td><span class="st empty"><i></i>빈 칸</span></td>'
            f'<td>{escape(memo)}</td></tr>'
        )
    pipeline = (f"수집 {total_items}건 → 주제 {len(topics_today)}개 → 순위 {len(ranked)}개"
                + (f" → 임계 통과 {passed}개" if mode != "early" else "") + f" → 실탐 요약이 붙은 주제 {reads}개")

    if mode == "early":
        pct = round(100 * min(days, need) / need)
        notice = f"""
    <div class="notice">
      <p><b>기준선이 쌓이는 중이에요 ({min(days, need)}/{need}일).</b> 지금은 "평소 대비" 없이 오늘 어텐션 순으로만 보여 줘요.
      {need}일이 차면 평소 대비 점수(z)와 가속이 켜지고 롤업(일·주·월 요약)이 나타나요.</p>
      <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="{need}" aria-valuenow="{min(days, need)}"><i style="width:{pct}%"></i></div>
    </div>"""
        top_sub = (f"지금 인기 순 · 오늘 어텐션이 높은 {len(top)}건 + 탐색 1건이에요. "
                   "어텐션 = 주제에 묶인 글마다 '하루 증가량이 그 소스의 보통 글의 몇 배인가'를 더한 값.")
        top_title = f"지금 인기 Top {cfg['top_n']}"
    else:
        notice = ""
        top_sub = (f"점수 순 위 {len(top)}건 + 탐색 1건이에요. 점수 = 평소 대비(z, 상한 {settings['score']['z_cap']}) "
                   f"+ 가속 + 플랫폼 폭. 임계 {settings['score']['threshold']} 이상이면 '임계 통과'예요.")
        top_title = f"교차 플랫폼 Top {cfg['top_n']}"

    first = conn.execute("SELECT topic_code FROM topic_score WHERE date = ? AND rank = 1", (day,)).fetchone()
    rollups = _rollups(conn, day, settings, first[0] if first else None) if mode == "score" else ""
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
    <p class="sub">{escape(run_line)} · 오늘 Top {len(top5)} 중 "몰랐는데 흥미로움" {liked}개</p>
    <div class="tiles">{stats_html}</div>
    {notice}
  </header>

  <section>
    <div><h2>{escape(top_title)}</h2>
    <p class="sub">{escape(top_sub)}</p></div>
    <div class="cards">{"".join(cards) or '<p class="sub">오늘 순위에 올릴 주제가 없어요.</p>'}</div>
  </section>

  <section>
    <div><h2>분야별 Top {cfg['per_field_n']}</h2>
    <p class="sub">분야마다 순위 위 {cfg['per_field_n']}개예요. "실탐"은 원문을 읽고 요약한 주제, "메타만"은 수치만 본 주제예요.</p></div>
    {"".join(field_html)}
  </section>

  {rollups}

  <section>
    <div><h2>탐색 슬롯</h2>
    <p class="sub">관심 목록 밖에서 무작위로 모은 글(수집의 약 20%) 중 {len(picks)}건이에요. 점수와 상관없고, 이 중 1건이 위 Top 5의 마지막 자리로 올라갔어요.</p></div>
    <div class="card list">{explore_rows or '<p class="sub" style="padding:10px 0">뽑을 주제가 없어요.</p>'}</div>
  </section>

  <section>
    <div><h2>수집 상태와 오늘의 실행</h2>
    <p class="sub">소스마다 오늘 몇 건을 가져왔는지, 막힌 곳은 없는지 보여 줘요.</p></div>
    <div class="card"><div class="scroll"><table>
      <tr><th>소스</th><th>분야</th><th>수집</th><th>가중치</th><th>상태</th><th>비고</th></tr>
      {"".join(status_rows) or '<tr><td colspan="6">오늘 실행 기록이 없어요.</td></tr>'}
    </table></div>
    <p class="sub">{escape(pipeline)}</p>
    <p class="sub">{escape(run_facts)}</p></div>
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
