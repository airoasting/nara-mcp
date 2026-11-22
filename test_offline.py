"""API 호출 없는 단위 테스트. 사용: uv run python test_offline.py"""
from datetime import datetime

import company as co
from g2b_core import parse_period, parse_won, windows

NOW = datetime(2026, 11, 22, 19, 30)


CHECKS = 0


def eq(a, b, msg=""):
    global CHECKS
    CHECKS += 1
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

# ---------------------------------------------------------------- 2차 개선 회귀 시험(4인 평가에서 나온 거짓 양성)
from g2b_core import keyword_hit, latest_versions, biz_type  # noqa: E402
import attachments as att  # noqa: E402

for s_, v in [("2천5백만원", 25_000_000), ("5천", 50_000_000), ("5천원", 5_000), ("만원", 10_000)]:
    eq(parse_won(s_), v, f"parse_won({s_})")
try:
    parse_period("0일", NOW)
    raise AssertionError("0일은 실패해야 한다")
except ValueError:
    pass

# 지역: 통합 지역명, 해석 못 하면 확인 필요(None)
eq(co.region_ok("전남광주통합특별시 서구", ["전남광주통합특별시 동구"])[0], False, "통합시 다른 구")
eq(co.region_ok("전남광주통합특별시 동구", ["전남광주통합특별시 동구"])[0], True, "통합시 같은 구")
eq(co.region_ok("전라남도 여수시", ["전남광주통합특별시 순천시"])[0], None, "통합 전후 이름 혼재")
eq(co.region_ok("광주광역시 동구", ["전남광주통합특별시 동구"])[0], None, "광주 → 통합시")
eq(co.region_ok("어딘가 시", ["경기도"])[0], None, "해석 못 한 소재지")
eq(co.region_ok("경기도", ["경기도 성남시"])[0], None, "프로필 시군구 없음")

# 면허: 빈 이름끼리 맞지 않음, 이름만 저장하면 확인 필요
empty = [{"lmtGrpNo": "1", "lcnsLmtNm": "", "permsnIndstrytyList": ""}]
eq(co.license_ok(["/1468"], empty)[0], False, "빈 이름 매칭 금지")
sw = [{"lmtGrpNo": "1", "lcnsLmtNm": "소프트웨어사업자(컴퓨터관련서비스사업)/1468", "permsnIndstrytyList": ""}]
eq(co.license_ok(["SW사업자"], sw)[0], None, "이름만 저장 → 확인 필요")
eq(co.license_ok(["소프트웨어사업자/1468"], sw)[0], True, "코드 일치")

# 판정: 취소공고, 제한 플래그, 공고문 미확인, 직접생산
base_notice = {"bidNtceNo": "R26BK00000001", "bidNtceOrd": "001", "bidNtceNm": "AI 플랫폼 구축",
               "bidClseDt": "2026-12-01 10:00:00"}
prof = {"region": "경기도 성남시", "licenses": ["소프트웨어사업자/1468"], "company_size": "중소기업",
        "direct_production": []}
doc_ok = {"read": True, "files": ["제안요청서.hwp"], "conditions": {"중소기업 제한": ["참가자격: 중소기업자로 제한한다"]}}
j = co.judge(prof, {**base_notice, "ntceKindNm": "취소공고"}, sw, [], doc_ok, now=NOW)
eq(j["verdict"], "참가 어려움", "취소공고")
j = co.judge(prof, base_notice, sw, [], doc_ok, now=NOW)
eq(j["verdict"], "참가 가능(자격 기준)", "정상 공고")
j = co.judge(prof, base_notice, sw, [], None, now=NOW)
eq(j["verdict"], "확인 필요", "공고문 미확인이면 참가 가능 금지")
j = co.judge(prof, {**base_notice, "arsltCmptYn": "Y"}, sw, [], doc_ok, now=NOW)
eq(j["verdict"], "확인 필요", "실적제한 표시")
j = co.judge(prof, {**base_notice, "bidQlfctRgstDt": "2026-11-20 18:00"}, sw, [], doc_ok, now=NOW)
eq(j["verdict"], "확인 필요", "자격등록 마감 지남(이미 등록한 업체는 가능)")
text = "입찰참가자격\n직접생산확인증명서[정보시스템개발서비스(8111159901)]를 소지한 자\n중소기업기본법에 따른 중소기업자로 제한"
cond = co.scan_conditions(text)
assert "직접생산" in cond and "중소기업 제한" in cond, cond
doc = {"read": True, "files": ["공고문.pdf"], "conditions": cond, "qualification_section": True}
eq(co.judge(prof, base_notice, sw, [], doc, now=NOW)["verdict"], "참가 어려움", "직접생산 없음(GOLD 거짓 양성)")
eq(co.judge({**prof, "direct_production": ["정보시스템개발서비스"]}, base_notice, sw, [], doc, now=NOW)["verdict"],
   "참가 가능(자격 기준)", "직접생산 보유")
