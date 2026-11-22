"""나라장터 낙찰정보서비스(ScsbidInfoService) 응답 가공과 통계.

명세 출처: 공공데이터포털 swagger(data/15129397)와
'조달청_OpenAPI참고자료_나라장터_낙찰정보서비스_1.2_261110.docx'.

오퍼레이션별 조회구분(inqryDiv)은 같은 서비스 안에서도 다르다(참고문서 기준, 2026-11-22 실호출로 확인).
- 낙찰목록 getScsbidListSttus{업무}            1 등록일시, 2 공고일시, 3 개찰일시, 4 입찰공고번호
- 개찰결과 getOpengResultListInfo{업무}        1 입력일시, 2 공고일시, 3 개찰일시, 4 입찰공고번호
- 검색조건 ...PPSSrch                          1 공고일시, 2 개찰일시, 3 입찰공고번호
- 예비가격 ...PreparPcDetail                   1 입력일시, 2 입찰공고번호(+차수)
- 개찰완료·유찰·재입찰 OpengCompt/Failing/Rebid  inqryDiv 없음. bidNtceNo 필수, 차수·분류·재입찰번호 선택
"""

from __future__ import annotations

import statistics
from typing import Any

from g2b_core import won_kr

AWARD_FIELDS = [
    "bidNtceNo", "bidNtceOrd", "bidNtceNm", "dminsttNm", "prtcptCnum",
    "bidwinnrNm", "bidwinnrBizno", "sucsfbidAmt", "sucsfbidRate", "rlOpengDt", "fnlSucsfDate",
]

INQRY = {
    "list": {"등록일시": 1, "공고일시": 2, "개찰일시": 3, "공고번호": 4},
    "ppssrch": {"공고일시": 1, "개찰일시": 2, "공고번호": 3},
}


def _num(v: Any) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def award_summary(it: dict[str, Any], category: str | None = None) -> dict[str, Any]:
    s = {k: it[k].strip() if isinstance(it[k], str) else it[k]
         for k in AWARD_FIELDS if it.get(k) not in ("", None)}
    if category:
        s["category"] = category
    if (w := won_kr(it.get("sucsfbidAmt"))):
        s["sucsfbidAmt_kr"] = w
    return s


def parse_corp_info(s: str | None) -> list[dict[str, Any]]:
    """opengCorpInfo '업체명^사업자번호^대표자^투찰금액^투찰률'을 풀어낸다. 여러 건이면 '|'로 이어진다."""
    out = []
    for part in (s or "").split("|"):
        f = part.strip().split("^")
        if len(f) < 4 or not f[0]:
            continue
        row = {"name": f[0], "bizno": f[1], "ceo": f[2], "bid_amount": f[3]}
        if len(f) > 4:
            row["bid_rate"] = f[4]
        if (w := won_kr(f[3])):
            row["bid_amount_kr"] = w
        out.append(row)
    return out


def stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    """낙찰률, 낙찰금액, 참가업체 수의 분포와 자주 낙찰받은 업체."""
    def col(k: str) -> list[float]:
        return [x for x in (_num(i.get(k)) for i in items) if x is not None and x > 0]

    def desc(xs: list[float], money: bool = False) -> dict[str, Any] | None:
        if not xs:
            return None
        d = {"n": len(xs), "min": min(xs), "median": statistics.median(xs), "mean": round(statistics.fmean(xs), 3),
             "max": max(xs)}
        if money:
            d = {k: (int(v) if k != "n" else v) for k, v in d.items()}
            d["median_kr"] = won_kr(d["median"])
        return d

    winners: dict[str, int] = {}
    for i in items:
        if i.get("bidwinnrNm"):
            winners[i["bidwinnrNm"].strip()] = winners.get(i["bidwinnrNm"].strip(), 0) + 1
    top = sorted(winners.items(), key=lambda x: -x[1])[:10]
    return {
        "count": len(items),
        "sucsfbidRate_pct": desc(col("sucsfbidRate")),
        "sucsfbidAmt_won": desc(col("sucsfbidAmt"), money=True),
        "prtcptCnum": desc(col("prtcptCnum")),
        "top_winners": [{"name": n, "wins": c} for n, c in top if c > 1] or None,
    }
