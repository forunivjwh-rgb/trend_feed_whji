'use strict';
const fs = require('fs'), vm = require('vm'), path = require('path');
const LOGIC = fs.readFileSync(path.join(__dirname, 'logic.js'), 'utf8');

/* ---------- 작은 DSL: 태그가 항상 짝이 맞고 속성이 항상 따옴표로 묶이게 ---------- */
function h(t, a) {
  const k = Array.prototype.slice.call(arguments, 2).reduce(function (x, y) { return x.concat(Array.isArray(y) ? y : [y]); }, []);
  return { t: t, a: a || {}, k: k.filter(function (x) { return x !== null && x !== undefined && x !== false; }) };
}
const esc = function (s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); };
const escA = function (s) { return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;'); };
function ser(n) {
  if (typeof n === 'string') return esc(n);
  let at = '';
  Object.keys(n.a).forEach(function (key) { const v = n.a[key]; if (v === false || v == null) return; at += v === true ? ' ' + key : ' ' + key + '="' + escA(v) + '"'; });
  const hasEl = n.k.some(function (c) { return typeof c !== 'string'; });
  const inner = n.k.map(ser).join(hasEl ? '\n' : '');
  return '<' + n.t + at + '>' + (hasEl ? '\n' + inner + '\n' : inner) + '</' + n.t + '>';
}

/* ---------- 구멍({{...}}) 검사: 모델에 없는 이름을 쓰면 빌드가 멈춰요 ---------- */
function holes(s) { const out = []; const re = /\{\{\s*([^}]+?)\s*\}\}/g; let m; while ((m = re.exec(s))) out.push(m[1]); return out; }
function lookup(scope, p) { return p.split('.').reduce(function (v, k) { return v == null ? undefined : v[k]; }, scope); }
const LITERAL = /^(true|false|null|-?\d+(\.\d+)?|\$index)$/;
function check(n, scope, errs, where) {
  if (typeof n === 'string') { holes(n).forEach(function (p) { if (!LITERAL.test(p) && lookup(scope, p) === undefined) errs.push('text hole: ' + p + ' @ ' + where); }); return; }
  const w = where + '>' + n.t;
  Object.keys(n.a).forEach(function (key) {
    const v = n.a[key]; if (typeof v !== 'string') return;
    holes(v).forEach(function (p) { if (!LITERAL.test(p) && lookup(scope, p) === undefined) errs.push('attr ' + key + ' hole: ' + p + ' @ ' + w); });
  });
  if (n.t === 'sc-for') {
    const lp = holes(n.a.list)[0], arr = lookup(scope, lp);
    if (!Array.isArray(arr)) { errs.push('sc-for list not array: ' + lp + ' @ ' + w); return; }
    if (!arr.length) { errs.push('(warn) empty list: ' + lp); return; }
    const sc2 = Object.create(scope); sc2[n.a.as] = arr[0];
    n.k.forEach(function (c) { check(c, sc2, errs, w); });
    return;
  }
  n.k.forEach(function (c) { check(c, scope, errs, w); });
}

/* ---------- 스타일 조각 ---------- */
const S = {
  card: 'background:var(--surface-1); border:1px solid var(--border); border-radius:12px; padding:16px; display:flex; flex-direction:column; gap:14px; min-width:0',
  chip: 'display:inline-flex; align-items:center; gap:6px; padding:2px 10px; border-radius:999px; background:var(--chip-bg); color:var(--text-secondary); font-size:12px; line-height:1.7; white-space:nowrap',
  lbl: 'font-size:12px; line-height:1.5; color:var(--text-secondary)',
  lblB: 'font-size:12px; line-height:1.5; color:var(--text-secondary); font-weight:600',
  h2: 'font-size:22px; line-height:1.3; font-weight:700',
  sub: 'font-size:13px; line-height:1.55; color:var(--text-secondary)',
  stat: 'display:flex; flex-direction:column; gap:2px; padding:10px 12px; border:1px solid var(--border); border-radius:10px; background:var(--surface-1); min-width:0',
  metric: 'display:flex; flex-direction:column; gap:2px; padding:8px 10px; border-radius:8px; background:var(--chip-bg); min-width:0',
  evi: 'display:flex; flex-direction:column; gap:6px; padding:10px 12px; border:1px solid var(--grid); border-radius:10px; min-width:0',
  ink: 'color:var(--text-primary)'
};
const ifv = function (p) { return h.apply(null, ['sc-if', { value: '{{' + p + '}}', 'hint-placeholder-val': '{{ true }}' }].concat(Array.prototype.slice.call(arguments, 1))); };
const forv = function (list, as, cnt) { return h.apply(null, ['sc-for', { list: '{{' + list + '}}', as: as, 'hint-placeholder-count': String(cnt) }].concat(Array.prototype.slice.call(arguments, 3))); };
const dot = function (c) { return h('span', { class: 'dot', 'data-p': c }); };
const key = function (c) { return h('span', { class: 'key', 'data-p': c }); };
const tagd = function (f, k) { return { 'data-f': f, 'data-k': k }; };
function sec(title, sub) {
  const rest = Array.prototype.slice.call(arguments, 2);
  return h.apply(null, ['section', { style: 'display:flex; flex-direction:column; gap:14px' },
    h('div', { style: 'display:flex; flex-direction:column; gap:4px' }, h('h2', { style: S.h2 }, title), sub ? h('p', { style: S.sub }, sub) : null)].concat(rest));
}
function icon(d) { return h('svg', { width: '12', height: '12', viewBox: '0 0 12 12', 'aria-hidden': 'true', style: 'flex:0 0 auto' }, h('path', { d: d, style: 'fill:none; stroke:currentColor; stroke-width:1.6; stroke-linecap:round; stroke-linejoin:round' })); }
const icTarget = h('svg', { width: '12', height: '12', viewBox: '0 0 12 12', 'aria-hidden': 'true', style: 'flex:0 0 auto' },
  h('circle', { cx: '6', cy: '6', r: '4.2', style: 'fill:none; stroke:currentColor; stroke-width:1.4' }), h('circle', { cx: '6', cy: '6', r: '1.2', style: 'fill:currentColor' }));
