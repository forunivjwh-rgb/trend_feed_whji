#!/usr/bin/env bash
# GitHub Actions 에서 한 번 도는 순서. (.github/workflows/collect.yml 이 부른다)
#
#   1. data 브랜치에서 저장 파일(SQLite 한 파일, trend.db)을 받아 온다
#   2. 수집 → 주제 → 실탐 → 피드를 돌린다
#   3. 저장 파일을 data 브랜치에 다시 올린다
#
# Actions 서버는 실행이 끝나면 지워지므로 저장 파일을 data 브랜치에 맡겨 두고 이어 쓴다.
# 윈도우·맥 컴퓨터에서 돌릴 때는 이 스크립트를 쓰지 않는다(저장 파일이 그 컴퓨터에 그대로 남는다).
set -euo pipefail

DATA_BRANCH="${DATA_BRANCH:-data}"
DATA_DIR="${DATA_DIR:-_data}"
DB_FILE="data/trend.db"

# --- 1. data 브랜치를 옆 폴더(_data)에 꺼낸다. 처음이면 빈 브랜치로 시작한다.
if git fetch --quiet --depth=1 origin "+refs/heads/${DATA_BRANCH}:refs/remotes/origin/${DATA_BRANCH}" 2>/dev/null; then
  git worktree add --quiet -B "${DATA_BRANCH}" "${DATA_DIR}" "origin/${DATA_BRANCH}"
else
  echo "data 브랜치가 아직 없어 새로 만듭니다."
  git worktree add --quiet --orphan -b "${DATA_BRANCH}" "${DATA_DIR}"
fi
mkdir -p "$(dirname "${DB_FILE}")"
if [ -f "${DATA_DIR}/trend.db" ]; then
  cp "${DATA_DIR}/trend.db" "${DB_FILE}"
  echo "저장 파일을 받아 왔습니다."
elif ls "${DATA_DIR}"/days/*.jsonl >/dev/null 2>&1; then
  # 예전 방식(날짜별 글자 파일)으로 쌓인 기록을 한 번만 저장 파일로 옮긴다
  python -m trendfeed import --dir "${DATA_DIR}"
  echo "예전 날짜별 기록을 저장 파일로 옮겼습니다."
fi

# --- 2. 수집 → 주제 → 실탐 → 피드. 일부가 실패해도 저장 파일은 올려야 하므로 여기서 멈추지 않는다.
status=0
python -m trendfeed daily || status=$?

# --- 3. 저장 파일을 data 브랜치에 올린다(예전 날짜별 파일은 옮긴 뒤 지운다).
cp "${DB_FILE}" "${DATA_DIR}/trend.db"
rm -rf "${DATA_DIR}/days"
cp scripts/data_branch_readme.md "${DATA_DIR}/README.md"
git -C "${DATA_DIR}" add -A
if git -C "${DATA_DIR}" diff --cached --quiet; then
  echo "바뀐 기록이 없습니다."
else
  git -C "${DATA_DIR}" -c user.name="trend-feed-bot" -c user.email="trend-feed-bot@users.noreply.github.com" \
    commit --quiet -m "저장 파일: $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M') KST"
  git -C "${DATA_DIR}" push --quiet origin "HEAD:refs/heads/${DATA_BRANCH}"
  echo "data 브랜치에 저장 파일을 올렸습니다."
fi

exit "${status}"
