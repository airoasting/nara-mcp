"""API 호출 없는 단위 테스트. 사용: uv run python test_offline.py"""
from datetime import datetime

import company as co
from g2b_core import parse_period, parse_won, windows

NOW = datetime(2026, 11, 22, 19, 30)


def eq(a, b, msg=""):
    assert a == b, f"{msg}: {a!r} != {b!r}"


# 금액
for s, v in [("5억", 500_000_000), ("1.5억", 150_000_000), ("3천만원", 30_000_000), ("1억5천만", 150_000_000),
             ("1억 5천", 150_000_000), ("3,000만원", 30_000_000), ("500만", 5_000_000), (300000000, 300000000),
             ("120000000", 120_000_000), ("2억3천500만원", 235_000_000)]:
    eq(parse_won(s), v, f"parse_won({s})")
try:
    parse_won("많이")
    raise AssertionError("parse_won('많이')는 실패해야 한다")
except ValueError:
    pass

# 기간
eq(parse_period("오늘", NOW)[0], datetime(2026, 11, 22), "오늘")
eq(parse_period("이번 주", NOW)[0], datetime(2026, 11, 16), "이번 주(월요일 시작)")
eq(parse_period("지난주", NOW), (datetime(2026, 11, 9), datetime(2026, 11, 15, 23, 59)), "지난주")
eq(parse_period("지난달", NOW), (datetime(2026, 10, 1), datetime(2026, 10, 31, 23, 59)), "지난달")
eq(parse_period("최근 7일", NOW)[0], datetime(2026, 11, 16), "최근 7일")

# 7일 구간 분할: 날짜 기준 7일, 구간 사이 빈틈 없음
ws = windows(datetime(2026, 10, 20), NOW)
eq(ws[0], (datetime(2026, 11, 16), NOW), "첫 구간")
eq(ws[1], (datetime(2026, 11, 9), datetime(2026, 11, 15, 23, 59)), "둘째 구간")
eq(ws[-1][0], datetime(2026, 10, 20), "마지막 구간 시작")

# 지역
eq(co.region_ok("경기도 성남시", [])[0], True, "제한 없음")
eq(co.region_ok("경기 성남시", ["경기도"])[0], True, "약칭")
eq(co.region_ok("경상북도 경산시", ["경상북도 경산시"])[0], True, "시군구 일치")
eq(co.region_ok("경상북도 포항시", ["경상북도 경산시"])[0], False, "시군구 불일치")
eq(co.region_ok("서울특별시 강남구", ["경기도", "인천광역시"])[0], False, "다른 시도")
eq(co.region_ok("", ["경기도"])[0], None, "프로필 지역 없음")

# 면허: 그룹 사이 OR, 그룹 안 AND, 허용업종 인정
med = [{"lmtGrpNo": "1", "lcnsLmtNm": "의료기기제조업/5309", "permsnIndstrytyList": ""},
       {"lmtGrpNo": "3", "lcnsLmtNm": "의료기기판매업/5312", "permsnIndstrytyList": "[의약품판매업(의약품도매상)/5307],[약국/5332]"}]
eq(co.license_ok(["약국/5332"], med)[0], True, "허용업종으로 충족")
eq(co.license_ok(["5309"], med)[0], True, "코드만으로 충족")
eq(co.license_ok(["소프트웨어사업자/1468"], med)[0], False, "불충족")
both = [{"lmtGrpNo": "1", "lcnsLmtNm": "종합여행업/1261", "permsnIndstrytyList": ""},
        {"lmtGrpNo": "1", "lcnsLmtNm": "국내외여행업/1262", "permsnIndstrytyList": "[종합여행업/1261]"}]
eq(co.license_ok(["종합여행업/1261"], both)[0], True, "같은 그룹 AND, 허용업종 포함")
eq(co.license_ok(["국내외여행업/1262"], both)[0], False, "같은 그룹 AND 불충족")
eq(co.license_ok([], both)[0], None, "프로필 면허 없음")

print("offline tests: all passed")