function spark(pp, big) {
  const W = big ? 300 : 150, H = big ? 108 : 40;
  const els = [
    h('rect', { x: '{{' + pp + '.bx}}', y: '{{' + pp + '.by}}', width: '{{' + pp + '.bw}}', height: '{{' + pp + '.bh}}', style: 'fill:var(--band)', opacity: '{{' + pp + '.op}}' }),
    h('line', { x1: '{{' + pp + '.bx}}', x2: '{{' + pp + '.bx2}}', y1: '{{' + pp + '.my}}', y2: '{{' + pp + '.my}}', style: 'stroke:var(--axis); stroke-width:1', opacity: '{{' + pp + '.op}}' }),
    h('polyline', { points: '{{' + pp + '.pts}}', style: 'fill:none; stroke:var(--s1); stroke-width:2; stroke-linejoin:round; stroke-linecap:round' }),
    h('circle', { cx: '{{' + pp + '.lx}}', cy: '{{' + pp + '.ly}}', r: '4', style: 'fill:var(--s1); stroke:var(--surface-1); stroke-width:2' })
  ];
  if (big) els.push(
    h('text', { x: '{{' + pp + '.tx}}', y: '{{' + pp + '.ty}}', 'font-size': '12', style: 'fill:var(--text-primary); font-weight:600' }, '{{' + pp + '.lab}}'),
    h('text', { x: '{{' + pp + '.ax}}', y: '{{' + pp + '.ay}}', 'font-size': '11', style: 'fill:var(--text-secondary)' }, '{{' + pp + '.l0}}'),
    h('text', { x: '{{' + pp + '.bx2}}', y: '{{' + pp + '.ay}}', 'font-size': '11', 'text-anchor': 'end', style: 'fill:var(--text-secondary)' }, '오늘'));
  return h.apply(null, ['svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': '{{' + pp + '.aria}}',
    style: big ? 'width:100%; max-width:360px; height:auto; display:block' : 'width:150px; max-width:100%; height:auto; display:block' }].concat(els));
}

/* ---------- 헤더 ---------- */
const header = h('header', { style: 'display:flex; flex-direction:column; gap:14px' },
  h('div', { style: 'display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px' },
    h('h1', { style: 'font-size:28px; line-height:1.2; font-weight:700' }, '오늘의 유행 피드'),
    h('span', { style: S.chip + '; ' + S.ink + '; border:1px solid var(--axis)' }, '샘플 데이터 — 이름과 수치는 모두 가상이에요'),
    h('span', Object.assign({ style: S.lbl }, tagd('run.day_no', '계산')), '{{head.day}}')),
  h('p', Object.assign({ style: S.sub }, tagd('run.finished_at', '계산')), '{{head.run}}'),
  h('div', { style: 'display:grid; grid-template-columns:repeat(auto-fit, minmax(min(240px,100%), 1fr)); gap:8px' },
    forv('head.stats', 's', 4,
      h('div', { style: S.stat },
        h('span', { style: S.lbl }, '{{s.l}}'),
        h('span', { style: 'font-size:14px; font-weight:600; line-height:1.45', 'data-f': '{{s.f}}', 'data-k': '{{s.k}}' }, '{{s.v}}')))),
  h('div', { style: 'display:flex; flex-wrap:wrap; gap:8px; align-items:center' },
    h('div', { role: 'group', 'aria-label': '보기 모드', style: 'display:inline-flex; flex-wrap:wrap; gap:8px' },
      h('button', { class: 'btn', type: 'button', 'aria-pressed': '{{matureP}}', onClick: '{{setMature}}' }, '성숙 모드 (가동 31일차)'),
      h('button', { class: 'btn', type: 'button', 'aria-pressed': '{{earlyP}}', onClick: '{{setEarly}}' }, '초기 모드 (가동 3일차)')),
    h('button', { class: 'btn', type: 'button', 'aria-pressed': '{{fieldsP}}', onClick: '{{toggleFields}}' }, '필드명 보기'),
    h('span', Object.assign({ style: S.lbl }, tagd('feedback.liked', '입력')), '{{head.liked}}')),
  ifv('showFields', h('div', { style: 'display:flex; flex-wrap:wrap; gap:4px 14px; font-size:12px; line-height:1.6; color:var(--text-secondary)' },
    h('span', { style: S.ink + '; font-weight:600' }, '태그 읽는 법: 표.필드 · 종류'),
    h('span', {}, '수집 = 소스가 준 값'), h('span', {}, '계산 = 로직이 계산'), h('span', {}, 'LLM = 모델이 쓴 문장'), h('span', {}, '실탐 = 원문을 읽은 결과'), h('span', {}, '입력 = 내가 누른 값'))),
  ifv('isEarly', h('div', { style: S.card + '; gap:10px' },
    h('p', { style: 'font-size:14px; line-height:1.6' }, '{{earlyBar.txt}}'),
    h('div', { 'aria-hidden': 'true', style: 'height:8px; border-radius:999px; background:var(--band); overflow:hidden' },
      h('div', { style: 'height:100%; width:{{earlyBar.pct}}; background:var(--s1); border-radius:999px' }))))
);

