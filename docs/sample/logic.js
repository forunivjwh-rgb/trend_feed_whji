'use strict';
/* ===== 샘플 데이터 + 공식 (페이지 안에서 그대로 계산돼요) ===== */
var K = { EPS: 0.8, ZCAP: 8, W_ACC: 1.5, W_PLAT: 0.5, TH: 5.0, ORIG_MIN: 3, BUDGET: 90, MPR: 2.6 };
var PL = { HN: 'Hacker News', GH: 'GitHub', YT: 'YouTube', HF: 'Hugging Face', GN: 'GeekNews', WK: 'Wikipedia', IG: 'Instagram' };
var FIELDS = [
  { k: 'dev', n: '개발·OSS', src: 'Hacker News · GitHub trending' },
  { k: 'ai', n: 'AI', src: 'Hugging Face trending (GitHub·HN과 교차)' },
  { k: 'kr', n: '한국 IT', src: 'GeekNews RSS (표결이 없어 등장 빈도로 계산)' },
  { k: 'cul', n: '문화·시사·밈', src: 'Wikipedia 조회수 (ko·en)' },
  { k: 'vid', n: '영상·숏폼', src: 'YouTube 인기 차트 · Instagram Reels 오디오 (낮은 가중치)' }
];

function mulberry32(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; var t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function median(a) { var s = a.slice().sort(function (x, y) { return x - y; }), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; }
function mad(a) { var m = median(a); return median(a.map(function (v) { return Math.abs(v - m); })); }
function mean(a) { return a.reduce(function (x, y) { return x + y; }, 0) / a.length; }
function f1(n) { return (Math.round(n * 10) / 10).toFixed(1); }
function sgm(z) { return (z < 0 ? '−' : '+') + f1(Math.abs(z)) + 'σ'; }
function fx(a) { return '×' + f1(a); }
function fpct(x) { return (x >= 0 ? '+' : '−') + Math.round(Math.abs(x) * 100) + '%'; }
function commas(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ','); }

/* 키프레임(날짜 인덱스, 값)을 이어서 28일 어텐션을 만든 뒤 잔잔한 잡음을 얹어요 (27 = 오늘) */
function series(kf, seed, nz) {
  var r = mulberry32(seed), out = [];
  for (var d = 0; d < 28; d++) {
    var a = r(), b = r(), v = 0;
    if (d >= kf[0][0]) {
      var i = 0;
      while (i < kf.length - 1 && kf[i + 1][0] <= d) i++;
      if (i === kf.length - 1) v = kf[i][1];
      else { var p = kf[i], q = kf[i + 1]; v = p[1] + (q[1] - p[1]) * (d - p[0]) / (q[0] - p[0]); }
      v = Math.max(0.05, v * (1 + nz * (a * 2 - 1)) + 0.1 * (b * 2 - 1));
    }
    out.push(Math.round(v * 100) / 100);
  }
  return out;
}
function firstIdx(s) { for (var i = 0; i < s.length; i++) if (s[i] > 0) return i; return -1; }

/* 7단계 로직의 5번: 견고한 z + 3일/14일 가속 + 폭 */
function statsAt(s, t) {
  var base = s.slice(Math.max(0, t - 27), t);
  var med = median(base), sg = 1.4826 * mad(base);
  var z = (s[t] - med) / (sg + K.EPS);
  var a3 = mean(s.slice(t - 2, t + 1)), a14 = mean(s.slice(Math.max(0, t - 13), t + 1));
  return { A: s[t], med: med, sg: sg, z: z, accel: a14 > 0 ? a3 / a14 : 1 };
}
function scoreOf(st, P) { return Math.min(Math.max(st.z, 0), K.ZCAP) + K.W_ACC * Math.log(Math.max(st.accel, 1)) + K.W_PLAT * (P - 1); }

