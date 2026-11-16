#!/usr/bin/env bash
# GitHub Actions 에서 한 번 도는 순서. (.github/workflows/collect.yml 이 부른다)
#
#   1. data 브랜치의 날짜별 기록 파일로 저장 파일을 되살린다
#   2. 수집하고 피드 화면을 만든다
#   3. 오늘 치 기록 파일을 data 브랜치에 올린다
#
# 서버에는 저장 파일을 계속 둘 곳이 없어서 매번 기록 파일에서 다시 만든다.
set -euo pipefail

DATA_BRANCH="${DATA_BRANCH:-data}"
DATA_DIR="${DATA_DIR:-_data}"

# --- 1. data 브랜치를 옆 폴더(_data)에 꺼낸다. 처음이면 빈 브랜치로 시작한다.
if git fetch --quiet --depth=1 origin "+refs/heads/${DATA_BRANCH}:refs/remotes/origin/${DATA_BRANCH}" 2>/dev/null; then
  git worktree add --quiet -B "${DATA_BRANCH}" "${DATA_DIR}" "origin/${DATA_BRANCH}"
else
  echo "data 브랜치가 아직 없어 새로 만듭니다."
  git worktree add --quiet --orphan -b "${DATA_BRANCH}" "${DATA_DIR}"
fi
python -m trendfeed import --dir "${DATA_DIR}"

# --- 2. 수집 + 피드. 일부 소스가 실패해도 기록은 남겨야 하므로 여기서 멈추지 않는다.
status=0
python -m trendfeed daily || status=$?

# --- 3. 오늘 치 기록 파일을 쓰고, 바뀐 것이 있으면 data 브랜치에 올린다.
python -m trendfeed export --dir "${DATA_DIR}"
cp scripts/data_branch_readme.md "${DATA_DIR}/README.md"
git -C "${DATA_DIR}" add -A
if git -C "${DATA_DIR}" diff --cached --quiet; then
  echo "바뀐 기록이 없습니다."
else
  git -C "${DATA_DIR}" -c user.name="trend-feed-bot" -c user.email="trend-feed-bot@users.noreply.github.com" \
    commit --quiet -m "기록: $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M') KST"
  git -C "${DATA_DIR}" push --quiet origin "HEAD:refs/heads/${DATA_BRANCH}"
  echo "data 브랜치에 기록을 올렸습니다."
fi

exit "${status}"
