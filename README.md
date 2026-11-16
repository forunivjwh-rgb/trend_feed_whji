# trend_feed_whji

분야별로 무엇이 뜨는지 매일 한 화면으로 보는 개인용 피드. 설계는 [`docs/SPEC.md`](docs/SPEC.md).

## 지금 되는 것 (명세 9번 "처음 순서" 1단계)

매일 두 곳에서 항목을 모아 **그날의 숫자**를 저장한다. 피드 화면, 점수, 요약은 아직 없다.

| 소스 | 가져오는 것 | 저장하는 숫자 |
| --- | --- | --- |
| Hacker News | 인기글 위에서 60개 (공식 공개 API) | 점수, 댓글 수 |
| GitHub trending | 일간·주간 목록 (공개 페이지 읽기) | 전체 별 수, 포크 수, 오늘·이번 주에 늘어난 별 수 |

둘 다 키나 로그인이 필요 없다.

## 윈도우에서 켜는 법

**1. 코드 받기.** GitHub의 이 repo 페이지에서 초록색 `Code` 버튼 → `Download ZIP`으로 받아 압축을 푼다. 예: `C:\trend_feed`. (git을 쓴다면 `git clone`도 된다.) 폴더를 나중에 옮기면 6번을 다시 해야 한다.

**2. PowerShell 열기.** 시작 메뉴에서 `PowerShell`을 찾아 연다. 아래 명령은 전부 여기에 붙여 넣는다.

**3. `uv` 설치(한 번만).** `uv`는 파이썬을 알맞은 버전으로 맞춰 실행해 주는 도구다. 설치한 뒤 PowerShell을 닫았다 다시 연다.

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**4. 폴더로 들어가 한 번 돌려 본다.** 처음에는 파이썬을 받느라 1~2분 걸릴 수 있다.

```powershell
cd C:\trend_feed
```

```powershell
uv run python -m trendfeed daily
```

**5. 쌓인 것을 본다.**

```powershell
uv run python -m trendfeed status
```

**6. 매일 자동 실행 등록.** 윈도우의 "작업 스케줄러"에 `TrendFeed Daily`라는 이름으로 등록된다.

```powershell
uv run python -m trendfeed install-schedule
```

- 매일 04:00에 돈다. 시각은 `config/settings.toml`의 `[schedule]`에서 바꾸고 이 명령을 다시 돌리면 된다.
- **그 시각에 노트북이 꺼져 있거나 잠들어 있었으면, 켠 뒤에 놓친 실행을 돌린다.** 윈도우가 켜진 직후 몇 분(보통 10분 안쪽) 기다렸다가 시작한다.
- 로그인해 있는 동안에만 돌고, 인터넷이 연결돼 있어야 시작한다. 배터리로 쓰는 중에도 돈다.
- 창은 뜨지 않는다. 무슨 일이 있었는지는 `data\logs\daily.log`를 메모장으로 열어 본다.
- 해제는 아래 명령이다.

```powershell
uv run python -m trendfeed uninstall-schedule
```

노트북은 켜는 시각이 날마다 달라서 숫자를 읽는 간격이 24시간이 아닐 수 있다. 그래서 숫자를 읽은 시각을 같이 저장하고, 하루 증가량은 실제 간격으로 나눠 계산한다.

## 맥에서 켜는 법

터미널에서 `uv`를 한 번 설치한다.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

이 폴더(repo)로 들어가서 돌려 보고, 자동 실행을 등록한다. 명령은 윈도우와 같다.

```bash
uv run python -m trendfeed daily
```

```bash
uv run python -m trendfeed install-schedule
```

맥이 그 시각에 잠들어 있으면 깨어난 뒤에 돈다. 꺼져 있었으면 그날은 건너뛴다.

## 공통

- 같은 날 여러 번 돌려도 그날 숫자는 한 줄만 남는다(나중 값으로 덮어쓴다).
- 자동 실행 기록은 `data/logs/daily.log`에 쌓인다.

## 어디에 무엇이 있나

| 위치 | 내용 |
| --- | --- |
| `config/settings.toml` | 숫자와 한도 전부(수집 개수, 시각, 다시 시도 횟수 등). 코드에는 박지 않는다 |
| `data/trend.db` | 저장 파일(SQLite). git에 올리지 않는다. 이 파일만 복사하면 백업이다 |
| `trendfeed/sources/` | 수집원 하나당 파일 하나 |
| `trendfeed/db.py` | 표 구조 |
| `tests/` | 자동 시험. `uv run python -m unittest discover -s tests -t .` |

저장 파일 안의 표는 셋이다(명세 8번).

- `source_runs`: 소스별 하루 실행 기록. 건수와 상태(정상 / 주의 / 입력 없음), 이유.
- `items`: 수집한 글·저장소 하나. 제목, 링크, 출처, 처음 수집한 날.
- `item_snapshots`: 항목의 하루치 숫자. 기준선을 만드는 재료라 계속 남긴다.

## 알아 둘 것

- **상태 "주의"**는 지금은 일부만 실패했을 때(예: 글 몇 개를 못 읽음, 주간 목록만 못 받음) 붙는다. "평소보다 크게 줄 때" 기준은 실제 수집량을 본 뒤 정한다(명세 9번).
- **Hacker News 다시 확인**: 인기글 목록에서 빠진 글도 2일 동안은 숫자를 다시 적는다. 어제와 오늘의 숫자 차이를 계산하려면 같은 글의 이틀 치가 필요해서다. `follow_days = 0`으로 끌 수 있다.
- **GitHub trending**은 공식 API가 없어 페이지를 읽는다. GitHub가 화면을 바꾸면 0건이 되고 실행 기록에 "입력 없음"과 이유가 남는다. Hacker News 수집에는 영향이 없다.
- 1단계에서는 본문·댓글 같은 원문을 저장하지 않는다. 그래서 2~3일 뒤 지우는 정리는 실탐(4단계)을 붙일 때 만든다.