/* ---------- 주제 16개 (가상) ---------- */
var TOP = [
  { id: 'T-0731', f: 'dev', sn: '마이크로 샌드박스', name: '에이전트 코드 실행용 마이크로 샌드박스', kw: ['sandbox', 'microvm', 'agent-runtime', 'wasm'], pl: ['HN', 'GH', 'GN', 'YT'], og: 7, sd: 11, kf: [[23, 1.4], [24, 3.2], [25, 4.6], [26, 5.4], [27, 6.0]],
    why: 'Hacker News 글이 먼저 올라오고, 같은 이틀 안에 GitHub 저장소 3곳이 별을 모았어요. 뒤이어 GeekNews와 영상 2건이 붙었어요.',
    whyE: 'Hacker News 글이 먼저 올라오고, 같은 이틀 안에 GitHub 저장소 3곳이 별을 모았어요. 뒤이어 GeekNews와 영상 2건이 붙었어요.',
    ev: [
      { r: '대표', p: 'GH', o: 'mirebox 조직', t: 'mirebox/mirebox — 에이전트용 마이크로VM 샌드박스', m: '★ 6.4k (+1.1k/일) · 포크 310', a: '등록 9일 전' },
      { r: '발단', p: 'HN', o: 'mirebox.dev', t: 'Show HN: Mirebox – 50ms 콜드스타트 샌드박스', m: '▲ 612 · 댓글 241', a: '4일 전' },
      { r: '최다 논의', p: 'HN', o: 'lowbit 블로그', t: '컨테이너 대신 마이크로VM을 직접 만든 이유', m: '▲ 388 · 댓글 402', a: '2일 전' }
    ],
    deep: { kind: '레포 + HN 스레드', rd: 3, b: [
      ['무엇', '에이전트가 만든 코드를 격리해서 실행하는 마이크로VM 기반 런타임이에요. README 기준 콜드스타트는 약 50ms이고 호스트 파일 접근은 기본 차단이에요.'],
      ['왜 나왔나', '컨테이너는 기동이 느리고 설정이 무겁다는 불만이 이슈 12건 중 7건이에요. 에이전트가 도구를 호출할 때마다 새 샌드박스를 띄우려는 수요가 배경이에요.'],
      ['어떻게 쓰이나', 'SDK로 코드와 입력 파일을 보내면 실행 결과와 생성 파일만 돌려받아요. 예제 대부분이 에이전트 도구 호출용이에요.']],
      c: '댓글 상위 20개: 호스트 커널을 공유하는지, 보안 경계를 얼마나 믿을 수 있는지가 가장 큰 논점이에요. 기존 컨테이너 격리로 충분하다는 반론도 있어요.',
      sc: 'README 1 · 이슈 12 · HN 댓글 상위 20' } },
  { id: 'T-0702', f: 'ai', sn: '소형 추론 모델 증류', name: '소형 추론 특화 모델 증류 열풍', kw: ['distill', 'reasoning', '3b', 'small-model'], pl: ['HF', 'GH', 'HN', 'YT'], og: 9, sd: 23, kf: [[3, 0.9], [10, 1.3], [20, 1.4], [21, 2.6], [22, 4.0], [23, 5.2], [24, 5.9], [25, 6.4], [26, 6.6], [27, 6.8]],
    why: '3주 넘게 낮은 수준이다가 6일 전 Hacker News 글을 계기로 Hugging Face 모델 5종과 GitHub 레시피 저장소 2곳이 잇따라 올라왔어요. 최근 3일은 영상이 붙으며 더 빨라졌어요.',
    whyE: 'Hacker News 글을 시작으로 Hugging Face 모델과 GitHub 레시피 저장소가 이어서 올라왔고, 영상도 붙기 시작했어요.',
    ev: [
      { r: '대표', p: 'HF', o: 'kestrel-lab 조직', t: 'kestrel-r1-3b — 3B 추론 특화 모델', m: '다운로드 18만 (+2.4만/일) · 좋아요 3.1k', a: '등록 5일 전' },
      { r: '발단', p: 'HN', o: '개인 블로그 (hhlee)', t: '3B 모델에 추론 과정을 증류하는 법: 되는 것과 안 되는 것', m: '▲ 740 · 댓글 188', a: '6일 전' },
      { r: '최다 논의', p: 'YT', o: '채널 코드와 칩', t: '3B 모델이 70B를 이긴다고? 직접 돌려봤다', m: '조회 41만 (+9만/일) · 댓글 3.2k', a: '2일 전' }
    ],
    deep: { kind: '영상 자막 + 모델 카드', rd: 3, b: [
      ['무엇', '큰 모델의 추론 과정을 3B급 소형 모델에 옮겨 담은 모델들이에요. 모델 카드마다 수학·코드 벤치 점수와 학습 레시피를 같이 공개해요.'],
      ['왜 나왔나', '큰 추론 모델은 비용이 부담스러워서예요. 14분짜리 영상 자막의 핵심 논거는 "노트북에서 돌아간다"예요.'],
      ['어떻게 쓰이나', '노트북·맥에서 양자화해 돌린 후기가 많아요. 레시피는 데이터 생성 → 필터링 → 학습 3단계예요.']],
      c: '영상 댓글 상위 20개: 벤치 점수가 과적합 아니냐는 의심과 "실사용은 다르다"는 반응이 가장 많아요.',
      sc: '영상 자막 14분 · 모델 카드 1 · HN 댓글 상위 20 · 영상 댓글 상위 20' } },
  { id: 'T-0728', f: 'vid', sn: '슬로우워크 챌린지', name: '슬로우워크 챌린지', kw: ['slowwalk', '챌린지', '숏폼', 'ost'], pl: ['IG', 'YT'], og: 12, sd: 37, kf: [[22, 0.8], [23, 1.6], [24, 2.8], [25, 3.9], [26, 4.7], [27, 5.2]],
    why: '릴스 오디오 사용 횟수가 5일 만에 약 2,100회에서 약 38,500회로 늘었어요. 같은 음원을 쓴 YouTube 쇼츠 8건이 인기 차트에 올라왔어요.',
    whyE: '릴스 오디오 사용 횟수가 하루 새 약 11,200회 늘었어요. 같은 음원을 쓴 YouTube 쇼츠 8건이 인기 차트에 올라왔어요.',
    ev: [
      { r: '대표', p: 'YT', o: '채널 하루한컷', t: '30초 슬로우워크 따라하기 (지하철편)', m: '조회 112만 (+34만/일)', a: '2일 전' },
      { r: '발단', p: 'IG', o: '릴스 오디오 · 원본 계정 1곳', t: 'slow walk (original audio)', m: '사용 ≈38,500회 (+11,200/일, 100단위 반올림)', a: '5일 전' },
      { r: '최다 논의', p: 'YT', o: '채널 뭐든리뷰', t: '이 걸음걸이 뭐예요? 슬로우워크 유래 정리', m: '댓글 2.9k · 조회 대비 댓글 비율 상위', a: '1일 전' }
    ],
    deep: { kind: '영상 자막·설명', rd: 3, b: [
      ['무엇', '한 걸음을 3초에 옮기는 슬로모션 걸음걸이를 따라 하는 숏폼이에요. 짧은 후크 음원과 정해진 동작을 묶은 포맷이에요.'],
      ['왜 나왔나', '첫 영상이 "3초에 한 걸음"이라는 규칙을 자막으로 못 박아서 누구나 같은 동작을 따라 하기 쉬웠어요.'],
      ['어떻게 쓰이나', '지하철·교실·마트처럼 장소만 바꿔 반복해요. 장소 이름이 제목에 붙는 영상이 많아요.']],
      c: '댓글 상위 20개: 따라 하기 인증이 대부분이고, 공공장소에서 방해가 된다는 지적이 일부 있어요.',
      sc: '영상 자막 3 · 설명란 3 · 댓글 상위 20' } },
  { id: 'T-0725', f: 'cul', sn: '새벽의 정류장 최종화', name: '드라마 〈새벽의 정류장〉 최종화 반향', kw: ['새벽의정류장', '최종화', '결말', '시청률'], pl: ['WK', 'YT', 'IG'], og: 8, sd: 41, kf: [[0, 2.1], [20, 2.3], [24, 2.4], [25, 3.1], [26, 6.2], [27, 6.9]],
    why: '최종화 방영 다음 날 위키 문서 조회가 평소의 약 11배로 뛰었고, 이틀 뒤 결말 해석 영상과 릴스 오디오가 이어졌어요.',
    whyE: '최종화 방영 다음 날 위키 문서 조회가 급증했고, 이틀 뒤 결말 해석 영상과 릴스 오디오가 이어졌어요.',
    ev: [
      { r: '대표', p: 'YT', o: '채널 영화로운 해석', t: '〈새벽의 정류장〉 결말 완전 해석 (떡밥 14개)', m: '조회 63만 (+21만/일)', a: '1일 전' },
      { r: '발단', p: 'WK', o: '위키백과 ko', t: '새벽의 정류장 (드라마)', m: '조회 4.2만/일 (평소 3.8천)', a: '2일 전' },
      { r: '최다 논의', p: 'YT', o: '채널 청춘다락', t: '최종화 같이 보며 울어요 (리액션)', m: '댓글 5.1k · 조회 29만', a: '1일 전' }
    ],
    deep: { kind: '위키 문서 + 영상 자막', rd: 3, b: [
      ['무엇', '16부작 드라마의 최종화가 방영된 뒤 결말과 복선을 다시 정리하는 흐름이에요.'],
      ['왜 나왔나', '열린 결말이라 해석이 갈려요. 위키 문서에 "결말" 항목이 하루 새 새로 생겼어요.'],
      ['어떻게 쓰이나', '해석 영상 → 리액션 영상 → 엔딩 OST 릴스 순서로 번졌어요.']],
      c: '댓글 상위 20개: 결말 해석이 둘로 갈리고, 후속 시즌을 바라는 반응이 많아요.',
      sc: '위키 문서 1 (ko) · 영상 자막 2 · 댓글 상위 20' } },
  { id: 'T-0733', f: 'vid', ex: true, sn: '보드게임 규칙 복원', name: '잊힌 보드게임 규칙 복원 프로젝트', kw: ['boardgame', 'rules', 'restoration', '1970s'], pl: ['GH', 'YT', 'WK'], og: 3, sd: 53, kf: [[24, 0.4], [25, 0.7], [26, 0.9], [27, 1.1]],
    why: 'GitHub 저장소 1곳, 영상 1건, 위키 문서 1건이 같은 사흘 안에 겹쳤어요. 수치는 낮지만 서로 다른 곳에서 같은 주제가 동시에 나타났어요.',
    whyE: 'GitHub 저장소 1곳, 영상 1건, 위키 문서 1건이 같은 사흘 안에 겹쳤어요. 수치는 낮지만 서로 다른 곳에서 같은 주제가 동시에 나타났어요.',
    note: '무작위 추첨으로 올라왔어요 · 관심 목록 밖 · 점수는 임계(5.0)에 못 미쳐요',
    ev: [
      { r: '대표', p: 'YT', o: '채널 주사위 한 줌', t: '50년 전 규칙서를 복원해서 해봤다', m: '조회 4.1만 · 구독자 대비 12배', a: '2일 전' },
      { r: '발단', p: 'GH', o: 'oldrules 조직', t: 'oldrules/lost-games — 절판 보드게임 규칙서 복원', m: '★ 340 (+210/일)', a: '3일 전' },
      { r: '최다 논의', p: 'WK', o: '위키백과 ko', t: '〈샌드위치 전쟁〉 (보드게임)', m: '조회 1.8만 (평소의 9배)', a: '1일 전' }
    ],
    deep: { kind: '레포 README + 영상 자막', rd: 2, b: [
      ['무엇', '절판된 옛 보드게임의 규칙서를 스캔하고 정리해서 현대어로 복원하는 오픈 저장소예요.'],
      ['왜 나왔나', '규칙서가 흩어져 있거나 번역본마다 달라서, 한곳에 정본을 만들려는 시도예요.'],
      ['어떻게 쓰이나', '복원한 규칙으로 직접 플레이한 영상이 나오고, 저장소에는 게임별 규칙과 카드 목록이 쌓여요.']],
      c: '댓글 상위 20개: 어릴 적 하던 게임이라는 반응과 저작권을 걱정하는 질문이 같이 달려요.',
      sc: 'README 1 · 영상 자막 1 · 댓글 상위 20' } },
  { id: 'T-0614', f: 'dev', sn: '로컬 우선 동기화', name: 'SQLite 로컬 우선 동기화 라이브러리 붐', kw: ['sqlite', 'local-first', 'sync', 'crdt'], pl: ['HN', 'GH', 'GN'], og: 6, sd: 61, kf: [[6, 1.0], [20, 1.1], [23, 1.4], [24, 2.2], [25, 3.1], [26, 3.9], [27, 4.4]],
    rep: { p: 'GH', t: 'tideline/tideline — 로컬 우선 동기화 엔진', m: '★ 2.9k (+310/일)' }, rd: 2,
    one: '로컬 DB를 진실의 원천으로 두고 서버와는 바뀐 부분만 맞추는 라이브러리 3종이 동시에 올라왔어요. 이슈의 절반이 "충돌 해결 규칙" 질문이에요.' },
  { id: 'T-0522', f: 'dev', sn: '러스트 터미널 UI', name: '러스트 터미널 UI 프레임워크 약진', kw: ['tui', 'terminal', 'rust-ui'], pl: ['GH', 'HN'], og: 3, sd: 67, kf: [[0, 3.0], [18, 3.1], [24, 3.4], [27, 3.9]],
    rep: { p: 'GH', t: 'glyphkit/glyphkit — 러스트 터미널 UI 툴킷', m: '★ 8.1k (+160/일)' } },
  { id: 'T-0719', f: 'ai', sn: '한국어 음성 합성', name: '한국어 음성 합성 경량 모델', kw: ['tts', 'korean', '600m', 'voice-clone'], pl: ['HF', 'GH', 'YT'], og: 5, sd: 71, kf: [[21, 0.5], [22, 0.9], [23, 1.3], [24, 1.7], [25, 2.1], [26, 2.4], [27, 2.7]],
    rep: { p: 'HF', t: 'sori-tts-0.6b — 한국어 음성 합성', m: '좋아요 1.8k (+420/일)' }, rd: 2,
    one: '0.6B급 한국어 음성 합성 모델이 공개됐어요. 소수 화자 음성 복제를 지원하고, 댓글 쟁점은 음성 도용 우려와 라이선스예요.' },
  { id: 'T-0655', f: 'ai', sn: '온디바이스 비전-언어', name: '온디바이스 비전-언어 모델', kw: ['vlm', 'on-device', 'quantization'], pl: ['HF', 'HN'], og: 4, sd: 73, kf: [[0, 1.6], [20, 1.7], [25, 2.3], [27, 2.9]],
    rep: { p: 'HF', t: 'pocketvl-2b — 온디바이스 비전-언어 모델', m: '다운로드 6.2만 (+0.8만/일)' } },
  { id: 'T-0690', f: 'kr', sn: '클라우드 장애 사후분석', name: '국내 클라우드 장애 사후분석 공개', kw: ['장애', '사후분석', '리전', '배포'], pl: ['GN', 'HN'], og: 5, sd: 79, kf: [[22, 0.5], [23, 1.0], [24, 1.8], [25, 2.4], [26, 2.8], [27, 2.6]],
    rep: { p: 'GN', t: '한빛클라우드 리전 장애 사후분석 공개', m: '등장 6회 · 출처 5곳' }, rd: 2,
    one: '한빛클라우드가 리전 장애 원인(설정 배포 오류)을 자세히 공개했어요. "공개 수준이 높다"는 평과 "재발 방지책이 약하다"는 지적이 갈려요.' },
  { id: 'T-0668', f: 'kr', sn: '채용시장 논쟁', name: '개발자 채용시장 위축 논쟁', kw: ['채용', '신입', '연봉', '감원'], pl: ['GN', 'YT'], og: 4, sd: 83, kf: [[0, 2.0], [24, 2.2], [27, 2.9]],
    rep: { p: 'GN', t: '신입 개발자 공고 집계를 둘러싼 논쟁', m: '등장 4회 · 출처 4곳' } },
  { id: 'T-0701', f: 'kr', sn: '앱마켓 수수료', name: '앱마켓 수수료 규제 후속 논의', kw: ['수수료', '규제', '앱마켓'], pl: ['GN', 'HN'], og: 3, sd: 89, kf: [[8, 1.2], [22, 1.3], [27, 2.1]],
    rep: { p: 'GN', t: '앱마켓 수수료 규정 개정안 해설', m: '등장 3회 · 출처 3곳' } },
  { id: 'T-0710', f: 'cul', sn: '거북이 라떼 밈', name: "'거북이 라떼' 밈 확산", kw: ['거북이라떼', '밈', '카페'], pl: ['IG', 'YT', 'WK'], og: 6, sd: 97, kf: [[19, 0.6], [20, 0.9], [22, 1.4], [24, 1.9], [26, 2.4], [27, 2.7]],
    rep: { p: 'YT', t: "'거북이 라떼' 유래 정리", m: '조회 18만 (+6만/일)' }, rd: 2,
    one: '카페 메뉴판 사진에 "거북이 라떼"를 끼워 넣는 합성 밈이에요. 위키 문서가 새로 생겼고 유래를 설명하는 영상이 올라왔어요.' },
  { id: 'T-0676', f: 'cul', sn: '오디션 결승', name: '오디션 프로그램 〈스테이지 제로〉 결승', kw: ['스테이지제로', '결승', '투표'], pl: ['WK', 'YT'], og: 3, sd: 101, kf: [[0, 2.4], [20, 2.5], [26, 3.0], [27, 3.2]],
    rep: { p: 'WK', t: 'Stage Zero (TV series)', m: '조회 2.4만/일 (평소의 3배)' } },
  { id: 'T-0694', f: 'vid', sn: '공방 ASMR', name: '공방 ASMR 브이로그', kw: ['공방', 'asmr', '목공'], pl: ['YT'], og: 5, sd: 103, kf: [[0, 2.6], [22, 2.7], [27, 3.3]],
    rep: { p: 'YT', t: '비 오는 날 공방 — 서랍 짜기 (ASMR)', m: '조회 24만 (+3만/일)' } },
  { id: 'T-0681', f: 'vid', sn: '영화 요약 쇼츠', name: '1분 영화 요약 쇼츠 포맷', kw: ['요약', '영화', '쇼츠'], pl: ['YT', 'IG'], og: 8, sd: 107, kf: [[4, 1.8], [20, 1.9], [27, 2.9]],
    rep: { p: 'YT', t: '3분 만에 보는 영화 한 편 — 요약 쇼츠 모음', m: '조회 77만 (+5만/일)' } }
];

