"""나라장터 입찰공고정보서비스 호출, 날짜와 금액 해석, 응답 가공.

MCP와 무관한 순수 로직만 둔다. server.py가 이 모듈을 감싼다.
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from urllib.parse import unquote

import httpx

BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService02"
# 서비스별 (주소, 오퍼레이션 접미사, 활용신청 페이지). 접미사는 공식 swagger basePath 기준.
SERVICES = {
    "bid": (BASE_URL, "02", "https://www.data.go.kr/data/15129394/openapi.do"),
    "award": ("https://apis.data.go.kr/1230000/as/ScsbidInfoService", "", "https://www.data.go.kr/data/15129397/openapi.do"),
}
SERVICE_NAMES = {"bid": "조달청_나라장터 입찰공고정보서비스", "award": "조달청_나라장터 낙찰정보서비스"}
KST = timezone(timedelta(hours=9))

# 요청 URL에 인증키가 들어가므로 httpx 요청 로그를 끈다.
logging.getLogger("httpx").setLevel(logging.WARNING)

# 조회기간 상한. 2026-11-10 공지로 1개월에서 7일로 줄었다.
# 시각이 아니라 날짜 기준으로 세며 시작일과 종료일을 모두 포함해 7일까지 된다(실측).
MAX_DAYS = 7
MAX_WINDOWS = 5  # 한 번의 검색에서 자동 분할할 최대 구간 수(약 35일)
CACHE_TTL = 1800  # 같은 요청은 30분 동안 다시 부르지 않는다(브리핑·검토·시세 조회가 한도 안에 들도록)

CAT_CODE: dict[str, str] = {
    "물품": "Thng",
    "공사": "Cnstwk",
    "용역": "Servc",
    "외자": "Frgcpt",
    "기타": "Etc",
}
CAT_ALIASES = {
    "서비스": "용역", "sw": "용역", "소프트웨어": "용역", "컨설팅": "용역",
    "건설": "공사", "시설": "공사", "구매": "물품", "제품": "물품",
    "해외": "외자", "국외": "외자",
}
SEARCH_ORDER = ["용역", "물품", "공사", "외자", "기타"]

SUMMARY_FIELDS = [
    "bidNtceNo", "bidNtceOrd", "ntceKindNm", "bidNtceNm",
    "ntceInsttNm", "dminsttNm", "cntrctCnclsMthdNm", "sucsfbidMthdNm",
    "presmptPrce", "asignBdgtAmt", "bidNtceDt", "bidClseDt", "opengDt",
    "mainCnsttyNm", "srvceDivNm", "bidNtceDtlUrl",
    # 실무 필드(SILVER 평가 반영): 낙찰하한율, 평가 비율, 공동수급 방식, 자격등록 마감, 예가 방식, 사전규격, 재공고
    "sucsfbidLwltRate", "techAbltEvlRt", "bidPrceEvlRt", "cmmnSpldmdMethdNm", "bidQlfctRgstDt",
    "prearngPrceDcsnMthdNm", "bfSpecRgstNo", "reNtceYn",
]

ERROR_HINTS = {
    "01": "나라장터 서버 일시 오류(시간 초과 포함). 잠시 후 다시 시도하거나 조회기간을 줄인다.",
    "03": "조회 결과가 없다. 공고번호 오타, 업무구분(물품·공사·용역·외자·기타)을 확인한다. 검색이면 기간을 늘리거나 키워드를 줄인다.",
    "07": "입력 범위 초과. 조회기간은 날짜 기준 7일 이내여야 하고 numOfRows는 999 이하로 둔다.",
    "08": "필수값 누락. 상세 조회는 공고번호와 차수(bidNtceOrd)가 모두 필요하다.",
    "12": "오퍼레이션 이름이 틀렸거나 폐기됐다. call_operation 설명의 오퍼레이션 목록에서 이름을 확인한다.",
    "22": "일일 호출 한도 초과(개발계정 트래픽 1,000건). 자정 이후 다시 시도하거나 운영계정을 신청한다.",
    "30": "등록되지 않은 인증키. 이 서비스를 활용신청했는지, 발급 직후라면 1~2시간 지났는지 확인한다.",
    "31": "인증키 활용기간이 끝났다. 공공데이터포털 마이페이지에서 활용기간 연장을 신청한다.",
}


# ---------------------------------------------------------------- 호출

def load_key() -> str:
    return _normalize_key(_raw_key())


def _raw_key() -> str:
    key = os.environ.get("G2B_SERVICE_KEY", "").strip()
    if key and not key.startswith("${"):  # 플러그인 설정이 비었을 때 '${user_config...}'가 그대로 올 수 있다
        return key
    key = ""
    env = Path(__file__).with_name(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("G2B_SERVICE_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not key:
        raise RuntimeError(
            f"인증키가 없다. {env} 파일에 'G2B_SERVICE_KEY=발급받은키' 한 줄을 넣고 Claude를 다시 시작한다. "
            "플러그인으로 설치했다면 /plugin configure에서 키를 넣는다."
        )
    return key


def _normalize_key(key: str) -> str:
    """공공데이터포털이 보여 주는 '인코딩' 키(%2B, %3D 포함)를 넣어도 동작하게 한 번 디코딩한다."""
    return unquote(key) if "%" in key else key


class G2BError(Exception):
    def __init__(self, code: str, msg: str):
        self.code = code
        super().__init__(f"[{code}] {msg} {ERROR_HINTS.get(code, '')}".strip())


_client = httpx.Client(timeout=httpx.Timeout(30.0))
_cache: dict[tuple, tuple[float, dict[str, Any]]] = {}
stats = {"api_calls": 0, "cache_hits": 0}


def call(operation: str, params: dict[str, Any], retries: int = 2, service: str = "bid") -> dict[str, Any]:
    """오퍼레이션을 호출하고 body(items, totalCount, pageNo, numOfRows)를 돌려준다.

    service: "bid"(입찰공고정보서비스) 또는 "award"(낙찰정보서비스).
    """
    base_url, suffix, apply_url = SERVICES[service]
    if suffix and not operation.endswith(suffix):
        operation += suffix
    q = {k: v for k, v in params.items() if v not in (None, "")}
    q.setdefault("pageNo", 1)
    q.setdefault("numOfRows", 10)
    q["type"] = "json"

    ck = (service, operation, tuple(sorted((k, str(v)) for k, v in q.items())))
    hit = _cache.get(ck)
    if hit and time.time() - hit[0] < CACHE_TTL:
        stats["cache_hits"] += 1
        return hit[1]

    q["serviceKey"] = load_key()
    last: G2BError | None = None
    for attempt in range(retries + 1):
        stats["api_calls"] += 1
        try:
            data = _client.get(f"{base_url}/{operation}", params=q).json()
        except (httpx.HTTPError, ValueError) as e:
            last = G2BError("01", f"응답을 읽지 못했다({type(e).__name__}).")
        else:
            if "response" in data:
                head = data["response"].get("header", {})
                code = str(head.get("resultCode", ""))
                if code == "00":
                    body = data["response"].get("body") or {}
                    items = body.get("items") or []
                    if isinstance(items, dict):  # 건수가 1일 때 dict로 오는 경우 대비
                        items = items.get("item", items)
                        items = items if isinstance(items, list) else [items]
                    body["items"] = items
                    _cache[ck] = (time.time(), body)
                    return body
                last = G2BError(code, head.get("resultMsg", ""))
            elif "OpenAPI_ServiceResponse" in data:
                h = data["OpenAPI_ServiceResponse"].get("cmmMsgHeader", {})
                last = G2BError(str(h.get("returnReasonCode", "")), h.get("returnAuthMsg", ""))
            else:
                err = next(iter(data.values()), {}) if isinstance(data, dict) else {}
                h = err.get("header", {}) if isinstance(err, dict) else {}
                last = G2BError(str(h.get("resultCode", "??")), h.get("resultMsg", str(data)[:200]))
        if last.code != "01":
            break  # 재시도해도 바뀌지 않는 오류
        time.sleep(1.0 * (attempt + 1))
    if last and last.code == "30":
        raise G2BError("30", f"이 인증키는 '{SERVICE_NAMES[service]}'에 등록돼 있지 않다. "
                             f"공공데이터포털에서 활용신청한다(개발계정 자동승인): {apply_url}")
    raise last  # type: ignore[misc]


# ---------------------------------------------------------------- 날짜

def now_kst() -> datetime:
    return datetime.now(KST).replace(tzinfo=None, second=0, microsecond=0)


def parse_dt(s: str, end: bool) -> datetime:
    s = s.strip().replace("-", "").replace(".", "").replace("/", "").replace(":", "")
    s = s.replace(" ", "").replace("T", "")
    if len(s) == 8:
        d = datetime.strptime(s, "%Y%m%d")
        return d.replace(hour=23, minute=59) if end else d
    if len(s) == 12:
        return datetime.strptime(s, "%Y%m%d%H%M")
    if len(s) == 14:
        return datetime.strptime(s, "%Y%m%d%H%M%S").replace(second=0)
    raise ValueError(f"날짜 형식 오류: {s!r}. YYYY-MM-DD 또는 YYYYMMDDHHMM 으로 넣는다.")


def fmt(d: datetime) -> str:
    return d.strftime("%Y%m%d%H%M")


def window_start(end: datetime) -> datetime:
    """end가 속한 날짜를 포함해 7일째 되는 날의 00:00."""
    return (end - timedelta(days=MAX_DAYS - 1)).replace(hour=0, minute=0)


def windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """최신 구간부터 API 한도(날짜 기준 7일) 안의 구간으로 나눈다."""
    out = []
    cur_end = end
    while cur_end > start and len(out) < MAX_WINDOWS:
        cur_start = max(start, window_start(cur_end))
        out.append((cur_start, cur_end))
        cur_end = cur_start - timedelta(minutes=1)
    return out


def parse_period(text: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """'오늘', '어제', '이번 주', '지난주', '이번 달', '지난달', '최근 30일', '2주', '3개월' 같은 말을 기간으로 바꾼다."""
    now = now or now_kst()
    t = text.replace(" ", "")
    today = now.replace(hour=0, minute=0)
    if t in ("오늘", "today"):
        return today, now
    if t in ("어제", "yesterday"):
        y = today - timedelta(days=1)
        return y, y.replace(hour=23, minute=59)
    if t in ("이번주", "금주"):
        return today - timedelta(days=today.weekday()), now
    if t in ("지난주", "저번주"):
        s = today - timedelta(days=today.weekday() + 7)
        return s, (s + timedelta(days=6)).replace(hour=23, minute=59)
    if t in ("이번달", "금월"):
        return today.replace(day=1), now
    if t in ("지난달", "저번달"):
        first = today.replace(day=1)
        last = first - timedelta(minutes=1)
        return last.replace(day=1, hour=0, minute=0), last
    m = re.fullmatch(r"(?:최근|지난)?(\d+)(일|주|개월|달)(?:간|동안)?", t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if n < 1:
            raise ValueError("기간은 1 이상이어야 한다. 예: '최근 7일'")
        days = n if unit == "일" else n * 7 if unit == "주" else n * 30
        return today - timedelta(days=days - 1), now
    raise ValueError(f"기간 표현을 이해하지 못했다: {text!r}. 예: '최근 7일', '이번 주', '지난달'")


def resolve_range(period: str | None, start: str | None, end: str | None) -> tuple[datetime, datetime]:
    if period:
        return parse_period(period)
    end_dt = parse_dt(end, True) if end else now_kst()
    start_dt = parse_dt(start, False) if start else window_start(end_dt)
    if start_dt >= end_dt:
        raise ValueError("start가 end보다 늦다.")
    return start_dt, end_dt


# ---------------------------------------------------------------- 금액

_SMALL = {"천": 1000, "백": 100, "십": 10}


def _parse_small(t: str) -> float:
    """'2천5백', '3', '1.5' 같은 만 단위 미만 묶음을 숫자로 바꾼다. 빈 문자열은 1('만원' = 1만원)."""
    if t == "":
        return 1
    total, pos = 0.0, 0
    for m in re.finditer(r"(\d+(?:\.\d+)?)?(천|백|십)?", t):
        if m.end() == m.start():
            continue
        if m.start() != pos or (m.group(1) is None and m.group(2) is None):
            raise ValueError(t)
        num = float(m.group(1)) if m.group(1) else 1.0
        total += num * _SMALL.get(m.group(2), 1)
        pos = m.end()
    if pos != len(t):
        raise ValueError(t)
    return total


def parse_won(v: Any) -> int | None:
    """금액 표현을 원 단위 정수로 바꾼다.

    '5억', '1.5억', '3천만원', '2천5백만원', '1억5천만', '1억 5천'(=1억5천만), '3,000만원', 300000000.
    억·만 없이 '5천', '3백'만 쓰면 조달 금액 관행에 따라 만원 단위(5천만원, 3백만원)로 읽는다.
    """
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).replace(",", "").replace(" ", "")
    explicit_won = s.endswith("원")
    s = s.rstrip("원")
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return int(float(s))
    try:
        total = 0.0
        rest = s
        had_eok = "억" in rest
        if had_eok:
            left, rest = rest.split("억", 1)
            total += _parse_small(left) * 100_000_000
        if "만" in rest:
            left, rest = rest.split("만", 1)
            total += _parse_small(left) * 10_000
            if rest:
                total += _parse_small(rest)
        elif rest:
            small = _parse_small(rest)
            # '1억5천'처럼 억 뒤에 만이 빠졌거나, '5천'처럼 단위 없이 천·백만 쓴 경우는 만원 단위로 본다
            if had_eok or (re.search(r"[천백십]$", rest) and not explicit_won):
                small *= 10_000
            total += small
    except ValueError:
        raise ValueError(f"금액 표현을 이해하지 못했다: {v!r}. 예: '5억', '3천만원', '2천5백만원', 300000000") from None
    if total <= 0:
        raise ValueError(f"금액 표현을 이해하지 못했다: {v!r}. 예: '5억', '3천만원', 300000000")
    return int(round(total))


def won_kr(v: Any) -> str | None:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    if n >= 100_000_000:
        return f"{n / 100_000_000:,.2f}억원"
    if n >= 10_000:
        return f"{n / 10_000:,.0f}만원"
    return f"{n:,}원"


# ---------------------------------------------------------------- 가공

def normalize_category(c: str | None) -> str | None:
    if not c:
        return None
    c = c.strip()
    c = CAT_ALIASES.get(c.lower(), c)
    if c not in CAT_CODE:
        raise ValueError(f"업무구분은 {', '.join(CAT_CODE)} 중 하나다(받은 값: {c!r}).")
    return c


def is_canceled(item: dict[str, Any]) -> bool:
    return "취소" in (item.get("ntceKindNm") or "")


def deadline_status(item: dict[str, Any], now: datetime | None = None) -> str | None:
    """'진행중 D-5', '오늘 마감', '마감', '취소'. 취소공고는 마감일이 남아 있어도 '취소'다."""
    if is_canceled(item):
        return "취소"
    s = item.get("bidClseDt")
    if not s:
        return None
    try:
        close = parse_dt(s, True)
    except ValueError:
        return None
    now = now or now_kst()
    if close < now:
        return "마감"
    days = (close.date() - now.date()).days
    return "오늘 마감" if days == 0 else f"진행중 D-{days}"


BIZ_TYPES = {  # 공고명으로 사업 성격을 추정한다. 참고용 분류다.
    "감리": ["감리"],
    "운영·유지관리": ["유지관리", "유지보수", "운영", "운용", "위탁"],
    "컨설팅·계획": ["컨설팅", "ISP", "ISMP", "BPR", "계획 수립", "계획수립", "전략"],
    "연구": ["연구용역", "연구", "조사"],
    "구축·개발": ["구축", "개발", "고도화", "전환", "도입", "시작품", "보안 강화"],
    "콘텐츠·홍보": ["홍보", "영상", "콘텐츠", "행사", "디자인"],
}
_WEAK_BUILD = ["시스템", "플랫폼", "솔루션"]  # 다른 유형이 없을 때만 구축·개발로 본다
_NOT_OPERATE = re.compile(r"운영\s*(?:환경|체계|체제|모델|방안\s*수립)")


def biz_type(title: str | None) -> str | None:
    """공고명에서 가장 뒤에 나오는 유형어를 고른다('AI운영환경 … 개발 용역' → 구축·개발, '플랫폼 운영 용역' → 운영·유지관리).

    감리는 어디에 있든 감리다. '운영환경·운영체계'의 '운영'은 운영 사업이 아니다. '구축 위탁'의 '위탁'은 구축을 앞서지 않는다.
    """
    t = _NOT_OPERATE.sub(" ", title or "")
    if "감리" in t:
        return "감리"
    best, pos = None, -1
    for name, words in BIZ_TYPES.items():
        for w in words:
            i = t.rfind(w)
            if i < 0:
                continue
            if w == "위탁" and any(x in t for x in ("구축", "개발")):
                continue
            if i > pos:
                best, pos = name, i
    if best:
        return best
    return "구축·개발" if any(w in t for w in _WEAK_BUILD) else None


def keyword_hit(keyword: str, title: str | None) -> bool:
    """영문 키워드는 단어 단위로 맞춘다('AI'가 'LPAI'에 걸리지 않게). 한글은 부분 일치."""
    t = title or ""
    if re.fullmatch(r"[A-Za-z0-9]+", keyword):
        return re.search(rf"(?<![A-Za-z]){re.escape(keyword)}(?![A-Za-z])", t, re.I) is not None
    return keyword in t


def latest_versions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 공고번호는 가장 높은 차수만 남긴다(정정 전 조건으로 판정하지 않게)."""
    best: dict[str, dict[str, Any]] = {}
    for it in items:
        no = it.get("bidNtceNo")
        if no not in best or (it.get("bidNtceOrd") or "") > (best[no].get("bidNtceOrd") or ""):
            best[no] = it
    return list(best.values())


