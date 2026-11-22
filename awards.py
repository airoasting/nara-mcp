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


def _desc(xs: list[float], money: bool = False) -> dict[str, Any] | None:
    if not xs:
        return None
    d: dict[str, Any] = {"n": len(xs), "min": min(xs), "median": round(statistics.median(xs), 3),
                         "mean": round(statistics.fmean(xs), 3), "max": max(xs)}
    if money:
        d = {k: (int(v) if k != "n" else v) for k, v in d.items()}
        d["median_kr"] = won_kr(d["median"])
    return d


def _group(items: list[dict[str, Any]]) -> dict[str, Any]:
    def col(k: str) -> list[float]:
        return [x for x in (_num(i.get(k)) for i in items) if x is not None and x > 0]
    return {
        "count": len(items),
        "sucsfbidRate_pct": _desc(col("sucsfbidRate")),
        "sucsfbidAmt_won": _desc(col("sucsfbidAmt"), money=True),
        "prtcptCnum": _desc(col("prtcptCnum")),
    }


def stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    """낙찰률·낙찰금액·참가업체 수 분포를 전체, 경쟁(2개사 이상), 단독(1개사)으로 나눠 낸다.

    단독 낙찰은 수의계약이 많아 경쟁 낙찰보다 낙찰률이 높게 나온다(실측: 용역 113건 중 58건이 단독, 단독 중앙값 92.96%).
    낙찰률 0이나 빈 값(협상에 의한 계약에서 흔하다)은 낙찰률 통계에서 뺀다. 다수 낙찰 업체는 사업자등록번호로 센다.
    """
    comp = [i for i in items if (_num(i.get("prtcptCnum")) or 0) >= 2]
    single = [i for i in items if (_num(i.get("prtcptCnum")) or 0) == 1]
    winners: dict[str, dict[str, Any]] = {}
    for i in items:
        key = (i.get("bidwinnrBizno") or i.get("bidwinnrNm") or "").strip()
        if not key:
            continue
        w = winners.setdefault(key, {"name": (i.get("bidwinnrNm") or "").strip(), "bizno": i.get("bidwinnrBizno"),
                                     "wins": 0, "competitive_wins": 0})
        w["wins"] += 1
        if (_num(i.get("prtcptCnum")) or 0) >= 2:
            w["competitive_wins"] += 1
    top = sorted(winners.values(), key=lambda x: (-x["competitive_wins"], -x["wins"]))[:10]
    return {
        "all": _group(items),
        "competitive": _group(comp),
        "single_bidder": _group(single),
        "top_winners": [w for w in top if w["wins"] > 1] or [],
        "how_to_read": ("시세는 competitive(참가 2개사 이상)를 본다. 다만 competitive에도 2인 이상 견적 수의계약이 섞일 수 있다. "
                        "낙찰방법별로 보려면 search_awards의 with_method를 쓴다. single_bidder는 대개 수의계약이다."),
    }