/* ---------- A. Top 5 ---------- */
const card = h('article', { style: S.card },
  h('div', { style: 'display:flex; flex-wrap:wrap; gap:12px 16px; align-items:flex-start; justify-content:space-between' },
    h('div', { style: 'display:flex; flex-direction:column; gap:8px; min-width:0; flex:1 1 320px' },
      h('div', { style: 'display:flex; flex-wrap:wrap; align-items:center; gap:8px' },
        h('span', { style: 'font-size:14px; font-weight:700' }, '{{c.rank}}'),
        h('span', Object.assign({ style: S.chip + '; ' + S.ink + '; border:1px solid var(--axis)' }, tagd('topics.label', '계산')),
          ifv('c.isNew', icon('M6 2.5v7M2.5 6h7')), ifv('c.isAccel', icon('M3 9L9 3M4.5 3H9v4.5')), ifv('c.isEx', icTarget), ifv('c.isNow', icon('M3 9.5V6M6 9.5V3M9 9.5V5')),
          '{{c.label}}'),
        h('span', Object.assign({ style: S.lbl }, tagd('topics.id', '계산')), '{{c.id}}')),
      h('h3', Object.assign({ style: 'font-size:20px; line-height:1.35; font-weight:700; overflow-wrap:anywhere' }, tagd('topics.name', 'LLM')), '{{c.name}}'),
      h('div', Object.assign({ style: 'display:flex; flex-wrap:wrap; align-items:center; gap:6px' }, tagd('topics.keywords', '계산')),
        forv('c.kw', 'w', 4, h('span', { style: S.chip }, '{{w.w}}'))),
      h('div', Object.assign({ style: 'display:flex; flex-wrap:wrap; align-items:center; gap:4px 12px' }, tagd('topic_daily.platforms', '수집')),
        forv('c.plats', 'p', 3, h('span', { style: 'display:inline-flex; align-items:center; gap:6px; font-size:12px; color:var(--text-secondary)' }, dot('{{p.c}}'), '{{p.n}}'))),
      ifv('c.isEx', h('p', Object.assign({ style: 'font-size:13px; line-height:1.55; color:var(--text-primary)' }, tagd('explore_picks.reason', '계산')), '{{c.note}}'))),
    h('div', { style: 'display:flex; flex-direction:column; align-items:flex-end; gap:2px' },
      h('span', { style: S.lbl }, '{{c.scoreL}}'),
      h('span', Object.assign({ style: 'font-size:32px; line-height:1.1; font-weight:700' }, tagd('topic_score.score', '계산')), '{{c.scoreV}}'))),
  h('div', { style: 'display:grid; grid-template-columns:repeat(auto-fit, minmax(min(320px,100%), 1fr)); gap:16px 24px; align-items:start' },
    h('div', { style: 'display:flex; flex-direction:column; gap:10px; min-width:0' },
      h('div', { style: S.lblB }, '왜 올랐나 (수치)'),
      h('div', { style: 'display:grid; grid-template-columns:repeat(auto-fit, minmax(min(128px,100%), 1fr)); gap:8px' },
        forv('c.metrics', 'm', 4,
          h('div', { style: S.metric },
            h('span', { style: S.lbl }, '{{m.l}}'),
            h('span', { style: 'font-size:18px; line-height:1.3; font-weight:700', 'data-f': '{{m.f}}', 'data-k': '{{m.k}}' }, '{{m.v}}')))),
      h('p', Object.assign({ style: 'font-size:14px; line-height:1.65' }, tagd('topics.why_text', 'LLM')), '{{c.why}}')),
    h('figure', { style: 'display:flex; flex-direction:column; gap:6px; min-width:0' },
      spark('c.sp', true),
      h('figcaption', { style: S.lbl }, '{{c.cap}}'))),
  h('div', { style: 'display:flex; flex-direction:column; gap:8px' },
    h('div', { style: S.lblB }, '근거 3건'),
    h('ul', { style: 'list-style:none; margin:0; padding:0; display:grid; grid-template-columns:repeat(auto-fit, minmax(min(280px,100%), 1fr)); gap:8px' },
      forv('c.ev', 'e', 3,
        h('li', { style: S.evi },
          h('div', { style: 'display:flex; flex-wrap:wrap; align-items:center; gap:4px 8px' },
            h('span', Object.assign({ style: S.chip + '; ' + S.ink }, tagd('topic_items.role', '계산')), '{{e.r}}'),
            h('span', Object.assign({ style: 'display:inline-flex; align-items:center; gap:6px; font-size:12px; color:var(--text-secondary)' }, tagd('items.platform', '수집')), dot('{{e.c}}'), '{{e.p}}'),
            h('span', Object.assign({ style: S.lbl }, tagd('items.published_at', '계산')), '{{e.a}}')),
          h('div', Object.assign({ style: 'font-size:14px; line-height:1.5; font-weight:600; overflow-wrap:anywhere' }, tagd('items.title', '수집')), '{{e.t}}'),
          h('div', Object.assign({ style: S.lbl }, tagd('items.origin', '수집')), '{{e.o}}'),
          h('div', Object.assign({ style: 'font-size:13px; line-height:1.5' }, tagd('item_snapshots.metrics', '수집')), '{{e.m}}'))))),
  h('details', { open: '{{c.open}}', style: 'border-top:1px solid var(--grid)' },
    h('summary', { style: 'cursor:pointer; list-style:none; display:block' },
      h('span', { style: 'display:flex; flex-wrap:wrap; align-items:center; gap:2px 8px; min-height:44px' },
        h('span', { class: 'chev', 'aria-hidden': 'true' }),
        h('span', { style: 'font-size:14px; font-weight:600' }, '실탐 요약'),
        h('span', { style: S.lbl }, '{{c.dk}} · {{c.drd}}'))),
    h('div', { style: 'display:flex; flex-direction:column; gap:12px; padding:4px 0 8px' },
      forv('c.db', 'b', 3,
        h('div', { style: 'display:flex; flex-wrap:wrap; gap:2px 12px' },
          h('span', { style: S.lblB + '; flex:0 0 88px' }, '{{b.h}}'),
          h('span', Object.assign({ style: 'flex:1 1 260px; font-size:14px; line-height:1.65; min-width:0' }, tagd('deepreads.summary', 'LLM')), '{{b.t}}'))),
      h('div', { style: 'display:flex; flex-wrap:wrap; gap:2px 12px' },
        h('span', { style: S.lblB + '; flex:0 0 88px' }, '커뮤 반응'),
        h('span', Object.assign({ style: 'flex:1 1 260px; font-size:14px; line-height:1.65; min-width:0' }, tagd('deepreads.community', 'LLM')), '{{c.dc}}')),
      h('div', { style: 'display:flex; flex-wrap:wrap; gap:2px 12px' },
        h('span', { style: S.lblB + '; flex:0 0 88px' }, '읽은 범위'),
        h('span', Object.assign({ style: 'flex:1 1 260px; font-size:13px; line-height:1.6; color:var(--text-secondary); min-width:0' }, tagd('deepreads.scope', '실탐')), '{{c.dsc}}')),
      h('div', { style: 'display:flex; flex-wrap:wrap; gap:2px 12px' },
        h('span', { style: S.lblB + '; flex:0 0 88px' }, '재탐색'),
        h('span', Object.assign({ style: 'flex:1 1 260px; font-size:13px; line-height:1.6; color:var(--text-secondary); min-width:0' }, tagd('deepreads.next_allowed', '계산')), '7일 동안은 다시 읽지 않아요')))),
  h('div', { style: 'display:flex; flex-wrap:wrap; align-items:center; gap:10px' },
    h('button', Object.assign({ class: 'btn', type: 'button', 'aria-pressed': '{{c.likedStr}}', onClick: '{{c.toggle}}' }, tagd('feedback.liked', '입력')),
      ifv('c.isLiked', icon('M2.5 6.5l2.5 2.5 4.5-5')), '몰랐는데 흥미로움'))
);
const secA = sec('교차 플랫폼 Top 5', '{{topSub}}', h('div', { style: 'display:flex; flex-direction:column; gap:16px' }, forv('top5', 'c', 5, card)));