/* 탐색 슬롯 풀 (점수와 무관하게 무작위로 뽑은 5건) */
var POOL = [
  { p: 'GH', t: 'oldrules/lost-games — 절판 보드게임 규칙서 복원', m: '★ 340 (+210/일)', up: true },
  { p: 'YT', t: '60년 된 타자기 리본을 직접 만들어 봤다', m: '조회 9.4만 · 구독자 대비 7배' },
  { p: 'WK', t: '수중 고고학 (ko)', m: '조회 1.1만 (평소의 6배)' },
  { p: 'HN', t: 'Show HN: 지하철 노선도 자동 정렬 도구', m: '▲ 87 · 댓글 31' },
  { p: 'HF', t: 'fieldnote-asr-small — 방언 음성 인식', m: '좋아요 120 (+40/일)' }
];

/* 월 롤업: 한 주제를 플랫폼별로 나눠 본 28일 곡선 (각 플랫폼 최대치 = 100) */
var LL = [
  { id: 'HN', kf: [[3, 6], [10, 8], [19, 9], [20, 30], [21, 72], [22, 100], [23, 86], [25, 58], [27, 44]], sd: 131 },
  { id: 'GH', kf: [[3, 3], [12, 4], [20, 6], [22, 24], [23, 55], [24, 82], [25, 100], [27, 86]], sd: 137 },
  { id: 'YT', kf: [[18, 2], [22, 5], [24, 26], [25, 52], [26, 78], [27, 100]], sd: 139 }
];

