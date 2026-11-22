"""회사 프로필, 참가 적합도 판정, 관심 검색(watchlist) 저장소.

저장 위치: 이 폴더의 data/ (환경변수 G2B_DATA_DIR로 바꿀 수 있다). JSON 파일 두 개만 쓴다.

적합도 판정 원칙
- 거짓 '참가 가능'이 가장 위험한 오류다. 확실하지 않으면 '확인 필요'로 내린다.
- '참가 가능'은 공개 제한(면허·지역·제한 플래그)과 공고문 자격 조건(직접생산, 중소기업·대기업 제한)을
  모두 확인했을 때만 낸다. 공고문을 읽지 못했으면 '확인 필요'다.

나라장터 데이터에서 실측한 규칙
- 면허제한: 서로 다른 lmtGrpNo는 '또는', 같은 그룹 안의 항목은 '그리고'.
  항목은 그 업종코드나 permsnIndstrytyList(허용업종)의 코드 중 하나를 가지면 충족한다.
- 참가가능지역: 목록이 비어 있으면 제한 없음. 있으면 본사 소재지가 그중 하나에 들어가야 한다.
  '경상북도 경산시'처럼 시군구까지 적힌 경우 시군구도 맞아야 한다.
- 취소공고(ntceKindNm=취소공고)는 마감일이 남아 있어도 참가할 수 없다.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from g2b_core import biz_type, deadline_status, now_kst, parse_dt, won_kr

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

PROFILE_KEYS = ["company_name", "region", "licenses", "company_size", "direct_production",
                "keywords", "exclude_keywords", "exclude_types", "categories", "min_price", "max_price", "notes"]
COMPANY_SIZES = ["대기업", "중견기업", "중소기업", "소기업", "소상공인"]


def get_profile() -> dict[str, Any]:
    return _load(PROFILE_FILE, {})


def update_profile(changes: dict[str, Any], replace: bool = False) -> dict[str, Any]:
    prof = {} if replace else get_profile()
    for k, v in changes.items():
        if k not in PROFILE_KEYS:
            raise ValueError(f"모르는 항목: {k}. 쓸 수 있는 항목: {', '.join(PROFILE_KEYS)}")
        if v is None:
            continue
        if k == "company_size" and v not in COMPANY_SIZES:
            raise ValueError(f"company_size는 {', '.join(COMPANY_SIZES)} 중 하나다(받은 값: {v!r}).")
        prof[k] = v
    _save(PROFILE_FILE, prof)
    return prof


# ---------------------------------------------------------------- 지역

_SIDO = {
    "전남광주": ["전남광주통합특별시"],  # 2026년 응답에 실제로 나오는 통합 지역명
    "서울": ["서울특별시", "서울시", "서울"],
    "부산": ["부산광역시", "부산시", "부산"],
    "대구": ["대구광역시", "대구시", "대구"],
    "인천": ["인천광역시", "인천시", "인천"],
    "광주": ["광주광역시", "광주"],  # '광주시'는 경기도 광주시와 헷갈려 뺀다(RED 평가)
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
# 긴 이름부터 맞춘다. 이름 뒤는 공백이나 끝이어야 한다('전남'이 '전남광주통합특별시'에 걸리지 않게).
_SIDO_NAMES = sorted(((nm, key) for key, names in _SIDO.items() for nm in names), key=lambda x: -len(x[0]))
# 통합 전후 이름이 섞이면 같은 곳인지 단정할 수 없다.
_AMBIGUOUS = {frozenset({"전남광주", "광주"}), frozenset({"전남광주", "전남"})}


def _split_region(s: str) -> tuple[str | None, str | None]:
    s = (s or "").strip()
    for nm, key in _SIDO_NAMES:
        if s == nm or s.startswith(nm + " "):
            rest = s[len(nm):].strip().split()
            return key, (rest[0] if rest else None)
    return None, None


def region_ok(company_region: str, allowed: list[str]) -> tuple[bool | None, str]:
    if not allowed:
        return True, "지역 제한 없음"
    if not company_region:
        return None, f"참가가능지역 {allowed}. 프로필에 본사 소재지(region)가 없어 판정하지 못했다."
    c_sido, c_sgg = _split_region(company_region)
    if not c_sido:
        return None, f"본사 소재지 '{company_region}'의 시도를 해석하지 못했다. 참가가능지역 {allowed}"
    unsure = []
    for a in allowed:
        a_sido, a_sgg = _split_region(a)
        if not a_sido or frozenset({a_sido, c_sido}) in _AMBIGUOUS:
            unsure.append(a)
            continue
        if a_sido != c_sido:
            continue
        if not a_sgg or a_sgg == c_sgg:
            return True, f"참가가능지역 '{a}'에 해당"
        if not c_sgg:
            unsure.append(a)
    if unsure:
        return None, f"참가가능지역 {unsure}와 본사 소재지 '{company_region}'가 같은지 단정할 수 없다(시군구 누락 또는 지역명 변경)"
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
    names_without_code = {_name(x) for x in company_licenses if not _code(x) and _name(x)}

    def item_ok(it: dict[str, Any]) -> bool:
        opts = [it.get("lcnsLmtNm", "")] + re.findall(r"\[([^\]]+)\]", it.get("permsnIndstrytyList") or "")
        for o in opts:
            c = _code(o)
            if c and c in have_codes:
                return True
            # 코드 없이 저장한 면허만 이름으로 맞춘다(빈 이름끼리 맞는 일이 없게)
            if _name(o) and _name(o) in names_without_code:
                return True
        return False

    for gno, g in groups.items():
        if all(item_ok(i) for i in g):
            return True, f"면허 그룹 {gno} 충족: {', '.join(i.get('lcnsLmtNm', '') for i in g)}"
    if names_without_code:
        return None, (f"면허제한 {desc}. 프로필 면허 {sorted(names_without_code)}에 업종코드가 없어 이름으로만 대조했고 "
                      "맞는 것이 없다. '업종명/코드' 형식으로 저장하면 정확해진다.")
    return False, f"면허제한 {desc} 중 충족하는 그룹이 없다"


# ---------------------------------------------------------------- 공고문 자격 조건

# 조건 문장 패턴. 법령 이름(중소기업제품 구매촉진 및 판로지원에 관한 법률)은 미리 지워 오탐을 막는다.
_COND_PATTERNS = {
    "직접생산": re.compile(r"직접\s*생산"),
    # '중소기업·소상공인'의 '소기업·소상공인'에 걸리지 않게 앞 글자가 '중'이면 제외한다
    "소기업·소상공인 제한": re.compile(
        r"((?<!중)(?<!중·)(?<!중ㆍ)(?<!중 )(?<!중,)소기업\s*(?:[·ㆍ,]|또는|및|과|와)?\s*소상공인(?!\s*확인서\s*\d)"
        r"|소상공인\s*만|(?<![중·ㆍ])소기업\s*만|(?<![중·ㆍ])소기업(?:으로|에\s*한)"
        r"|(?<!기업·)(?<!기업 )(?<!기업)소상공인\s*확인서)"),
    "중소기업 제한": re.compile(
        r"(중소기업자\s*간|중소기업\s*(?:자)?\s*(?:만|으로|에\s*한|로\s*제한)|중소기업기본법[^.\n]{0,40}중소기업"
        r"|중소기업\s*[·ㆍ,]?\s*소상공인|중\s*[·ㆍ,]\s*소기업|중소기업자(?:로서|이어야|일\s*것|인\s*자))"),
    "대기업 참여 제한": re.compile(
        r"(대기업[^.\n]{0,25}(?:참여|참가)[^.\n]{0,15}(?:제한|불가|금지|없|할\s*수\s*없)|대기업인\s*소프트웨어사업자"
        r"|대기업\s*(?:및|과|·|ㆍ)\s*중견기업|상호출자제한기업집단)"),
    # 판정하지 않는 요건(공고문에만 적힌 실적·소재지·신용등급·인증). 찾으면 '확인 필요' 근거로 남긴다(RED 4차 평가)
    "공고문 기타 요건": re.compile(
        r"((?:수행|이행|납품|용역)\s*실적[^.\n]{0,40}(?:이상|있는|보유)|본점\s*소재지|소재지가[^.\n]{0,20}(?:인|에\s*있는)"
        r"|신용\s*평가\s*등급|(?:ISMS|ISO\s*\d+|CC\s*인증|GS\s*인증|품질\s*인증)[^.\n]{0,30}(?:보유|취득|받은))"),
    "기타 참여 제한": re.compile(
        r"(여성기업|사회적기업|장애인기업|사회적협동조합|자활기업|마을기업|창업기업|벤처기업)[^.\n]{0,30}(?:제한|한정|만\s|참가|참여)"),
}
_LAW_NAMES = re.compile(r"중소기업제품\s*구매\s*촉진\s*및\s*판로\s*지원에\s*관한\s*법률(\s*시행(?:령|규칙))?")
# 참가 요건 문장이라는 신호
_REQ_CUES = re.compile(r"(소지한|소지하|갖춘|갖추|보유한|보유하|자격|(?<!면)제한|한정|한함|한하|참여할\s*수|참가할\s*수|참여\s*가능|참가\s*가능"
                       r"|만\s*참여|만\s*참가|으로\s*한다|이어야|발급받은|등록한\s*자|인\s*자|한\s*자)")
# 계약 이행·제출 서류·점검 문장(참가 요건이 아니다. GOLD 평가에서 실측)
_NOT_REQ = re.compile(r"(위반|해지|해제|취소할|면제|하도급|1\s*부|사본|원본|제출\s*서류|구비\s*서류|증빙\s*서류|확인\s*기준|점검|실태\s*조사|사후\s*관리)")
_NEGATION = re.compile(r"(아닙니다|아님|아니다|아니며|아니고|해당하지\s*않|해당\s*없|해당없|적용하지\s*않|적용되지\s*않|대상이\s*아)")
_SENT_SPLIT = re.compile(r"(?<=[다요음함])\.\s+|\n+|(?<=[다])\s+(?=\d+\)|[가-하]\.|[①-⑳]|-\s)")
_QUAL_SECTION = re.compile(r"(입찰\s*참가\s*자격|참가\s*자격|참가자의\s*자격)")
MAX_SENT = 300


def _sentences(text: str) -> list[str]:
    out = []
    for sent in _SENT_SPLIT.split(text or ""):
        s = " ".join((sent or "").split())
        while len(s) > MAX_SENT:  # 긴 줄을 버리지 않고 잘라서 본다(RED 평가: 311자 줄 누락)
            cut = s.rfind(" ", 0, MAX_SENT)
            cut = cut if cut > 100 else MAX_SENT
            out.append(s[:cut])
            s = s[cut:].strip()
        if len(s) >= 6:
            out.append(s)
    return out


def has_qualification_section(text: str) -> bool:
    return bool(_QUAL_SECTION.search(text or ""))


def scan_conditions(text: str) -> dict[str, list[str]]:
    """공고문·제안요청서 본문에서 참가 요건 문장을 뽑는다. 근거로 원문 문장을 그대로 남긴다.

    계약 이행·제출 서류 문장과 부정문(예: '중소기업자간 경쟁제품이 아닙니다')은 요건에서 뺀다.
    """
    found: dict[str, list[str]] = {}
    for s in _sentences(text):
        # 가운뎃점 변형(ㆍ, ․, ‧, ∙)을 하나로 맞춘다(GOLD 4차 평가: '중․소기업'을 소기업 제한으로 오독)
        probe = re.sub(r"[ㆍ․‧∙•]", "·", _LAW_NAMES.sub("판로지원법", s))
        hits = [name for name, pat in _COND_PATTERNS.items() if pat.search(probe)]
        if not hits:
            continue
        if "소기업·소상공인 제한" in hits and "중소기업 제한" in hits:
            hits.remove("중소기업 제한")  # 더 좁은 조건만 남긴다
        # 이행 조항·제출 서류·부정문이거나 요건 단서가 약한 문장은 버리지 않고 '불명확'으로 남긴다(RED 3차 평가).
        # 불명확 문장은 판정을 '확인 필요'까지만 내릴 수 있고 '참가 어려움'은 만들지 않는다.
        unclear = bool(_NOT_REQ.search(probe) or _NEGATION.search(probe) or not _REQ_CUES.search(probe))
        for name in hits:
            key = name + UNCLEAR if unclear else name
            lst = found.setdefault(key, [])
            if s not in lst and len(lst) < 5:
                lst.append(s)
    return found


UNCLEAR = " (불명확)"


def _worst(results: list[tuple[bool | None, str]]) -> tuple[bool | None, str]:
    """여러 근거 문장 중 가장 불리한 결과를 고른다(불충족 > 확인 필요 > 충족)."""
    for want in (False, None, True):
        for ok, why in results:
            if ok is want:
                return ok, why
    return None, "근거 없음"


def _dp_check(dp: list[str] | None, s: str) -> tuple[bool | None, str]:
    if dp is None:
        return None, f"공고문이 직접생산확인을 요구한다: \"{s}\". 프로필에 직접생산 보유 품명(direct_production)이 없다"
    if dp == []:
        return False, f"공고문이 직접생산확인을 요구하는데 프로필은 보유 없음이다: \"{s}\""
    hit = [p for p in dp if p and p.replace(" ", "") in s.replace(" ", "")]
    if not hit:
        return None, f"공고문의 품명과 보유 품명 {dp}이 같은지 확인한다: \"{s}\""
    codes = set(re.findall(r"\d{10}", s))
    any_of = re.search(r"(1\s*개\s*이상|하나\s*이상|중\s*1|어느\s*하나)", s)
    listed = len(codes) > 1 or re.search(r"[가-힣]\s*[,、]\s*[가-힣]", _LAW_NAMES.sub("", s))
    if any_of or not listed:
        return True, f"보유 품명 {hit} 확인: \"{s}\""
    return None, f"여러 품명이 모두 필요한지 확인한다(보유 {hit}): \"{s}\""


def _size_eval(kind: str, size: str | None, s: str) -> tuple[bool | None, str]:
    if not size:
        return None, f"{kind}이 있다: \"{s}\". 프로필에 기업 규모(company_size)가 없다"
    if kind == "소기업·소상공인 제한":
        if size in ("소기업", "소상공인"):
            return True, f"{size}: \"{s}\""
        if size == "중소기업":
            return None, f"소기업·소상공인만 참가할 수 있다. 소기업 확인서가 있는지 확인한다: \"{s}\""
        return False, f"{size}는 소기업·소상공인 제한에 해당하지 않는다: \"{s}\""
    if kind == "중소기업 제한":
        if size in ("대기업", "중견기업"):
            return False, f"{size}는 중소기업 제한 공고에 참가할 수 없다: \"{s}\""
        return True, f"{size}: \"{s}\""
    # 대기업 참여 제한
    if size == "대기업":
        return False, f"대기업 참여 제한: \"{s}\""
    if size == "중견기업":
        return (False, f"중견기업도 제한된다: \"{s}\"") if "중견" in s else (None, f"중견기업이 제한 대상인지 확인한다: \"{s}\"")
    return True, f"{size}: \"{s}\""


def _doc_checks(profile: dict[str, Any], doc: dict[str, Any] | None) -> list[tuple[str, bool | None, str]]:
    if not doc or not doc.get("read"):
        why = (doc or {}).get("error") or "공고문을 읽지 않았다"
        return [("공고문 자격 조건", None, f"{why}. 직접생산·중소기업 제한 등은 공고문으로 확인해야 한다")]
    cond = doc.get("conditions") or {}
    files = ", ".join(doc.get("files") or [])
    partial = bool(doc.get("errors") or doc.get("warnings"))
    size = profile.get("company_size")
    dp = profile.get("direct_production")
    out: list[tuple[str, bool | None, str]] = []

    def evaluate(kind: str, s: str) -> tuple[bool | None, str]:
        if kind == "직접생산":
            return _dp_check(dp, s)
        if kind == "기타 참여 제한":
            return None, f"특정 기업 유형 제한이 있다. 해당하는지 확인한다: \"{s}\""
        if kind == "공고문 기타 요건":
            return None, f"도구가 판정하지 않는 요건(실적·소재지·신용등급·인증)이 있다. 충족하는지 확인한다: \"{s}\""
        return _size_eval(kind, size, s)

    names = {"직접생산": "직접생산확인", "공고문 기타 요건": "기타 요건"}
    for kind in _COND_PATTERNS:
        res = [evaluate(kind, s) for s in cond.get(kind, [])]
        # 불명확 문장: 불충족이 나와도 '확인 필요'로 낮춘다(요건인지 확실하지 않다)
        for s in cond.get(kind + UNCLEAR, []):
            ok, why = evaluate(kind, s)
            if ok is False:
                res.append((None, "요건인지 불명확한 문장이라 확인이 필요하다. " + why))
            elif ok is None:
                res.append((None, why))
        if res:
            out.append((names.get(kind, kind), *_worst(res)))

    if not out:
        # 조건 문장을 못 찾았다고 조건이 없다고 단정하지 않는다(RED 3차 평가: 패턴 누락이 거짓 '참가 가능'을 만든다)
        out.append(("공고문 자격 조건", None,
                    f"읽은 문서({files})에서 직접생산·기업 규모 제한 문장을 찾지 못했다. 참가자격 절을 직접 확인한다"))
    elif partial:
        out = [(n, None, why + " (일부 문서를 읽지 못했거나 다른 공고 파일이 섞여 확인 필요로 낮췄다)") if ok else (n, ok, why)
               for n, ok, why in out]
    return out


# ---------------------------------------------------------------- 종합 판정

HARD_CHECKS = {"공고 상태", "자격등록 마감", "면허(업종)", "참가지역", "제한 표시", "지역의무공동도급",
               "직접생산확인", "소기업·소상공인 제한", "중소기업 제한", "대기업 참여 제한", "기타 참여 제한",
               "기타 요건", "공고문 자격 조건"}
RULES_VERSION = "2026-11-22.5"  # 판정 규칙을 바꾸면 올린다. 저장된 판정은 버전이 다르면 다시 쓰지 않는다
TIME_CHECKS = ("공고 상태", "자격등록 마감")


def judge(profile: dict[str, Any], notice: dict[str, Any], limits: list[dict[str, Any]] | str,
          regions: list[dict[str, Any]] | str, doc: dict[str, Any] | None = None,
          now: datetime | None = None) -> dict[str, Any]:
    """notice는 입찰공고 원본 항목(raw)을 넘긴다. 요약본을 넘기면 제한 플래그를 볼 수 없다."""
    now = now or now_kst()
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool | None, why: str) -> None:
        checks.append({"check": name, "result": {True: "충족", False: "불충족", None: "확인 필요"}[ok], "detail": why})

    checks.extend(time_checks(notice, now))

    if isinstance(limits, str):
        add("면허(업종)", None, limits)
    else:
        add("면허(업종)", *license_ok(profile.get("licenses") or [], limits))

    if isinstance(regions, str):
        add("참가지역", None, regions)
    else:
        allowed = sorted({r.get("prtcptPsblRgnNm", "") for r in regions if r.get("prtcptPsblRgnNm")})
        ok, why = region_ok(profile.get("region") or "", allowed)
        basis = notice.get("rgnLmtBidLocplcJdgmBssNm") or ""
        if allowed and "지사" in basis:
            why += f" (판단 기준: {basis})"
            if ok is False:
                ok = None
        add("참가지역", ok, why)

    flags = []
    if notice.get("dsgntCmptYn") == "Y":
        flags.append("지명경쟁(지명된 업체만 참가)")
    if notice.get("arsltCmptYn") == "Y":
        flags.append("실적제한경쟁")
    if notice.get("prdctClsfcLmtYn") == "Y":
        flags.append(f"세부품명 제한{(' ' + notice['dtilPrdctClsfcNoNm']) if notice.get('dtilPrdctClsfcNoNm') else ''}")
    if notice.get("bidPrtcptLmtYn") == "Y":
        flags.append("입찰참가 제한 있음")
    if flags:
        add("제한 표시", None, f"공고에 {', '.join(flags)} 표시가 있다. 공고문에서 조건을 확인한다")

    duty = [notice.get(f"jntcontrctDutyRgnNm{i}") for i in (1, 2, 3) if notice.get(f"jntcontrctDutyRgnNm{i}")]
    if duty:
        rt = notice.get("rgnDutyJntcontrctRt")
        add("지역의무공동도급", None, f"{', '.join(duty)} 업체와 공동수급해야 한다{f'(지분 {rt}% 이상)' if rt else ''}")

    for name, ok, why in _doc_checks(profile, doc):
        add(name, ok, why)

    # 참고 항목(판정에 영향 없음)
    price = notice.get("presmptPrce")
    lo, hi = profile.get("min_price"), profile.get("max_price")
    if price and (lo or hi):
        p = int(float(price))
        ok = (not lo or p >= int(lo)) and (not hi or p <= int(hi))
        rng = f"{won_kr(lo) if lo else '하한 없음'}~{won_kr(hi) if hi else '상한 없음'}"
        add("금액대(참고)", ok, f"추정가격 {won_kr(price) or price}, 선호 범위 {rng}")
    title = notice.get("bidNtceNm") or ""
    words = [w for w in profile.get("exclude_keywords") or [] if w in title]
    if words:
        add("제외 키워드(참고)", False, f"공고명에 제외 키워드 {words}")
    bt = biz_type(title)
    if bt and bt in (profile.get("exclude_types") or []):
        add("제외 사업유형(참고)", False, f"사업 유형 '{bt}'은 프로필에서 제외했다")

    return finalize(checks, notice)


def _check(name: str, ok: bool | None, why: str) -> dict[str, Any]:
    return {"check": name, "result": {True: "충족", False: "불충족", None: "확인 필요"}[ok], "detail": why}


def time_checks(notice: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    """시간이 지나면 바뀌는 항목(공고 상태, 자격등록 마감). 저장된 판정을 다시 쓸 때도 이것만은 새로 계산한다."""
    now = now or now_kst()
    out = []
    st = deadline_status(notice, now)
    if st == "취소":
        out.append(_check("공고 상태", False, f"취소공고다({notice.get('ntceKindNm')})"))
    elif st == "마감":
        out.append(_check("공고 상태", False, "입찰 마감이 지났다"))
    else:
        out.append(_check("공고 상태", True if st else None, st or "마감일 정보 없음"))
    q = notice.get("bidQlfctRgstDt")
    if q:
        try:
            qd = parse_dt(q, True)
            if qd >= now:
                out.append(_check("자격등록 마감", True, f"입찰참가자격 등록 마감 {q}"))
            else:  # 이미 그 업종으로 자격을 등록한 업체는 참가할 수 있다(SILVER 평가)
                out.append(_check("자격등록 마감", None, f"입찰참가자격 등록 마감 {q}이 지났다. 이미 등록돼 있지 않으면 참가할 수 없다"))
        except ValueError:
            pass
    return out


def refresh(saved: dict[str, Any], notice: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """저장된 판정의 시간 항목만 지금 기준으로 다시 계산하고 판정을 다시 낸다(RED 4차 평가: 낡은 '참가 가능' 방지)."""
    rest = [c for c in saved.get("checks") or [] if c["check"] not in TIME_CHECKS]
    fresh = finalize(time_checks(notice, now) + rest, notice)
    keep = {k: v for k, v in saved.items() if k not in fresh}
    return {**keep, **fresh}


def finalize(checks: list[dict[str, Any]], notice: dict[str, Any]) -> dict[str, Any]:
    hard = [c for c in checks if c["check"] in HARD_CHECKS]
    if any(c["result"] == "불충족" for c in hard):
        verdict = "참가 어려움"
    elif any(c["result"] == "확인 필요" for c in hard):
        verdict = "확인 필요"
    else:
        verdict = "참가 가능(자격 기준)"

    jv = notice.get("cmmnSpldmdMethdNm") or ""
    failed = [c["check"] for c in hard if c["result"] == "불충족"]
    if verdict == "참가 어려움":
        if "공고 상태" in failed:
            nxt = "마감됐거나 취소된 공고다. 넘긴다."
        elif any(f in failed for f in ("소기업·소상공인 제한", "중소기업 제한", "대기업 참여 제한")):
            nxt = "기업 규모 때문에 참가 대상이 아니다. 넘긴다."
        elif "직접생산확인" in failed:
            nxt = ("직접생산확인증명서가 필요하다. 공동수급이어도 구성원 각자에게 요구될 수 있다(공고문 확인). "
                   "같은 품명 공고가 자주 나오면 증명서 취득을 검토한다.")
        elif "참가지역" in failed:
            nxt = "참가 가능 지역 밖이다. 넘긴다."
        elif not jv:
            nxt = "공동수급 방식이 표시되지 않았다. 공고문으로 공동수급 허용 여부를 확인하고, 허용되지 않으면 넘긴다."
        elif "불허" in jv:
            nxt = "공동수급이 허용되지 않아 단독으로 자격을 갖춰야 한다. 넘긴다."
        elif "분담" in jv:
            nxt = "분담이행 공동수급이 허용된다. 부족한 면허를 가진 업체와 분담할 수 있는지 공고문으로 확인한다."
        else:
            nxt = (f"공동수급 방식이 '{jv}'다. 공동이행은 구성원 모두가 요건을 갖춰야 할 수 있다(공고문 확인). "
                   "대개 넘긴다.")
    elif verdict == "확인 필요":
        nxt = "'확인 필요' 항목을 공고문(read_attachment)이나 프로필 보완으로 확인한 뒤 다시 판정한다."
    else:
        nxt = "공고문에서 실적·인력 배점과 일정을 확인하고 준비한다."
    info = {k: notice.get(k) for k in ("cmmnSpldmdMethdNm", "sucsfbidMthdNm", "sucsfbidLwltRate",
                                         "techAbltEvlRt", "bidPrceEvlRt") if notice.get(k)}
    return {
        "verdict": verdict,
        "checks": checks,
        "failed_checks": failed or None,
        "next_action": nxt,
        "notice_info": info or None,
        "caution": "참고 판정이다. 최종 참가 여부는 나라장터 원문 공고로 확인한다.",
    }


# ---------------------------------------------------------------- 관심 검색

JUDGE_FILE = DATA_DIR / "judgments.json"


def load_judgments() -> dict[str, Any]:
    return _load(JUDGE_FILE, {})


def save_judgment(key: str, rec: dict[str, Any]) -> None:
    data = load_judgments()
    data[key] = rec
    if len(data) > 2000:  # 오래된 것부터 정리
        for k in sorted(data, key=lambda k: data[k].get("at", ""))[: len(data) - 2000]:
            data.pop(k)
    _save(JUDGE_FILE, data)


def list_watch() -> dict[str, Any]:
    return _load(WATCH_FILE, {})


def save_watch(data: dict[str, Any]) -> None:
    _save(WATCH_FILE, data)