/* ---------- B. 분야별 ---------- */
const row = h('div', { style: 'display:flex; flex-direction:column; gap:8px; padding-top:12px; border-top:1px solid var(--grid)' },
  h('div', { style: 'display:flex; flex-wrap:wrap; align-items:center; gap:6px 8px' },
    h('span', { style: 'font-size:13px; font-weight:700' }, '{{r.rank}}'),
    h('span', Object.assign({ style: S.chip + '; ' + S.ink }, tagd('topics.label', '계산')), '{{r.label}}'),
    ifv('r.inTop5', h('span', { style: S.chip + '; ' + S.ink + '; border:1px solid var(--axis)' }, '{{r.top5}}')),
    ifv('r.deep', h('span', Object.assign({ style: S.chip + '; ' + S.ink + '; border:1px solid var(--axis)' }, tagd('deepreads.status', '계산')), '실탐')),
    ifv('r.notDeep', h('span', Object.assign({ style: S.chip }, tagd('deepreads.status', '계산')), '메타만'))),
  h('div', Object.assign({ style: 'font-size:15px; line-height:1.4; font-weight:600; overflow-wrap:anywhere' }, tagd('topics.name', 'LLM')), '{{r.name}}'),
  h('div', { style: 'display:flex; flex-wrap:wrap; align-items:flex-end; justify-content:space-between; gap:8px 12px' },
    h('div', { style: 'display:flex; flex-direction:column; gap:3px; min-width:0; flex:1 1 200px' },
      h('div', { style: 'display:flex; align-items:center; gap:6px; font-size:12px; color:var(--text-secondary)' }, dot('{{r.rc}}'), '{{r.rp}} · 대표'),
      h('div', Object.assign({ style: 'font-size:13px; line-height:1.5; overflow-wrap:anywhere' }, tagd('items.title', '수집')), '{{r.rt}}'),
      h('div', Object.assign({ style: S.lbl }, tagd('item_snapshots.metrics', '수집')), '{{r.rm}}')),
    spark('r.sp', false)),
  h('div', { style: 'display:flex; flex-wrap:wrap; gap:2px 16px; font-size:12px; color:var(--text-secondary)' },
    h('span', { style: 'display:inline-flex; gap:4px' }, h('span', {}, '{{r.n1l}}'), h('span', { style: S.ink + '; font-weight:600' }, '{{r.n1v}}')),
    h('span', { style: 'display:inline-flex; gap:4px' }, h('span', {}, '{{r.n2l}}'), h('span', { style: S.ink + '; font-weight:600' }, '{{r.n2v}}')),
    ifv('r.showScore', h('span', { style: 'display:inline-flex; gap:4px' }, h('span', {}, '{{r.n3l}}'), h('span', { style: S.ink + '; font-weight:600' }, '{{r.n3v}}'))),
    h('span', {}, '{{r.plTxt}}')),
  ifv('r.hasOne', h('p', Object.assign({ style: 'font-size:13px; line-height:1.6' }, tagd('deepreads.summary', 'LLM')), '{{r.one}}'))
);
const secB = sec('분야별 Top 3', '{{bSub}}',
  h('div', { style: 'display:grid; grid-template-columns:repeat(auto-fit, minmax(min(460px,100%), 1fr)); gap:16px; align-items:start' },
    forv('fields', 'f', 5,
      h('div', { style: S.card + '; gap:12px' },
        h('div', { style: 'display:flex; flex-direction:column; gap:2px' }, h('h3', { style: 'font-size:17px; line-height:1.35; font-weight:700' }, '{{f.n}}'), h('p', { style: S.lbl }, '{{f.src}}')),
        forv('f.rows', 'r', 3, row)))));

/* ---------- C. 탐색 슬롯 ---------- */
const secC = sec('탐색 슬롯', '관심 목록 밖에서 무작위로 뽑은 5건이에요. 점수와 상관없고, 이 중 1건이 위 Top 5의 #5로 올라갔어요.',
  h('div', { style: S.card + '; gap:0; padding-top:4px; padding-bottom:4px' },
    forv('pool', 'p', 5,
      h('div', { style: 'display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:6px 12px; padding:10px 0; border-bottom:1px solid var(--grid)' },
        h('div', { style: 'display:flex; flex-direction:column; gap:3px; min-width:0; flex:1 1 260px' },
          h('div', { style: 'display:flex; align-items:center; gap:6px; font-size:12px; color:var(--text-secondary)' }, dot('{{p.c}}'), '{{p.p}}'),
          h('div', Object.assign({ style: 'font-size:14px; line-height:1.5; font-weight:600; overflow-wrap:anywhere' }, tagd('items.title', '수집')), '{{p.t}}')),
        h('div', { style: 'display:flex; flex-wrap:wrap; align-items:center; gap:6px 10px' },
          h('span', Object.assign({ style: 'font-size:13px' }, tagd('item_snapshots.metrics', '수집')), '{{p.m}}'),
          ifv('p.up', h('span', Object.assign({ style: S.chip + '; ' + S.ink + '; border:1px solid var(--axis)' }, tagd('explore_picks.promoted', '계산')), 'Top 5로 올라감')))))));