/* 수집 상태 (가상) */
var SRC = [
  { n: 'Hacker News', fd: '개발·OSS', c: 60, w: '1.0', s: 'ok', note: '인기글 60 · 댓글은 실탐 때만 읽어요', pc: 'HN' },
  { n: 'GitHub trending', fd: '개발·OSS', c: 75, w: '1.0', s: 'ok', note: '일간·주간 목록 합산', pc: 'GH' },
  { n: 'Hugging Face trending', fd: 'AI', c: 40, w: '1.0', s: 'ok', note: '모델 trending 상위 40', pc: 'HF' },
  { n: 'GeekNews RSS', fd: '한국 IT', c: 36, w: '1.0', s: 'warn', note: '항목 수가 평소의 40% — 피드 일부 누락이 의심돼요. 표결이 없어 등장 빈도로 계산해요', pc: 'GN' },
  { n: 'Wikipedia 조회수', fd: '문화·시사·밈', c: 200, w: '1.0', s: 'ok', note: 'ko·en 일간 상위 100씩', pc: 'WK' },
  { n: 'YouTube 인기 차트', fd: '영상·숏폼', c: 250, w: '1.0', s: 'ok', note: '5개 카테고리 · 무료 API 키로 일일 쿼터 안에서', pc: 'YT' },
  { n: 'Instagram Reels 오디오', fd: '영상·숏폼', c: 60, w: '0.3', s: 'ok', note: '7/10쪽 사용 (계정 보호 한도) · 사용 횟수는 100단위 반올림', pc: 'IG' },
  { n: 'Reddit', fd: '—', c: 0, w: '—', s: 'none', note: '슬롯만 있어요. 나중에 같은 카드 형식으로 연결해요', pc: '' },
  { n: 'X', fd: '—', c: 0, w: '—', s: 'none', note: '슬롯만 있어요', pc: '' },
  { n: 'LinkedIn', fd: '—', c: 0, w: '—', s: 'none', note: '슬롯만 있어요', pc: '' }
];

