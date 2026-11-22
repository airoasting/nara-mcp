"""회사 프로필, 참가 적합도 판정, 관심 검색(watchlist) 저장소.

저장 위치: 이 폴더의 data/ (환경변수 G2B_DATA_DIR로 바꿀 수 있다). JSON 파일 두 개만 쓴다.

적합도 판정 규칙(나라장터 데이터에서 실측)
- 면허제한: 서로 다른 lmtGrpNo는 '또는', 같은 그룹 안의 항목은 '그리고'.
  항목은 그 업종코드나 permsnIndstrytyList(허용업종)의 코드 중 하나를 가지면 충족한다.
- 참가가능지역: 목록이 비어 있으면 제한 없음. 있으면 본사 소재지가 그중 하나에 들어가야 한다.
  '경상북도 경산시'처럼 시군구까지 적힌 경우 시군구도 맞아야 한다.
판정은 참고용이다. 중소기업 제한, 실적 제한, 공동수급 조건은 공고문을 직접 확인해야 한다.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from g2b_core import won_kr

DATA_DIR = Path(os.environ.get("G2B_DATA_DIR") or Path(__file__).with_name("data"))
PROFILE_FILE = DATA_DIR / "profile.json"
WATCH_FILE = DATA_DIR / "watchlist.json"


def _load(p: Path, default: Any) -> Any:
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return default


def _save(p: Path, data: Any) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


# ---------------------------------------------------------------- 프로필

PROFILE_KEYS = ["company_name", "region", "licenses", "keywords", "exclude_keywords",
                "categories", "min_price", "max_price", "notes"]


def get_profile() -> dict[str, Any]:
    return _load(PROFILE_FILE, {})


def update_profile(changes: dict[str, Any], replace: bool = False) -> dict[str, Any]:
    prof = {} if replace else get_profile()
    for k, v in changes.items():
        if k not in PROFILE_KEYS:
            raise ValueError(f"모르는 항목: {k}. 쓸 수 있는 항목: {', '.join(PROFILE_KEYS)}")
        if v is None:
            continue
        prof[k] = v
    _save(PROFILE_FILE, prof)
    return prof


# ---------------------------------------------------------------- 지역

_SIDO = {
    "서울": ["서울특별시", "서울시", "서울"],
    "부산": ["부산광역시", "부산시", "부산"],
    "대구": ["대구광역시", "대구시", "대구"],
    "인천": ["인천광역시", "인천시", "인천"],
    "광주": ["광주광역시", "광주시", "광주"],
    "대전": ["대전광역시", "대전시", "대전"],
    "울산": ["울산광역시", "울산시", "울산"],
    "세종": ["세종특별자치시", "세종시", "세종"],
    "경기": ["경기도", "경기"],
    "강원": ["강원특별자치도", "강원도", "강원"],
    "충북": ["충청북도", "충북"],
    "충남": ["충청남도", "충남"],
    "전북": ["전북특별자치도", "전라북도", "전북"],
    "전남": ["전라남도", "전남"],
    "경북": ["경상북도", "경북"],
    "경남": ["경상남도", "경남"],
    "제주": ["제주특별자치도", "제주도", "제주"],
}


def _split_region(s: str) -> tuple[str | None, str | None]:
    s = (s or "").strip()
    for key, names in _SIDO.items():
        for nm in names:
            if s.startswith(nm):
                rest = s[len(nm):].strip().split()
                return key, (rest[0] if rest else None)
    return None, None


def region_ok(company_region: str, allowed: list[str]) -> tuple[bool | None, str]:
    if not allowed:
        return True, "지역 제한 없음"
    if not company_region:
        return None, f"참가가능지역 {allowed}. 프로필에 본사 소재지(region)가 없어 판정하지 못했다."
    c_sido, c_sgg = _split_region(company_region)
    for a in allowed:
        a_sido, a_sgg = _split_region(a)
        if a_sido and a_sido == c_sido and (not a_sgg or a_sgg == c_sgg):
            return True, f"참가가능지역 '{a}'에 해당"
    return False, f"참가가능지역 {allowed}에 본사 소재지 '{company_region}'가 없다"


# ---------------------------------------------------------------- 면허

_CODE = re.compile(r"/\s*(\w+)\s*\]?$")


def _code(s: str) -> str | None:
    s = s.strip()
    if re.fullmatch(r"\d{3,5}", s):
        return s
    m = _CODE.search(s)
    return m.group(1) if m else None


def _name(s: str) -> str:
    return s.split("/")[0].strip().strip("[]")


def license_ok(company_licenses: list[str], limits: list[dict[str, Any]]) -> tuple[bool | None, str]:
    if not limits:
        return True, "면허(업종) 제한 없음"
    groups: dict[str, list[dict[str, Any]]] = {}
    for it in limits:
        groups.setdefault(str(it.get("lmtGrpNo", "1")), []).append(it)
    desc = " 또는 ".join(
        "(" + " 그리고 ".join(i.get("lcnsLmtNm", "") for i in g) + ")" for g in groups.values()
    )
    if not company_licenses:
        return None, f"면허제한 {desc}. 프로필에 보유 업종(licenses)이 없어 판정하지 못했다."
    have_codes = {c for c in (_code(x) for x in company_licenses) if c}
    have_names = {_name(x) for x in company_licenses}

    def item_ok(it: dict[str, Any]) -> bool:
        opts = [it.get("lcnsLmtNm", "")] + re.findall(r"\[([^\]]+)\]", it.get("permsnIndstrytyList") or "")
        for o in opts:
            c = _code(o)
            if (c and c in have_codes) or _name(o) in have_names:
                return True
        return False

    for gno, g in groups.items():
        if all(item_ok(i) for i in g):
            return True, f"면허 그룹 {gno} 충족: {', '.join(i.get('lcnsLmtNm', '') for i in g)}"
    return False, f"면허제한 {desc} 중 충족하는 그룹이 없다"


# ---------------------------------------------------------------- 종합 판정

def judge(profile: dict[str, Any], notice: dict[str, Any], limits: list[dict[str, Any]] | str,
          regions: list[dict[str, Any]] | str) -> dict[str, Any]:
    checks = []

    def add(name: str, ok: bool | None, why: str) -> None:
        checks.append({"check": name, "result": {True: "충족", False: "불충족", None: "확인 필요"}[ok], "detail": why})

    status = notice.get("status")
    add("마감", status != "마감" if status else None, status or "마감일 정보 없음")

    if isinstance(limits, str):
        add("면허(업종)", None, limits)
    else:
        add("면허(업종)", *license_ok(profile.get("licenses") or [], limits))

    if isinstance(regions, str):
        add("참가지역", None, regions)
    else:
        allowed = sorted({r.get("prtcptPsblRgnNm", "") for r in regions if r.get("prtcptPsblRgnNm")})
        add("참가지역", *region_ok(profile.get("region") or "", allowed))

    price = notice.get("presmptPrce")
    lo, hi = profile.get("min_price"), profile.get("max_price")
    if price and (lo or hi):
        p = int(float(price))
        ok = (not lo or p >= int(lo)) and (not hi or p <= int(hi))
        rng = f"{won_kr(lo) if lo else '하한 없음'}~{won_kr(hi) if hi else '상한 없음'}"
        add("금액대", ok, f"추정가격 {notice.get('presmptPrce_kr', price)}, 선호 범위 {rng}")

    words = [w for w in profile.get("exclude_keywords") or [] if w in (notice.get("bidNtceNm") or "")]
    if words:
        add("제외 키워드", False, f"공고명에 제외 키워드 {words}")

    hard = [c for c in checks if c["check"] in ("마감", "면허(업종)", "참가지역")]
    if any(c["result"] == "불충족" for c in hard):
        verdict = "참가 어려움"
    elif any(c["result"] == "확인 필요" for c in hard):
        verdict = "확인 필요"
    else:
        verdict = "참가 가능(자격 기준)"
    return {
        "verdict": verdict,
        "checks": checks,
        "caution": "중소기업·실적·공동수급·직접생산 조건은 공고문으로 따로 확인한다.",
    }


# ---------------------------------------------------------------- 관심 검색

def list_watch() -> dict[str, Any]:
    return _load(WATCH_FILE, {})


def save_watch(data: dict[str, Any]) -> None:
    _save(WATCH_FILE, data)