/* ---------- D. 롤업 ---------- */
const cm = 'month.chart';
const polys = [0, 1, 2].map(function (k) { return h('polyline', { points: '{{' + cm + '.pts' + k + '}}', style: 'fill:none; stroke:var(--s' + (k + 1) + '); stroke-width:2; stroke-linejoin:round; stroke-linecap:round' }); });
const hovDots = [0, 1, 2].map(function (k) { return h('circle', { cx: '{{' + cm + '.hx}}', cy: '{{' + cm + '.hy' + k + '}}', r: '4', opacity: '{{' + cm + '.hop}}', style: 'fill:var(--s' + (k + 1) + '); stroke:var(--surface-1); stroke-width:2' }); });
const endMarks = [0, 1, 2].map(function (k) {
  return [
    h('circle', { cx: '{{' + cm + '.ex' + k + '}}', cy: '{{' + cm + '.ey' + k + '}}', r: '4', style: 'fill:var(--s' + (k + 1) + '); stroke:var(--surface-1); stroke-width:2' }),
    h('line', { x1: '{{' + cm + '.k1' + k + '}}', x2: '{{' + cm + '.k2' + k + '}}', y1: '{{' + cm + '.ey' + k + '}}', y2: '{{' + cm + '.ey' + k + '}}', style: 'stroke:var(--s' + (k + 1) + '); stroke-width:2; stroke-linecap:round' }),
    h('text', { x: '{{' + cm + '.tx' + k + '}}', y: '{{' + cm + '.ey' + k + '}}', dy: '4', 'font-size': '12', style: 'fill:var(--text-primary); font-weight:600' }, '{{' + cm + '.lab' + k + '}}')];
});
const grid = function (yk, lbl) {
  return [h('line', { x1: '{{' + cm + '.gx1}}', x2: '{{' + cm + '.gx2}}', y1: '{{' + cm + '.' + yk + '}}', y2: '{{' + cm + '.' + yk + '}}', style: 'stroke:' + (yk === 'g0' ? 'var(--axis)' : 'var(--grid)') + '; stroke-width:1' }),
    h('text', { x: '{{' + cm + '.yl}}', y: '{{' + cm + '.' + yk + '}}', dy: '4', 'text-anchor': 'end', 'font-size': '11', style: 'fill:var(--text-secondary)' }, lbl)];
};
const xt = [0, 1, 2, 3, 4].map(function (i) { return h('text', { x: '{{' + cm + '.t' + i + 'x}}', y: '{{' + cm + '.tickY}}', 'text-anchor': i === 0 ? 'start' : i === 4 ? 'end' : 'middle', 'font-size': '11', style: 'fill:var(--text-secondary)' }, '{{' + cm + '.t' + i + '}}'); });
const lineSvg = h.apply(null, ['svg', { viewBox: '0 0 640 250', role: 'img', 'aria-label': '{{' + cm + '.aria}}', style: 'display:block; width:100%; height:auto' }]
  .concat(grid('g100', '100'), grid('g50', '50'), grid('g0', '0'), polys,
    [h('line', { x1: '{{' + cm + '.hx}}', x2: '{{' + cm + '.hx}}', y1: '{{' + cm + '.ytop}}', y2: '{{' + cm + '.ybot}}', opacity: '{{' + cm + '.hop}}', style: 'stroke:var(--axis); stroke-width:1' })],
    hovDots, endMarks[0], endMarks[1], endMarks[2], xt));
const chartBox = h('div', { style: 'overflow-x:auto' },
  h('div', { style: 'position:relative; min-width:560px' },
    lineSvg,
    h('div', { style: 'position:absolute; top:0; right:0; bottom:0; left:0; touch-action:pan-y; cursor:crosshair', onPointerMove: '{{' + cm + '.onMove}}', onPointerLeave: '{{' + cm + '.onLeave}}' }),
    ifv(cm + '.hasHover', h('div', { style: 'position:absolute; top:6px; left:{{' + cm + '.tipLeft}}; transform:{{' + cm + '.tipTf}}; background:var(--surface-1); border:1px solid var(--axis); border-radius:8px; padding:8px 10px; pointer-events:none; min-width:140px; z-index:2; display:flex; flex-direction:column; gap:4px' },
      h('div', { style: S.lblB }, '{{' + cm + '.tipDay}}'),
      forv(cm + '.tipRows', 't', 3,
        h('div', { style: 'display:flex; align-items:center; gap:8px' }, key('{{t.c}}'), h('span', { style: 'font-size:14px; font-weight:700' }, '{{t.v}}'), h('span', { style: S.lbl }, '{{t.n}}')))))));
const tableView = h('details', {},
  h('summary', { style: 'cursor:pointer; list-style:none; display:block' }, h('span', { style: 'display:flex; align-items:center; gap:8px; min-height:44px' }, h('span', { class: 'chev', 'aria-hidden': 'true' }), h('span', { style: 'font-size:14px; font-weight:600' }, '표로 보기 (28일 값)'))),
  h('div', { style: 'max-height:260px; overflow:auto; border:1px solid var(--grid); border-radius:8px; font-size:13px; font-variant-numeric:tabular-nums' },
    h('div', { style: 'display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:4px; padding:6px 10px; font-weight:600; border-bottom:1px solid var(--grid); background:var(--chip-bg)' },
      h('span', {}, '날짜'), h('span', {}, 'Hacker News'), h('span', {}, 'GitHub'), h('span', {}, 'YouTube')),
    forv(cm + '.table', 'q', 6,
      h('div', { style: 'display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:4px; padding:5px 10px; border-bottom:1px solid var(--grid)' },
        h('span', {}, '{{q.d}}'), h('span', {}, '{{q.a}}'), h('span', {}, '{{q.b}}'), h('span', {}, '{{q.c}}')))));