/* ---------- 계산 (한 번만) ---------- */
var _D = null;
function DATA() {
  if (_D) return _D;
  var T = TOP.map(function (t) {
    var s = series(t.kf, t.sd, 0.08), st = statsAt(s, 27), P = t.pl.length, fi = firstIdx(s), sc = scoreOf(st, P);
    return Object.assign({}, t, { s: s, st: st, P: P, old: fi === 0, seen: 27 - fi, score: sc,
      pass: !t.ex && t.og >= K.ORIG_MIN && sc >= K.TH, rankable: !t.ex && t.og >= K.ORIG_MIN });
  });
  var byId = {}; T.forEach(function (t) { byId[t.id] = t; });
  var rk = T.filter(function (t) { return t.rankable; });
  var byScore = rk.slice().sort(function (a, b) { return b.score - a.score; });
  var top4 = byScore.slice(0, 4);
  var ex = T.filter(function (t) { return t.ex; })[0];
  var passN = T.filter(function (t) { return t.pass; }).length;
  var deepSet = {}; T.forEach(function (t) { if (t.pass || t.ex) deepSet[t.id] = true; });
  var reads = 0; T.forEach(function (t) { if (deepSet[t.id]) reads += (t.deep ? t.deep.rd : t.rd || 2); });

  function rankingAt(d) {
    return rk.map(function (t) { return { id: t.id, v: scoreOf(statsAt(t.s, d), t.P) }; })
      .sort(function (a, b) { return b.v - a.v; }).map(function (o) { return o.id; });
  }
  var r0 = rankingAt(27), r1 = rankingAt(26);
  var wk = {}; for (var d = 21; d <= 27; d++) rankingAt(d).slice(0, 4).forEach(function (id) { wk[id] = (wk[id] || 0) + 1; });
  var gone = []; for (var d2 = 21; d2 <= 26; d2++) rankingAt(d2).slice(0, 4).forEach(function (id) { if (r0.slice(0, 4).indexOf(id) < 0 && gone.indexOf(id) < 0) gone.push(id); });

  /* 월 롤업 곡선 */
  var ll = LL.map(function (o) {
    var raw = series(o.kf, o.sd, 0.07), mx = Math.max.apply(null, raw);
    var v = raw.map(function (x) { return Math.round(x / mx * 1000) / 10; });
    var half = 0; for (var i = 0; i < v.length; i++) { if (v[i] >= 50) { half = i; break; } }
    return { id: o.id, v: v, half: half };
  });
  _D = { T: T, byId: byId, rk: rk, byScore: byScore, top4: top4, ex: ex, passN: passN, deepSet: deepSet, reads: reads, r0: r0, r1: r1, wk: wk, gone: gone, ll: ll };
  return _D;
}

/* ---------- 작은 그래프 좌표 ---------- */
function mkSpark(arr, band, o) {
  var n = arr.length, W = o.w, H = o.h;
  var top = Math.max.apply(null, arr.concat([band ? band.hi : 0, 1])) * 1.12;
  function X(i) { return o.pl + (W - o.pl - o.pr) * (n === 1 ? 0 : i / (n - 1)); }
  function Y(v) { return o.pt + (H - o.pt - o.pb) * (1 - v / top); }
  var pts = arr.map(function (v, i) { return X(i).toFixed(1) + ',' + Y(v).toFixed(1); }).join(' ');
  var lo = band ? Math.max(0, band.lo) : 0, hi = band ? band.hi : 0;
  return { pts: pts, bx: o.pl.toFixed(1), bw: (W - o.pl - o.pr).toFixed(1), by: Y(hi).toFixed(1), bh: Math.max(0, Y(lo) - Y(hi)).toFixed(1),
    my: Y(band ? band.med : 0).toFixed(1), lx: X(n - 1).toFixed(1), ly: Y(arr[n - 1]).toFixed(1),
    tx: (X(n - 1) + 9).toFixed(1), ty: (Y(arr[n - 1]) + 4).toFixed(1), lab: f1(arr[n - 1]),
    ax: o.pl.toFixed(1), ay: (H - 6).toFixed(1), bx2: (W - o.pr).toFixed(1) };
}
var SP_BIG = { w: 300, h: 108, pl: 6, pr: 44, pt: 12, pb: 26 };
var SP_SMALL = { w: 150, h: 40, pl: 4, pr: 10, pt: 6, pb: 6 };