def by_method(items: list[dict[str, Any]]) -> dict[str, Any]:
    """낙찰방법(sucsfbidMthdNm)별로 나눈 통계. items에는 'method' 키가 붙어 있어야 한다.

    방법 안에서도 공고마다 낙찰하한율이 다르므로(87.745, 88.745, 89.745 등) 낙찰률에서 하한율을 뺀 값(rate_minus_floor_pp)을
    함께 낸다(nominal_rate_minus_floor_pp, A값 미반영 명목값). 협상계약처럼 낙찰률이 비면 예산 대비 낙찰가(award_to_budget_pct)를 본다.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for i in items:
        groups.setdefault(i.get("method") or "알 수 없음", []).append(i)
    out = {}
    for m, g in sorted(groups.items(), key=lambda x: -len(x[1])):
        st = _group(g)
        diffs = [_num(i.get("sucsfbidRate")) - _num(i.get("lwlt")) for i in g
                 if (_num(i.get("sucsfbidRate")) or 0) > 0 and _num(i.get("lwlt"))]
        # 공고 하한율 기준의 명목 차이다. A값이 있는 공사·물품은 실제 하한율이 더 높아 여유가 부풀려진다(SILVER 4차 평가).
        # 개별 공고의 실제 차이는 get_award의 winner_rate_minus_floor_pp(A값 반영)를 쓴다.
        st["nominal_rate_minus_floor_pp"] = _desc([round(d, 3) for d in diffs])
        st["award_to_budget_pct"] = _desc([x for x in (_num(i.get("award_to_budget_pct")) for i in g) if x])
        out[m] = st
    return out


A_VALUE_FIELDS = ["sftyMngcst", "sftyChckMngcst", "npnInsrprm", "mrfnHealthInsrprm", "rtrfundNon",
                  "odsnLngtrmrcprInsrprm", "qltyMngcst"]


def a_value(base: dict[str, Any]) -> tuple[float, dict[str, float], bool]:
    """(A값 합계, 항목, 적용 여부). 공고 플래그를 우선한다(SILVER 3차 평가).

    - bidPrceCalclAYn이 'Y'일 때만 A값을 적용한다.
    - 항목별 '<항목>AObjYn'이 'N'이면 그 항목은 A값에서 뺀다(예: qltyMngcstAObjYn=N이면 품질관리비 제외).
    """
    items = {}
    for k in A_VALUE_FIELDS:
        v = _num(base.get(k))
        if v and v > 0 and base.get(k + "AObjYn") != "N":
            items[k] = v
    uses = base.get("bidPrceCalclAYn") == "Y"
    return (sum(items.values()) if uses else 0.0), items, uses


def effective_floor_rate(lower_rate: Any, a_val: float, planned_price: Any) -> float | None:
    """A값이 있을 때 예정가격 대비 실제 하한율(%) = r + (A/P)(100 − r). bidprcrt와 같은 기준으로 비교할 때 쓴다."""
    r, p = _num(lower_rate), _num(planned_price)
    if not r or not p:
        return None
    return round(r + (a_val / p) * (100 - r), 3) if a_val else r


def bid_calc(base: dict[str, Any], lower_rate: Any) -> dict[str, Any] | None:
    """기초금액 응답으로 예정가격 예상 범위와 낙찰하한율 기준 참고 하한을 낸다.

    A값(국민연금·건강보험·퇴직급여충당금·노인장기요양보험료·안전관리비·품질관리비 등)이 있는 공고는
    '하한 = A + (예정가격 − A) × 하한율'로 계산한다(SILVER 평가: A값을 빼면 실제 하한보다 낮게 나온다).
    어떤 항목이 A값에 들어가는지와 산식은 공고의 적용 기준(sucsfbidMthdAppStd)마다 다르니 공고로 확인한다.
    """
    bss = _num(base.get("bssamt"))
    if not bss:
        return None
    lo_r = _num(base.get("rsrvtnPrceRngBgnRate"))
    hi_r = _num(base.get("rsrvtnPrceRngEndRate"))
    out: dict[str, Any] = {"bssamt": int(bss), "bssamt_kr": won_kr(bss)}
    if lo_r is not None and hi_r is not None:
        lo, hi = bss * (1 + lo_r / 100), bss * (1 + hi_r / 100)
        out["planned_price_range"] = [int(lo), int(hi)]
        out["planned_price_range_kr"] = f"{won_kr(lo)} ~ {won_kr(hi)} (기초금액 {lo_r:+g}% ~ {hi_r:+g}%)"
    a_val, a_items, uses_a = a_value(base)
    if a_items and not uses_a:
        out["a_value_note"] = "A값 항목이 있으나 bidPrceCalclAYn이 Y가 아니라 하한 계산에 반영하지 않았다"
    if uses_a:
        out["a_value"] = int(a_val)
        out["a_value_kr"] = won_kr(a_val)
        out["a_value_items"] = {k: int(v) for k, v in a_items.items()}
    rate = _num(lower_rate)
    if rate:
        out["sucsfbidLwltRate"] = rate

        def floor(p: float) -> float:
            return a_val + (p - a_val) * rate / 100 if uses_a else p * rate / 100

        out["reference_floor_at_base"] = int(floor(bss))
        out["reference_floor_at_base_kr"] = (f"{won_kr(floor(bss))} (사정률 100% 가정, "
                                             + ("A값 반영: A + (예정가격 − A) × 하한율" if uses_a else "예정가격 × 하한율") + ")")
        if "planned_price_range" in out:
            lo, hi = out["planned_price_range"]
            out["reference_floor_range_kr"] = f"{won_kr(floor(lo))} ~ {won_kr(floor(hi))} (예정가격 범위 양끝 기준)"
    out["caution"] = ("참고 계산이다. A값 항목과 산식은 공고의 적용 기준마다 다르다. 실제 투찰 전 공고의 산식과 "
                      "나라장터 투찰 화면의 하한을 반드시 확인한다.")
    return out