const panelDay = h('div', { style: S.card },
  h('div', { style: 'display:flex; flex-direction:column; gap:2px' }, h('h3', { style: 'font-size:17px; font-weight:700; line-height:1.35' }, '일 · 어제와 비교'), h('p', { style: S.lbl }, '어제와 오늘 순위를 같은 점수식으로 계산해 비교해요. 점수순 표라서 Top 5의 탐색 칸은 들어 있지 않아요.')),
  forv('dayLines', 'd', 3, h('div', { style: 'display:flex; flex-direction:column; gap:2px' }, h('span', { style: S.lbl }, '{{d.l}}'), h('span', Object.assign({ style: 'font-size:14px; line-height:1.55; font-weight:600' }, tagd('rollup_day.rank_change', '계산')), '{{d.v}}'))));
const panelWeek = h('div', { style: S.card },
  h('div', { style: 'display:flex; flex-direction:column; gap:2px' }, h('h3', { style: 'font-size:17px; font-weight:700; line-height:1.35' }, '주 · 지속, 신규, 이탈'), h('p', { style: S.lbl }, '최근 7일 중 점수 상위 4에 든 날 수')),
  ifv('hasRoll',
    h('div', { style: 'display:flex; flex-direction:column; gap:8px' },
      forv('week.bars', 'b', 6,
        h('div', { style: 'display:grid; grid-template-columns:minmax(0,1.3fr) minmax(0,1fr) 44px; gap:8px; align-items:center' },
          h('span', { style: 'font-size:13px; line-height:1.4; overflow-wrap:anywhere' }, '{{b.n}}'),
          h('div', { 'aria-hidden': 'true', style: 'height:8px' }, h('div', { style: 'height:8px; width:{{b.pct}}; background:var(--s1); border-radius:0 4px 4px 0' })),
          h('span', Object.assign({ style: 'font-size:12px; font-variant-numeric:tabular-nums; text-align:right' }, tagd('rollup_week.days_in_top', '계산')), '{{b.c}}')))),
    h('div', { style: 'display:flex; flex-direction:column; gap:2px' }, h('span', { style: S.lbl }, '이번 주 처음 등장한 상위 주제'), h('span', { style: 'font-size:14px; line-height:1.55; font-weight:600' }, '{{week.newTxt}}')),
    h('div', { style: 'display:flex; flex-direction:column; gap:2px' }, h('span', { style: S.lbl }, '이번 주 상위 4에 들었다가 빠진 주제'), h('span', { style: 'font-size:14px; line-height:1.55; font-weight:600' }, '{{week.goneTxt}}'))),
  ifv('noRoll', h('p', { style: 'font-size:14px; line-height:1.6' }, '집계 3일차라 아직 안 보여요. 주간은 7일, 월간은 28일이 쌓이면 켜져요.')));
const panelMonth = h('div', { style: S.card },
  h('div', { style: 'display:flex; flex-direction:column; gap:2px' }, h('h3', { style: 'font-size:17px; font-weight:700; line-height:1.35' }, '월 · 한 주제의 수명 곡선과 플랫폼 간 시차'), h('p', { style: S.lbl }, '예: 소형 추론 모델 증류 (플랫폼별 최대치를 100으로 맞춘 28일 곡선)')),
  ifv('hasRoll',
    h('p', Object.assign({ style: 'font-size:14px; line-height:1.65; font-weight:600' }, tagd('rollup_month.lead_lag', '계산')), '{{month.lead}}'),
    h('div', { style: 'display:flex; flex-wrap:wrap; gap:6px 16px' },
      forv('month.legend', 'g', 3, h('span', { style: 'display:inline-flex; align-items:center; gap:6px; font-size:12px; color:var(--text-secondary)' }, key('{{g.c}}'), '{{g.n}}'))),
    chartBox,
    h('p', { style: S.lbl }, '{{month.lag}}'),
    tableView),
  ifv('noRoll', h('p', { style: 'font-size:14px; line-height:1.6' }, '집계 3일차라 아직 안 보여요. 월간 곡선은 28일이 쌓이면 켜져요.')));
const secD = sec('롤업', '같은 데이터를 일·주·월 단위로 다시 본 화면이에요.',
  h('div', { style: 'display:grid; grid-template-columns:repeat(auto-fit, minmax(min(360px,100%), 1fr)); gap:16px; align-items:start' }, panelDay, panelWeek),
  panelMonth);

/* ---------- E. 수집 상태 · 오늘의 실행 ---------- */
const cols = 'minmax(180px,1.5fr) minmax(100px,.8fr) 64px 64px 110px minmax(220px,2.6fr)';
const okI = h('svg', { width: '16', height: '16', viewBox: '0 0 16 16', 'aria-hidden': 'true', style: 'flex:0 0 auto' }, h('circle', { cx: '8', cy: '8', r: '7', style: 'fill:var(--good)' }), h('path', { d: 'M4.8 8.2l2.3 2.3 4-4.6', style: 'fill:none; stroke:#ffffff; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round' }));
const warnI = h('svg', { width: '16', height: '16', viewBox: '0 0 16 16', 'aria-hidden': 'true', style: 'flex:0 0 auto' }, h('path', { d: 'M8 1.8L15 14H1Z', style: 'fill:var(--warn); stroke:var(--text-primary); stroke-width:1.2; stroke-linejoin:round' }), h('path', { d: 'M8 6.4v3.4M8 11.6v.4', style: 'fill:none; stroke:var(--text-primary); stroke-width:1.6; stroke-linecap:round' }));
const noneI = h('svg', { width: '16', height: '16', viewBox: '0 0 16 16', 'aria-hidden': 'true', style: 'flex:0 0 auto' }, h('circle', { cx: '8', cy: '8', r: '6.5', style: 'fill:none; stroke:var(--text-secondary); stroke-width:1.4' }), h('path', { d: 'M5 8h6', style: 'fill:none; stroke:var(--text-secondary); stroke-width:1.6; stroke-linecap:round' }));
const hdrCell = function (t) { return h('span', { style: S.lblB }, t); };
const statusTable = h('div', { style: 'overflow-x:auto' },
  h('div', { style: 'min-width:760px; display:flex; flex-direction:column' },
    h('div', { style: 'display:grid; grid-template-columns:' + cols + '; gap:12px; padding:6px 0; border-bottom:1px solid var(--grid)' }, hdrCell('소스'), hdrCell('분야'), hdrCell('수집'), hdrCell('가중치'), hdrCell('상태'), hdrCell('비고')),
    forv('srcRows', 's', 7,
      h('div', { style: 'display:grid; grid-template-columns:' + cols + '; gap:12px; padding:10px 0; border-bottom:1px solid var(--grid); align-items:start; font-size:13px; line-height:1.5' },
        h('span', { style: 'display:flex; align-items:center; gap:8px; font-weight:600' }, ifv('s.hasPc', dot('{{s.pc}}')), ifv('s.noPc', h('span', { class: 'dot hollow' })), '{{s.n}}'),
        h('span', { style: 'color:var(--text-secondary)' }, '{{s.fd}}'),
        h('span', Object.assign({ style: 'font-variant-numeric:tabular-nums' }, tagd('source_runs.item_count', '수집')), '{{s.c}}'),
        h('span', Object.assign({ style: 'font-variant-numeric:tabular-nums' }, tagd('sources.weight', '계산')), '{{s.w}}'),
        h('span', Object.assign({ style: 'display:inline-flex; align-items:center; gap:6px; font-weight:600' }, tagd('source_runs.status', '계산')),
          ifv('s.isOk', okI), ifv('s.isWarn', warnI), ifv('s.isNone', noneI), '{{s.sl}}'),
        h('span', { style: 'color:var(--text-secondary)' }, '{{s.note}}')))));