/* ---------- 화면에 필요한 값 전부 ---------- */
function makeVals(st, set) {
  var D = DATA(), T = D.T;
  var early = st.mode === 'early', showF = !!st.fields, liked = st.liked || {};
  var hov = (st.hov === 0 || st.hov) ? st.hov : null;
  var days = early ? 3 : 31;

  function label(t) { return t.ex ? '탐색' : early ? '지금 인기' : (!t.old && t.seen <= 14 ? '신생' : '가속'); }
  function seenTxt(t) { return t.old ? '28일 이상 전' : t.seen + '일 전'; }
  function earlyCh(t) { var p = t.s[24]; return p > 0 ? fpct(t.s[27] / p - 1) : '신규'; }
  function metrics(t) {
    var z = t.st.z, capped = z >= K.ZCAP;
    if (early) return [
      { l: '오늘 어텐션', v: f1(t.st.A), f: 'topic_daily.attention', k: '계산' },
      { l: '3일 변화', v: earlyCh(t), f: 'topic_daily.attention', k: '계산' },
      { l: '출처 · 플랫폼', v: t.og + '곳 · ' + t.P + '개', f: 'topic_score.breadth', k: '계산' },
      { l: '3일 평균', v: f1(mean(t.s.slice(-3))), f: 'topic_daily.attention', k: '계산' }];
    return [
      { l: '평소 대비', v: sgm(Math.min(z, K.ZCAP)) + (capped ? ' (상한)' : ''), f: 'topic_score.z', k: '계산' },
      { l: '가속 (3일/14일)', v: fx(t.st.accel), f: 'topic_score.accel', k: '계산' },
      { l: '출처 · 플랫폼', v: t.og + '곳 · ' + t.P + '개', f: 'topic_score.breadth', k: '계산' },
      { l: '첫 등장', v: seenTxt(t), f: 'topics.first_seen', k: '계산' }];
  }
  function spark(t, o) {
    var arr = early ? t.s.slice(-3) : t.s;
    var band = early ? null : { med: t.st.med, lo: t.st.med - 2 * t.st.sg, hi: t.st.med + 2 * t.st.sg };
    var g = mkSpark(arr, band, o);
    g.op = early ? '0' : '1';
    g.l0 = early ? '2일 전' : '27일 전';
    g.aria = t.name + ' ' + (early ? '최근 3일' : '28일') + ' 어텐션 추이. 오늘 ' + f1(t.st.A) + (early ? '' : ', 평소 중앙값 ' + f1(t.st.med));
    return g;
  }
  function plats(t) { return t.pl.map(function (c) { return { c: c, n: PL[c] }; }); }
  function evs(t) { return t.ev.map(function (e) { return { r: e.r, c: e.p, p: PL[e.p], o: e.o, t: e.t, m: e.m, a: e.a }; }); }

  /* ---- A. Top 5 ---- */
  var order = early ? D.top4.slice().sort(function (a, b) { return b.st.A - a.st.A; }) : D.top4;
  var cards = order.concat([D.ex]).map(function (t, i) {
    var lb = label(t);
    return {
      id: t.id, rank: '#' + (i + 1), name: t.name, kw: t.kw.map(function (w) { return { w: w }; }), label: lb,
      isNew: lb === '신생', isAccel: lb === '가속', isEx: !!t.ex, isNow: lb === '지금 인기',
      scoreL: early ? '오늘 어텐션' : '점수', scoreV: early ? f1(t.st.A) : f1(t.score),
      metrics: metrics(t), why: early ? t.whyE : t.why, note: t.note || '',
      cap: early ? '최근 3일 어텐션 (기준선 없음)' : '28일 어텐션 · 음영 = 평소 범위 (중앙값 ±2σ)',
      sp: spark(t, SP_BIG), plats: plats(t), ev: evs(t),
      dk: t.deep.kind, drd: '읽기 ' + t.deep.rd + '건',
      db: t.deep.b.map(function (b) { return { h: b[0], t: b[1] }; }), dc: t.deep.c, dsc: t.deep.sc,
      open: i === 0,
      likedStr: liked[t.id] ? 'true' : 'false', isLiked: !!liked[t.id],
      toggle: (function (id) { return function () { var m = Object.assign({}, liked); m[id] = !m[id]; set({ liked: m }); }; })(t.id)
    };
  });
  var likedN = cards.filter(function (c) { return c.isLiked; }).length;
  var rankOf = {}; cards.forEach(function (c) { rankOf[c.id] = c.rank; });

  /* ---- B. 분야별 ---- */
  var fields = FIELDS.map(function (F) {
    var list = D.byScore.filter(function (t) { return t.f === F.k; });
    if (early) list = list.slice().sort(function (a, b) { return b.st.A - a.st.A; });
    var rows = list.slice(0, 3).map(function (t, i) {
      var deep = !!D.deepSet[t.id], rep = t.ev ? { p: t.ev[0].p, t: t.ev[0].t, m: t.ev[0].m } : t.rep;
      var one = t.deep ? (t.deep.b[0][1]) : (t.one || '');
      return {
        id: t.id, rank: String(i + 1), name: t.name, label: label(t), top5: rankOf[t.id] ? 'Top 5 ' + rankOf[t.id] : '', inTop5: !!rankOf[t.id],
        deep: deep, notDeep: !deep, one: one, hasOne: deep && !!(t.one),
        rc: rep.p, rp: PL[rep.p], rt: rep.t, rm: rep.m, plTxt: t.pl.map(function (c) { return PL[c]; }).join(' · '),
        n1l: early ? '오늘' : 'z', n1v: early ? f1(t.st.A) : sgm(Math.min(t.st.z, K.ZCAP)),
        n2l: early ? '3일 변화' : '가속', n2v: early ? earlyCh(t) : fx(t.st.accel),
        n3v: f1(t.score), n3l: '점수', showScore: !early, sp: spark(t, SP_SMALL)
      };
    });
    return { k: F.k, n: F.n, src: F.src, rows: rows };
  });

  /* ---- C. 탐색 슬롯 ---- */
  var pool = POOL.map(function (p) { return { c: p.p, p: PL[p.p], t: p.t, m: p.m, up: !!p.up }; });

  /* ---- D. 롤업 ---- */
  function sn(id) { return D.byId[id].sn; }
  var top5 = D.r0.slice(0, 5), y5 = D.r1.slice(0, 5);
  var entered = top5.filter(function (id) { return y5.indexOf(id) < 0; });
  var left = y5.filter(function (id) { return top5.indexOf(id) < 0; });
  var best = null;
  D.r0.slice(0, 8).forEach(function (id, i) { var j = D.r1.indexOf(id); if (j >= 0 && j - i > 0 && (!best || j - i > best.d)) best = { id: id, d: j - i, from: j + 1, to: i + 1 }; });
  function mv(id) { var a = D.r1.indexOf(id), b = D.r0.indexOf(id); return sn(id) + ' (어제 ' + (a >= 0 ? '#' + (a + 1) : '순위 밖') + ' → 오늘 ' + (b >= 0 ? '#' + (b + 1) : '순위 밖') + ')'; }
  var dayLines = [
    { l: '점수 순위 5위 안에 새로 든 주제', v: entered.length ? entered.map(mv).join(', ') : '없음' },
    { l: '점수 순위 5위 밖으로 나간 주제', v: left.length ? left.map(mv).join(', ') : '없음' },
    { l: '가장 많이 오른 주제', v: best ? sn(best.id) + ' ▲' + best.d + ' (어제 #' + best.from + ' → 오늘 #' + best.to + ')' : '없음' }];
  var wkIds = Object.keys(D.wk).sort(function (a, b) { return D.wk[b] - D.wk[a]; }).slice(0, 6);
  var wkBars = wkIds.map(function (id) { return { n: sn(id), pct: Math.round(D.wk[id] / 7 * 100) + '%', c: D.wk[id] + '/7일' }; });
  var newWk = D.r0.slice(0, 8).filter(function (id) { var t = D.byId[id]; return !t.old && t.seen <= 7; });
  var week = { bars: wkBars, newTxt: newWk.length ? newWk.map(sn).join(', ') : '없음', goneTxt: D.gone.length ? D.gone.map(sn).join(', ') : '없음' };

  /* 월: 선 그래프 */
  var CW = 640, CH = 250, cl = 40, cr = 118, ct = 14, cb = 32, pw = CW - cl - cr, ph = CH - ct - cb;
  function CX(i) { return cl + pw * i / 27; }
  function CY(v) { return ct + ph * (1 - v / 100); }
  var ch = { w: CW, h: CH, hasHover: hov !== null, hop: hov !== null ? '1' : '0' };
  D.ll.forEach(function (o, k) {
    ch['pts' + k] = o.v.map(function (v, i) { return CX(i).toFixed(1) + ',' + CY(v).toFixed(1); }).join(' ');
    var lastV = o.v[27];
    ch['ex' + k] = CX(27).toFixed(1); ch['ey' + k] = CY(lastV).toFixed(1);
    ch['k1' + k] = (CX(27) + 12).toFixed(1); ch['k2' + k] = (CX(27) + 26).toFixed(1); ch['tx' + k] = (CX(27) + 31).toFixed(1);
    ch['lab' + k] = PL[o.id] + ' ' + Math.round(lastV);
    var hi = hov !== null ? hov : 27;
    ch['hy' + k] = CY(o.v[hi]).toFixed(1);
  });
  ch.hx = CX(hov !== null ? hov : 27).toFixed(1);
  ch.g0 = CY(0).toFixed(1); ch.g50 = CY(50).toFixed(1); ch.g100 = CY(100).toFixed(1);
  ch.gx1 = cl; ch.gx2 = (CW - cr).toFixed(1); ch.yl = (cl - 8); ch.ytop = ct; ch.ybot = CH - cb;
  ch.ticks = [0, 7, 14, 21, 27].map(function (i) { return { x: CX(i).toFixed(1), t: i === 27 ? '오늘' : (27 - i) + '일 전' }; });
  ch.t0x = ch.ticks[0].x; ch.t1x = ch.ticks[1].x; ch.t2x = ch.ticks[2].x; ch.t3x = ch.ticks[3].x; ch.t4x = ch.ticks[4].x;
  ch.t0 = ch.ticks[0].t; ch.t1 = ch.ticks[1].t; ch.t2 = ch.ticks[2].t; ch.t3 = ch.ticks[3].t; ch.t4 = ch.ticks[4].t;
  ch.tickY = CH - 10;
  ch.aria = '소형 추론 모델 증류 주제의 플랫폼별 28일 반응 곡선. 각 플랫폼 최대치를 100으로 맞췄어요. Hacker News가 먼저 오르고 GitHub, YouTube 순으로 따라 올랐어요.';
  var tipIdx = hov !== null ? hov : 27;
  ch.tipLeft = (CX(tipIdx) / CW * 100).toFixed(1) + '%';
  ch.tipTf = tipIdx > 17 ? 'translateX(calc(-100% - 10px))' : 'translateX(10px)';
  ch.tipDay = tipIdx === 27 ? '오늘' : (27 - tipIdx) + '일 전';
  ch.tipRows = D.ll.map(function (o) { return { c: o.id, n: PL[o.id], v: String(Math.round(o.v[tipIdx])) }; });
  ch.table = []; for (var q = 27; q >= 0; q--) ch.table.push({ d: q === 27 ? '오늘' : (27 - q) + '일 전', a: Math.round(D.ll[0].v[q]) + '', b: Math.round(D.ll[1].v[q]) + '', c: Math.round(D.ll[2].v[q]) + '' });
  ch.onMove = function (e) {
    var r = e.currentTarget.getBoundingClientRect();
    var xv = (e.clientX - r.left) / r.width * CW;
    var i = Math.max(0, Math.min(27, Math.round((xv - cl) / pw * 27)));
    if (i !== hov) set({ hov: i });
  };
  ch.onLeave = function () { if (hov !== null) set({ hov: null }); };
  var h0 = D.ll[0].half, h1 = D.ll[1].half, h2 = D.ll[2].half;
  var month = { legend: D.ll.map(function (o) { return { c: o.id, n: PL[o.id] }; }), chart: ch, lead: PL.HN + '가 ' + (27 - h0) + '일 전에 먼저 올랐고, GitHub는 +' + (h1 - h0) + '일, YouTube는 +' + (h2 - h0) + '일 뒤에 따라 올랐어요.',
    lag: '반응 시점 = 각 플랫폼이 자기 최대치의 50%를 처음 넘은 날' };

  /* ---- E. 수집 상태 · 오늘의 실행 ---- */
  var itemsTotal = SRC.reduce(function (a, s) { return a + s.c; }, 0);
  var nSrc = SRC.filter(function (s) { return s.c > 0; }).length, nOk = SRC.filter(function (s) { return s.s === 'ok'; }).length;
  var warnN = SRC.filter(function (s) { return s.s === 'warn'; }).length;
  var deepN = D.passN + 1, minutes = Math.round(D.reads * K.MPR);
  var llmCalls = 1 + deepN + 1, tokIn = 6 + 6 * deepN + 3, tokOut = Math.round(1 + 0.4 * deepN + 1);
  var tot = 38 + 6 + minutes + 9 + 1, endMin = 240 + tot;
  var hhmm = function (m) { return ('0' + Math.floor(m / 60)).slice(-2) + ':' + ('0' + (m % 60)).slice(-2); };
  var rows = SRC.map(function (s) {
    return { n: s.n, fd: s.fd, c: s.c ? commas(s.c) : '—', w: s.w, isOk: s.s === 'ok', isWarn: s.s === 'warn', isNone: s.s === 'none',
      sl: s.s === 'ok' ? '정상' : s.s === 'warn' ? '주의' : '입력 없음', note: s.note, pc: s.pc, hasPc: !!s.pc, noPc: !s.pc };
  });
  var pipe = [
    { l: '수집', v: commas(itemsTotal) + '건', f: 'items', k: '수집' },
    { l: '주제', v: '164개', f: 'topics', k: '계산' },
    { l: '임계 통과', v: D.passN + '개', f: 'topic_score.score', k: '계산' },
    { l: '실탐 선정', v: deepN + '개 (탐색 1 포함)', f: 'deepreads', k: '계산' },
    { l: '원문 읽기', v: D.reads + '건', f: 'deepreads.scope', k: '실탐' },
    { l: 'LLM 요약', v: deepN + '건', f: 'deepreads.summary', k: 'LLM' }];
  pipe.forEach(function (p, i) { p.arrow = i < pipe.length - 1; });
  var runLine = '04:00 시작 → ' + hhmm(endMin) + ' 완료 · 총 ' + tot + '분 (샘플 기록)';
  var stats = early
    ? [{ l: '수집', v: commas(itemsTotal) + '건 · ' + nSrc + '개 소스', f: 'source_runs.item_count', k: '수집' },
       { l: '주제', v: '164개 · 기준선 없음', f: 'topics', k: '계산' },
       { l: '실탐', v: deepN + '개 주제 · 읽기 ' + D.reads + '건', f: 'deepreads', k: '실탐' },
       { l: 'LLM', v: llmCalls + '회 · 입력 ' + tokIn + 'K · 출력 ' + tokOut + 'K 토큰', f: 'llm_calls', k: '계산' }]
    : [{ l: '수집', v: commas(itemsTotal) + '건 · ' + nSrc + '개 소스', f: 'source_runs.item_count', k: '수집' },
       { l: '주제', v: '164개 → 임계 통과 ' + D.passN + '개', f: 'topic_score.score', k: '계산' },
       { l: '실탐', v: deepN + '개 주제 · 읽기 ' + D.reads + '건', f: 'deepreads', k: '실탐' },
       { l: 'LLM', v: llmCalls + '회 · 입력 ' + tokIn + 'K · 출력 ' + tokOut + 'K 토큰', f: 'llm_calls', k: '계산' }];

  return {
    fieldsAttr: showF ? 'on' : 'off', showFields: showF, isEarly: early, isMature: !early,
    matureP: early ? 'false' : 'true', earlyP: early ? 'true' : 'false', fieldsP: showF ? 'true' : 'false',
    setMature: function () { set({ mode: 'mature', hov: null }); },
    setEarly: function () { set({ mode: 'early', hov: null }); },
    toggleFields: function () { set({ fields: !showF }); },
    head: { day: '가동 ' + days + '일차', run: runLine, stats: stats, liked: '오늘 Top 5 중 몰랐는데 흥미로움 ' + likedN + '/5' },
    earlyBar: { txt: '기준선이 쌓이는 중이에요 (' + days + '/14일). 지금은 "평소 대비" 없이 오늘 어텐션 순으로만 보여줘요. 14일이 차면 평소 대비 z와 가속이 켜져요. 이 샘플에서는 같은 5건을 어텐션 순으로 다시 정렬해서 보여줘요.', pct: Math.round(days / 14 * 100) + '%' },
    topSub: early ? '지금 인기 순 · 오늘 어텐션이 높은 4건 + 탐색 1건'
      : '점수 상위 4건 + 탐색 1건 · 점수 = z + ' + K.W_ACC + '·ln(가속) + ' + K.W_PLAT + '·(플랫폼 수 − 1) · 출처 ' + K.ORIG_MIN + '곳 미만은 제외 (시작값)',
    consts: 'ε ' + K.EPS + ' · z 상한 ' + K.ZCAP + ' · 가속 가중 ' + K.W_ACC + ' · 플랫폼 가중 ' + K.W_PLAT + ' · 임계 ' + f1(K.TH) + ' · 출처 최소 ' + K.ORIG_MIN + '곳',
    top5: cards,
    bSub: '분야마다 3개씩. "실탐"은 임계를 넘어 원문을 읽은 주제, "메타만"은 수치만 본 주제예요.',
    fields: fields,
    pool: pool,
    dayLines: dayLines, hasRoll: !early, noRoll: early, week: week, month: month,
    srcRows: rows, pipe: pipe,
    exec: [
      { l: '실행', v: 'Mac mini M4 Pro · 매일 04:00 자동 실행 (샘플)' },
      { l: '시간', v: '수집 38분 · 계산 6분 · 원문 읽기 ' + minutes + '분 · LLM 9분 · 피드 생성 1분' },
      { l: '실탐 시간 예산', v: minutes + '분 사용 / ' + K.BUDGET + '분 (임계 통과 주제를 다 읽고 남으면 탐색 슬롯에 씀)' },
      { l: '임계', v: '점수 ' + f1(K.TH) + ' 이상 · 출처 ' + K.ORIG_MIN + '곳 이상 (시작값, 2주 뒤 조정)' },
      { l: 'LLM 호출', v: '이름·병합 1회 · 실탐 요약 ' + deepN + '회 · 왜 올랐나 1회 = ' + llmCalls + '회' }],
    warnLine: warnN ? ('정상 ' + nOk + ' · 주의 ' + warnN + ' · 입력 없음 ' + SRC.filter(function (s) { return s.s === 'none'; }).length) : ''
  };
}