def clean(item: dict[str, Any]) -> dict[str, Any]:
    """빈 값 제거, 첨부파일 10쌍을 리스트로 묶는다."""
    out: dict[str, Any] = {}
    files = []
    for i in range(1, 11):
        url, name = item.get(f"ntceSpecDocUrl{i}"), item.get(f"ntceSpecFileNm{i}")
        if url:
            files.append({"index": i, "name": name or f"첨부{i}", "url": url})
    for k, v in item.items():
        if k.startswith(("ntceSpecDocUrl", "ntceSpecFileNm")):
            continue
        if v not in ("", None):
            out[k] = v.strip() if isinstance(v, str) else v
    if files:
        out["attachments"] = files
    for f in ("presmptPrce", "asignBdgtAmt"):
        if (w := won_kr(item.get(f))):
            out[f + "_kr"] = w
    if (st := deadline_status(item)):
        out["status"] = st
    return out


def summary(item: dict[str, Any], category: str | None = None) -> dict[str, Any]:
    s = {k: item[k].strip() if isinstance(item[k], str) else item[k]
         for k in SUMMARY_FIELDS if item.get(k) not in ("", None)}
    if category:
        s["category"] = category
    if (w := won_kr(item.get("presmptPrce"))):
        s["presmptPrce_kr"] = w
    if (st := deadline_status(item)):
        s["status"] = st
    if (bt := biz_type(item.get("bidNtceNm"))):
        s["biz_type"] = bt
    return s