const pipeRow = h('div', { style: 'display:flex; flex-wrap:wrap; align-items:stretch; gap:8px' },
  forv('pipe', 'p', 6,
    h('div', { style: 'display:flex; align-items:center; gap:8px' },
      h('div', { style: S.stat },
        h('span', { style: S.lbl }, '{{p.l}}'),
        h('span', { style: 'font-size:14px; font-weight:600; line-height:1.45', 'data-f': '{{p.f}}', 'data-k': '{{p.k}}' }, '{{p.v}}')),
      ifv('p.arrow', h('span', { 'aria-hidden': 'true', style: 'color:var(--text-secondary)' }, '→')))));
const execList = h('div', { style: 'display:flex; flex-direction:column; gap:8px' },
  forv('exec', 'x', 5, h('div', { style: 'display:flex; flex-wrap:wrap; gap:2px 12px' }, h('span', { style: S.lblB + '; flex:0 0 120px' }, '{{x.l}}'), h('span', { style: 'flex:1 1 260px; font-size:13px; line-height:1.6; min-width:0' }, '{{x.v}}'))));
const secE = sec('수집 상태와 오늘의 실행', '소스마다 오늘 몇 건을 가져왔는지, 막힌 곳은 없는지 보여줘요. 빈 슬롯은 같은 카드 형식으로 나중에 연결해요.',
  h('div', { style: S.card },
    h('div', { style: 'display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 12px' }, h('h3', { style: 'font-size:17px; font-weight:700' }, '소스 상태'), h('span', { style: S.lbl }, '{{warnLine}}')),
    statusTable),
  h('div', { style: S.card }, h('h3', { style: 'font-size:17px; font-weight:700' }, '오늘의 파이프라인'), pipeRow, execList));

const footer = h('footer', { style: 'display:flex; flex-direction:column; gap:6px; padding-top:12px; border-top:1px solid var(--grid)' },
  h('p', { style: 'font-size:14px; font-weight:700' }, '주목도 ≠ 중요도'),
  h('p', { style: S.sub }, '많이 올라온 것과 알아야 할 것은 달라요. 이 피드는 "요즘 어디를 보고 있나"를 보여줄 뿐이에요.'),
  h('p', { style: S.sub }, '{{consts}} — 모두 시작값이에요. 2주쯤 쓰면서 "몰랐는데 흥미로움" 비율을 보고 다시 맞춰요.'));

const root = h('div', { class: 'viz-root', 'data-fields': '{{fieldsAttr}}', style: 'min-height:100vh; padding:24px 16px 72px' },
  h('div', { style: 'max-width:1120px; margin:0 auto; display:flex; flex-direction:column; gap:36px' }, header, secA, secB, secC, secD, secE, footer));

/* ---------- 헬멧 CSS ---------- */
const CSS = `
body{margin:0}
sc-for,sc-if{display:contents}
.viz-root{color-scheme:light;--plane:#f9f9f7;--surface-1:#fcfcfb;--text-primary:#0b0b0b;--text-secondary:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--chip-bg:#f0efec;--band:rgba(42,120,214,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#6250d6;--good:#0ca30c;--warn:#fab219;--tag-bg:#f0efec;--tag-bd:#c3c2b7;--on-ink:#fcfcfb;font-family:system-ui,-apple-system,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",sans-serif;font-size:14px;line-height:1.5;background:var(--plane);color:var(--text-primary);-webkit-text-size-adjust:100%}
@media (prefers-color-scheme:dark){.viz-root{color-scheme:dark;--plane:#0d0d0d;--surface-1:#1a1a19;--text-primary:#f0efec;--text-secondary:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--chip-bg:#2c2c2a;--band:rgba(57,135,229,.18);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#0ca30c;--s7:#9085e9;--tag-bg:#2c2c2a;--tag-bd:#383835;--on-ink:#1a1a19}}
.viz-root *{box-sizing:border-box}
.viz-root h1,.viz-root h2,.viz-root h3,.viz-root p,.viz-root figure{margin:0}
.viz-root .dot{display:inline-block;width:8px;height:8px;border-radius:50%;flex:0 0 auto;background:var(--muted)}
.viz-root .dot.hollow{background:transparent;border:1.5px solid var(--text-secondary)}
.viz-root .dot[data-p="HN"],.viz-root .key[data-p="HN"]{background:var(--s1)}
.viz-root .dot[data-p="GH"],.viz-root .key[data-p="GH"]{background:var(--s2)}
.viz-root .dot[data-p="YT"],.viz-root .key[data-p="YT"]{background:var(--s3)}
.viz-root .dot[data-p="HF"],.viz-root .key[data-p="HF"]{background:var(--s4)}
.viz-root .dot[data-p="GN"],.viz-root .key[data-p="GN"]{background:var(--s5)}
.viz-root .dot[data-p="WK"],.viz-root .key[data-p="WK"]{background:var(--s6)}
.viz-root .dot[data-p="IG"],.viz-root .key[data-p="IG"]{background:var(--s7)}
.viz-root .key{display:inline-block;width:14px;height:2px;border-radius:1px;flex:0 0 auto;background:var(--muted)}
.viz-root .btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;padding:0 16px;border-radius:10px;border:1px solid var(--axis);background:var(--surface-1);color:var(--text-primary);font:inherit;font-size:14px;line-height:1.2;cursor:pointer}
.viz-root .btn:hover{background:var(--chip-bg)}
.viz-root .btn[aria-pressed="true"]{background:var(--text-primary);color:var(--surface-1);border-color:var(--text-primary)}
.viz-root .btn:focus-visible,.viz-root summary:focus-visible{outline:2px solid var(--s1);outline-offset:2px}
.viz-root summary::-webkit-details-marker{display:none}
.viz-root .chev{width:7px;height:7px;border-right:2px solid var(--text-secondary);border-bottom:2px solid var(--text-secondary);transform:rotate(-45deg);flex:0 0 auto;margin:0 4px 0 2px}
.viz-root details[open]>summary .chev{transform:rotate(45deg)}
.viz-root [data-f]::after{display:none}
.viz-root[data-fields="on"] [data-f]::after{display:inline-block;content:attr(data-f) " · " attr(data-k);margin-left:6px;padding:0 6px;border-radius:4px;font:600 11px/1.7 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--text-primary);background:var(--tag-bg);border:1px solid var(--tag-bd);vertical-align:middle;white-space:nowrap;font-style:normal;letter-spacing:0}
.viz-root[data-fields="on"] [data-k="LLM"]::after{background:var(--text-primary);color:var(--on-ink);border-color:var(--text-primary)}
`;

