"""수집원 모음. 가져오는 방식은 소스마다 달라도 돌려주는 모양(Record)은 같다."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Record:
    """수집한 항목 하나와 그날의 숫자 (명세 3번·8번)."""

    external_id: str            # 소스 안에서의 고유 번호·이름
    title: str
    url: str
    origin: str | None          # 출처: 올린 계정·조직·사이트
    published_at: str | None    # 올라온 시각(UTC). 소스가 알려 주지 않으면 None
    rank: int | None = None     # 목록에서의 순서(1부터)
    listed: bool = True         # False면 목록에서는 빠졌지만 숫자만 다시 적은 것
    metrics: dict = field(default_factory=dict)     # views·stars·score·comments·likes 중 있는 것
    item_extra: dict = field(default_factory=dict)  # 항목에 붙는 그 밖의 정보
    snap_extra: dict = field(default_factory=dict)  # 그날의 그 밖의 숫자


@dataclass
class CollectResult:
    records: list[Record]
    problems: list[str] = field(default_factory=list)  # 일부만 실패했을 때의 이유


def registry() -> dict:
    """수집 코드 모음. 설정 파일의 [sources.이름]은 같은 이름(또는 module 값)의 코드를 쓴다."""
    from . import github_trending, hackernews, huggingface

    return {
        "hackernews": hackernews,
        "github_trending": github_trending,
        "huggingface": huggingface,
    }


def module_for(name: str, cfg: dict):
    """소스 이름과 그 설정으로 수집 코드를 찾는다. 한 코드를 여러 소스가 쓸 수 있다(예: 위키 한국어·영어)."""
    return registry()[cfg.get("module", name)]