eq(co.judge({**prof, "direct_production": None}, base_notice, sw, [], doc, now=NOW)["verdict"], "확인 필요", "직접생산 모름")
eq(co.judge({**prof, "company_size": "대기업", "direct_production": ["정보시스템개발서비스"]}, base_notice, sw, [], doc,
            now=NOW)["verdict"], "참가 어려움", "중소기업 제한에 대기업")

# 키워드 단어 단위, 최신 차수, 사업 유형
eq(keyword_hit("AI", "국내 육계 IB, LPAI(H9N2) 실태조사"), False, "AI ⊄ LPAI")
eq(keyword_hit("AI", "생성형 AI 플랫폼"), True, "AI 단어")
eq([v["bidNtceOrd"] for v in latest_versions([{"bidNtceNo": "A", "bidNtceOrd": "000"}, {"bidNtceNo": "A", "bidNtceOrd": "001"}])], ["001"], "최신 차수")
eq(biz_type("마이데이터 통합 플랫폼 운영 용역"), "운영·유지관리", "운영")
eq(biz_type("정보시스템 감리"), "감리", "감리")

# HWPX 표 텍스트 중복 제거: 바깥 문단 run 아래 표 안의 문단이 중첩된 구조
ns = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'
xml = (f'<sec {ns}><hp:p><hp:run><hp:t>제목</hp:t></hp:run></hp:p>'
       f'<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>셀내용</hp:t></hp:run></hp:p>'
       f'</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p></sec>').encode()
eq(att._hwpx_section_text(xml).count("셀내용"), 1, "HWPX 표 중복")
eq(att.foreign_bid_numbers("R26BK01843717", "R26BK01845527_국가과학기술연구회.pdf", ""), ["R26BK01845527"], "다른 공고 파일")
eq(att.foreign_bid_numbers("R26BK01843717", "제안요청서.hwp", "공고번호 R26BK01843717"), [], "같은 공고")

print("regression tests: all passed")

# ---------------------------------------------------------------- 3차 개선 회귀 시험(2차 평가에서 나온 경로)
def verdict_for(text, **pf):
    d = {"read": True, "files": ["공고문.hwp"], "conditions": co.scan_conditions(text),
         "qualification_section": co.has_qualification_section(text)}
    return co.judge({**prof, **pf}, base_notice, sw, [], d, now=NOW)["verdict"]

# RED: 법령명에 '중소기업'이 들어간 소기업·소상공인 제한(R26BK01843994 문장)
s43994 = "입찰참가자격\n「중소기업제품 구매촉진 및 판로지원에 관한 법률」에 따른 <소기업·소상공인>으로 관련 확인서를 갖춘 업체"
eq(verdict_for(s43994, direct_production=["정보시스템개발서비스"]), "확인 필요", "소기업 제한 + 중소기업 프로필")
eq(verdict_for(s43994, company_size="소기업", direct_production=["정보시스템개발서비스"]), "참가 가능(자격 기준)", "소기업 프로필")
# 놓치던 표현 6종
for t in ["참가자격: 소기업 또는 소상공인으로 제한한다", "소상공인만 참여할 수 있다", "대기업 및 중견기업은 참여할 수 없음",
          "상호출자제한기업집단 소속 기업은 참가할 수 없다", "여성기업으로 참가를 제한한다", "사회적기업만 참여 가능하다"]:
    assert co.scan_conditions(t), f"패턴 누락: {t}"