/* ---------- 조립 ---------- */
function assemble() {
  const comp = 'const __feed = (function () {\n' + LOGIC + '\nreturn { makeVals: makeVals, DATA: DATA };\n})();\n' +
    'class Component extends DCLogic {\n  renderVals() {\n    var self = this;\n    return __feed.makeVals(this.state || {}, function (p) { self.setState(p); });\n  }\n}\n';
  return '<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n<title>오늘의 유행 피드 (샘플)</title>\n<script src="./support.js"></script>\n</head>\n<body>\n<x-dc>\n<helmet>\n<style>' + CSS + '</style>\n</helmet>\n' +
    ser(root) + '\n</x-dc>\n<script type="text/x-dc" data-dc-script data-props=\'{"$preview":{"width":1280,"height":8000}}\'>\n' + comp + '</script>\n</body>\n</html>\n';
}

/* ---------- 실행: 검사 + 출력 ---------- */
const ctx = { console: console, Math: Math, Object: Object, JSON: JSON };
vm.createContext(ctx);
vm.runInContext('var __feed = (function(){\n' + LOGIC + '\nreturn { makeVals: makeVals, DATA: DATA };\n})();', ctx);
const variants = [
  {}, { mode: 'mature' }, { mode: 'early' }, { mode: 'early', fields: true, hov: 5 }, { mode: 'mature', fields: true, hov: 12, liked: { 'T-0731': true, 'T-0733': true } }, { mode: 'mature', hov: 27 }, { mode: 'mature', hov: 0 }
];
let bad = 0;
variants.forEach(function (st, i) {
  const vals = vm.runInContext('__feed.makeVals(' + JSON.stringify(st) + ', function(){})', ctx);
  const errs = []; check(root, vals, errs, 'root');
  const real = errs.filter(function (e) { return e.indexOf('(warn)') !== 0; });
  const warns = errs.filter(function (e) { return e.indexOf('(warn)') === 0; });
  if (real.length) { bad += real.length; console.log('variant', i, 'ERRORS:\n  ' + Array.from(new Set(real)).join('\n  ')); }
  if (warns.length) console.log('variant', i, Array.from(new Set(warns)).join(' | '));
});
const out = assemble();
const dir = path.join(__dirname, 'out', 'project'); fs.mkdirSync(dir, { recursive: true });
fs.writeFileSync(path.join(dir, 'Main.dc.html'), out);
console.log('bad holes:', bad, '· bytes:', out.length, '· undefined in html:', /undefined|NaN/.test(out));

/* ---------- 내장 스크립트를 그대로 꺼내 가짜 DCLogic으로 돌려 보기 (내 코드의 단위 시험) ---------- */
(function () {
  const m = out.match(/<script type="text\/x-dc" data-dc-script[^>]*>([\s\S]*?)<\/script>/);
  if (!m) { console.log('script block NOT found'); process.exit(1); }
  const c2 = { console: console, Math: Math, Object: Object, JSON: JSON };
  vm.createContext(c2);
  vm.runInContext('class DCLogic { constructor(){ this.props = {}; this.state = null; this.calls = []; } setState(p){ this.calls.push(p); this.state = Object.assign({}, this.state || {}, p); } }\n' + m[1] + '\nvar __C = Component;', c2);
  const inst = vm.runInContext('new __C()', c2);
  const v0 = inst.renderVals();
  const tog = v0.top5[0].toggle; tog();
  const v1 = inst.renderVals();
  inst.setState({ hov: 3 });
  const v2 = inst.renderVals();
  v2.month.chart.onMove({ currentTarget: { getBoundingClientRect: function () { return { left: 10, width: 640 }; } }, clientX: 330 });
  const v3 = inst.renderVals();
  v3.month.chart.onLeave();
  const v4 = inst.renderVals();
  v4.setEarly(); const v5 = inst.renderVals(); v5.toggleFields(); const v6 = inst.renderVals();
  console.log('runtime: liked after toggle =', v1.top5[0].likedStr, '| hover tip =', v3.month.chart.hasHover, v3.month.chart.tipDay, '| after leave =', v4.month.chart.hasHover, '| early =', v5.isEarly, v5.top5[0].label, '| fields attr =', v6.fieldsAttr);
})();
