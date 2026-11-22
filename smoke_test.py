"""실호출 스모크 테스트(API 약 60~90건 사용). 사용: uv run python smoke_test.py

회사 프로필과 관심 검색은 임시 폴더에 저장해 실제 data/를 건드리지 않는다.
"""
import json
import os
import tempfile

os.environ["G2B_DATA_DIR"] = tempfile.mkdtemp(prefix="g2b-test-")
import server as s  # noqa: E402
from g2b_core import stats  # noqa: E402


def show(title, r, n=700):
    print(f"\n=== {title}\n{json.dumps(r, ensure_ascii=False)[:n]}")


r = s.search_bids(category="용역", keyword="AI,인공지능", period="이번 주", min_price="1억", open_only=True,
                  sort="마감임박", max_results=5)
show("search_bids: AI/인공지능, 이번 주, 1억 이상, 진행중, 마감임박", {k: r[k] for k in ("period", "total_count", "returned", "windows", "note")})
show("  첫 건", r["items"][0], 500)
bid = r["items"][0]["bidNtceNo"]

r2 = s.search_bids(category="전체", keyword="드론", period="최근 14일", max_results=5)
show("search_bids: 전체 업무구분, 드론, 14일(2구간)", {k: r2[k] for k in ("total_count", "returned", "windows")} | {"cats": [i["category"] for i in r2["items"]]})

d = s.get_bid(bid)
show("get_bid", {"category": d["category"], "versions": d["versions"], "status": d["notice"].get("status"),
                 "files": d["attachment_files"], "license": d["license_limits"]}, 900)

a = s.read_attachment(bid, max_chars=1500)
show("read_attachment 자동 선택", {k: a[k] for k in ("file", "files", "total_chars", "next_offset")}, 900)
print(a["text"][:600])
a2 = s.read_attachment(bid, offset=a["next_offset"] or 0, max_chars=1000)
print("  이어 읽기 offset", a2["offset"], "->", a2["next_offset"])

p = s.company_profile("set", company_name="테스트소프트", region="서울특별시 강남구",
                      licenses=["소프트웨어사업자/1468"], keywords=["AI", "데이터", "플랫폼"],
                      exclude_keywords=["유지보수"], categories=["용역"], min_price="5천만", max_price="10억")
show("company_profile set", p, 500)

e = s.check_eligibility(bid)
show("check_eligibility", {"name": e["notice"].get("bidNtceNm"), "verdict": e["verdict"], "checks": e["checks"]}, 1200)

rec = s.recommend_bids(period="최근 7일", max_results=6, check_top=3)
show("recommend_bids", {"pool": rec["pool_size"], "items": [(i.get("bidNtceNm"), i.get("status"), i.get("eligibility")) for i in rec["items"]]}, 1500)

show("watchlist add", s.watchlist("add", name="AI 용역", keyword="AI", category="용역", min_price="1억"), 300)
w1 = s.watchlist("check", name="AI 용역")
w2 = s.watchlist("check", name="AI 용역")
print("\n=== watchlist check 1회차 새 공고", w1["results"]["AI 용역"]["new_count"], "/ 2회차", w2["results"]["AI 용역"]["new_count"])
show("watchlist list", s.watchlist("list"), 300)

h = s.get_bid_change_history("용역", period="오늘", max_results=3)
show("get_bid_change_history 오늘", {"total": h["total_count"], "first": h["items"][:1]}, 400)

c = s.call_operation("getBidPblancIncntvRgnListInfo", {"inqryDiv": 1, "inqryBgnDt": "202611200000", "inqryEndDt": "202611201200", "numOfRows": 2})
show("call_operation 가산지역", c, 400)

for bad in [lambda: s.get_bid("R99XX00000000", category="용역"),
            lambda: s.search_bids(min_price="많이"),
            lambda: s.read_attachment(bid, file="없는파일이름")]:
    try:
        bad()
    except Exception as ex:
        print("\n=== 오류 처리:", type(ex).__name__, str(ex)[:160])

print("\n=== API 사용량", stats)