# 311자 한 줄
long = "입찰참가자격 " + "가" * 280 + " 직접생산확인증명서를 소지한 자로 한다"
assert "직접생산" in co.scan_conditions(long), "긴 줄 누락"
# 부정문, 계약 이행 상투 문구, 제출 서류 목록은 요건이 아니다(GOLD)
# 부정문·이행 조항·제출 서류는 확정 요건이 아니라 '불명확'으로만 남고, '참가 어려움'을 만들지 않는다(GOLD 2차, RED 3차)
definitive = lambda c: [k for k in c if not k.endswith(co.UNCLEAR)]  # noqa: E731
eq(definitive(co.scan_conditions("이 물품은 중소기업자간 경쟁제품이 아닙니다")), [], "부정문")
boiler = "계약담당공무원은 계약상대자가 직접생산 확인기준을 위반한 사실을 확인한 경우 계약을 해지할 수 있다"
eq(definitive(co.scan_conditions(boiler)), [], "이행 문구")
eq(definitive(co.scan_conditions("9) 중·소기업·소상공인 확인서 1부")), [], "제출 서류")
eq(verdict_for(boiler) != "참가 어려움", True, "이행 문구로 탈락 금지")
eq(verdict_for("이 물품은 중소기업자간 경쟁제품이 아닙니다", company_size="대기업") != "참가 어려움", True, "부정문으로 탈락 금지")
# 조건을 못 찾으면: 참가자격 부분이 있으면 충족, 없으면 확인 필요, 일부 실패면 확인 필요(RED)
eq(verdict_for("입찰참가자격: 소프트웨어사업자로 등록한 자"), "확인 필요", "조건 문장 미발견은 확인 필요(4차)")
eq(verdict_for("과업 내용: 시스템 구축"), "확인 필요", "참가자격 부분 없음")
d_partial = {"read": True, "files": ["a"], "conditions": {}, "qualification_section": True, "errors": ["b.hwp: Error"]}
eq(co.judge(prof, base_notice, sw, [], d_partial, now=NOW)["verdict"], "확인 필요", "일부 문서 실패")
d_warn = {"read": True, "files": ["a"], "conditions": {}, "qualification_section": True, "warnings": ["다른 공고"]}
eq(co.judge(prof, base_notice, sw, [], d_warn, now=NOW)["verdict"], "확인 필요", "다른 공고 파일 경고")
# 직접생산: 여러 품명이 나열되면 하나만 가져서는 확인 필요
eq(verdict_for("참가자격: 의자(5612150101), 책상(5612170101), 사물함(5612159901)에 대한 직접생산확인증명서를 소지한 자",
               direct_production=["의자"]), "확인 필요", "여러 품명 중 하나")
eq(verdict_for("참가자격: 직접생산증명서[소프트웨어 유지 및 지원 서비스, 정보시스템 유지관리서비스] 중 1개 이상 소지한 업체",
               direct_production=["정보시스템 유지관리서비스"]), "참가 가능(자격 기준)", "1개 이상 중 보유")
# 중견기업과 대기업 참여 제한
eq(verdict_for("참가자격: 대기업인 소프트웨어사업자의 참여를 제한한다", company_size="중견기업",
               direct_production=["x"]), "확인 필요", "중견기업 불명확")
eq(verdict_for("참가자격: 대기업 및 중견기업은 참여할 수 없음", company_size="중견기업"), "참가 어려움", "중견기업 명시")
# 지역: 경기도 광주시
eq(co.region_ok("광주시 오포읍", ["광주광역시"])[0], None, "경기도 광주시 별칭")
# 원인별 다음 행동
eq(co.judge(prof, {**base_notice, "ntceKindNm": "취소공고"}, sw, [], doc_ok, now=NOW)["next_action"],
   "마감됐거나 취소된 공고다. 넘긴다.", "취소 next_action")
c = co.scan_conditions("참가자격: 중소기업·소상공인으로 제한한다")
assert "중소기업 제한" in c and "소기업·소상공인 제한" not in c, c
eq(verdict_for("참가자격: 중소기업·소상공인으로 제한한다", direct_production=["x"]), "참가 가능(자격 기준)", "중소기업·소상공인 = 중소기업 제한")
print("round3 regression: all passed")

# ---------------------------------------------------------------- 4차 개선 회귀 시험(RED 3차 재현 9종)
big = dict(company_size="대기업", direct_production=["x"])
eq(verdict_for("소기업·소상공인 확인서 사본을 제출한 업체로 참가자격을 제한함", direct_production=["x"]), "확인 필요", "사본 문구의 진짜 요건")
eq(verdict_for("대기업인 소프트웨어사업자는 참여할 수 없다(다만 국방·외교 사업에 해당하지 않는 경우)", **big), "확인 필요", "예외 단서")
eq(verdict_for("제출 서류: 직접생산확인증명서 사본 1부"), "확인 필요", "제출 서류의 직접생산(dp 없음)")
eq(verdict_for("중소기업 확인서를 소지한 업체", **big), "확인 필요", "패턴 누락 → 확인 필요")
eq(verdict_for("참가자격: 의자, 책상, 사물함은 직접생산확인증명서를 소지한 업체로 한다", direct_production=["의자"]), "확인 필요", "품명 나열")
eq(verdict_for("나. 중소기업으로 확인된 업체는 하도급 계획서 제출을 면제한다", company_size="중견기업", direct_production=["x"]) != "참가 어려움",
   True, "하도급 면제 문장으로 탈락 금지")
c = co.scan_conditions("참가자격: 중·소기업 또는 소상공인으로 제한한다")
assert "중소기업 제한" in c and "소기업·소상공인 제한" not in c, c
c = co.scan_conditions("참가자격: 중소기업기본법 제2조에 따른 중소기업자로서 직접생산확인증명서를 소지한 자")
assert "중소기업 제한" in c and "직접생산" in c, c
eq(co.judge(prof, {**base_notice, "cmmnSpldmdMethdNm": "(분담이행)공동수급"}, [{"lmtGrpNo": "1", "lcnsLmtNm": "정보통신공사업/0036"}],
            [], doc_ok, now=NOW)["next_action"].startswith("분담이행"), True, "분담이행이면 면허 보완 안내")
print("round4 regression: all passed")

# ---------------------------------------------------------------- 5차(마지막 정리) 회귀 시험
# GOLD 4차: 가운뎃점 변형 '중․소기업'은 소기업 한정이 아니다
c = co.scan_conditions("참가자격: 중․소기업 소상공인확인서를 소지한 업체")
assert "소기업·소상공인 제한" not in c and "소기업·소상공인 제한" + co.UNCLEAR not in c, c
# RED 4차: 판정하지 않는 요건이 함께 있으면 확인 필요
base_ok = "참가자격: 중소기업자로 제한한다\n"
eq(verdict_for(base_ok + "「소상공인 기본법」에 따른 소상공인 확인서를 소지한 업체", direct_production=["x"]), "확인 필요", "소상공인 확인서")
eq(verdict_for(base_ok + "최근 3년간 단일 건 5억원 이상 수행실적이 있는 업체로 제한한다", direct_production=["x"]), "확인 필요", "실적 요건")
eq(verdict_for(base_ok + "본점 소재지가 부산광역시인 업체로 제한한다", direct_production=["x"]), "확인 필요", "소재지 요건")
eq(verdict_for(base_ok, direct_production=["x"]), "참가 가능(자격 기준)", "규모 조건만 있고 충족")
# SILVER 4차: 공동수급 방식이 비면 넘기지 않고 확인을 권한다
j = co.judge(prof, {**base_notice, "cmmnSpldmdMethdNm": ""}, [{"lmtGrpNo": "1", "lcnsLmtNm": "정보통신공사업/0036"}], [], doc_ok, now=NOW)
eq(j["next_action"].startswith("공동수급 방식이 표시되지 않았다"), True, "빈 공동수급 방식")
# GOLD 4차: 사업 유형
for t, want in [("과학연구자 대상 AI운영환경(AI-OS) 시범 서비스 개발 용역", "구축·개발"), ("통합관리시스템 구축 위탁 용역", "구축·개발"),
                ("자율주행 공동조사 차량 구축", "구축·개발"), ("2027년 경기도 마이데이터 통합 플랫폼 운영 용역", "운영·유지관리"),
                ("정보시스템 감리", "감리"), ("교통 데이터 플랫폼 시작품 제작", "구축·개발")]:
    eq(biz_type(t), want, t)
print("round5 regression: all passed")

print(f"offline tests: all passed ({CHECKS} eq checks)")
