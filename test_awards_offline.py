"""낙찰 도구 오프라인 테스트. 참고문서(낙찰정보서비스 1.2) 샘플 응답 형태로 가짜 응답을 넣는다.

사용: uv run python test_awards_offline.py
"""
import os
import tempfile

os.environ["G2B_DATA_DIR"] = tempfile.mkdtemp(prefix="g2b-test-")
import awards as aw  # noqa: E402
import server as s  # noqa: E402

calls = []


def fake_call(op, params, retries=2, service="bid"):
    calls.append((service, op, dict(params)))
    if service == "bid":  # 업무구분 찾기: 용역으로 응답
        if op.startswith("getBidPblancListInfoServc"):
            return {"totalCount": 1, "items": [{"bidNtceNo": params["bidNtceNo"], "bidNtceOrd": "000",
                                                "bidNtceNm": "시험 용역", "bidClseDt": "2026-11-01 10:00:00"}]}
        return {"totalCount": 0, "items": []}
    if op == "getScsbidListSttusServc":
        assert params["inqryDiv"] == 4
        return {"items": [{"bidNtceNo": "R25BK00927163", "bidNtceOrd": "000", "bidNtceNm": "시험 용역",
                           "prtcptCnum": "7", "bidwinnrNm": "가나다 주식회사", "sucsfbidAmt": "72000000",
                           "sucsfbidRate": "87.745", "rlOpengDt": "2025-07-01 11:00:00"}]}
    if op == "getOpengResultListInfoServc":
        return {"items": [{"bidNtceOrd": "000", "progrsDivCdNm": "개찰완료", "prtcptCnum": "7",
                           "opengCorpInfo": "가나다 주식회사^5088702880^홍길동^72000000^87.745"}]}
    if op == "getOpengResultListInfoOpengCompt":
        assert "inqryDiv" not in params, "개찰완료 목록은 inqryDiv를 받지 않는다"
        return {"items": [{"opengRank": "1", "prcbdrNm": "가나다 주식회사", "bidprcAmt": "72000000", "bidprcrt": "87.745"},
                          {"opengRank": "2", "prcbdrNm": "라마바", "bidprcAmt": "73000000", "bidprcrt": "88.9"}]}
    if op == "getOpengResultListInfoServcPreparPcDetail":
        assert params["inqryDiv"] == 2 and params["bidNtceOrd"] == "000"
        return {"items": [{"plnprc": "82055000", "bssamt": "82000000", "totRsrvtnPrceNum": "15",
                           "compnoRsrvtnPrceSno": str(i), "bsisPlnprc": str(81000000 + i * 100000),
                           "drwtYn": "Y" if i in (2, 5, 9, 13) else "N", "drwtNum": "3"} for i in range(1, 16)]}
    if op.endswith("PPSSrch"):
        assert params["inqryDiv"] in (1, 2)
        if params["pageNo"] > 1:
            return {"totalCount": 3, "items": []}
        return {"totalCount": 3, "items": [
            {"bidNtceNo": "A1", "bidNtceOrd": "000", "bidClsfcNo": "0", "rbidNo": "000", "bidwinnrNm": "가나다 주식회사",
             "sucsfbidAmt": "100000000", "sucsfbidRate": "87.7", "prtcptCnum": "10", "rlOpengDt": "2026-11-20 11:00:00"},
            {"bidNtceNo": "A2", "bidNtceOrd": "000", "bidClsfcNo": "0", "rbidNo": "000", "bidwinnrNm": "가나다 주식회사",
             "sucsfbidAmt": "200000000", "sucsfbidRate": "88.1", "prtcptCnum": "4", "rlOpengDt": "2026-11-19 11:00:00"},
            {"bidNtceNo": "A3", "bidNtceOrd": "000", "bidClsfcNo": "0", "rbidNo": "000", "bidwinnrNm": "라마바",
             "sucsfbidAmt": "300000000", "sucsfbidRate": "90.0", "prtcptCnum": "1", "rlOpengDt": "2026-11-21 11:00:00"}]}
    return {"items": []}


s.call = fake_call

# opengCorpInfo 파싱
c = aw.parse_corp_info("이엠테스트코리아 주식회사^1428139282^김종인^178750000^97.992")
assert c[0]["name"] == "이엠테스트코리아 주식회사" and c[0]["bid_rate"] == "97.992" and c[0]["bid_amount_kr"] == "1.79억원"
assert aw.parse_corp_info("") == []

# get_award
r = s.get_award("R25BK00927163", bidders_top=5)
assert r["category"] == "용역" and r["status"] == "개찰완료", r["status"]
assert r["final_award"][0]["bidwinnrNm"] == "가나다 주식회사"
assert r["bidders"][1]["prcbdrNm"] == "라마바"
assert r["reserve_price"]["plnprc_kr"] == "0.82억원" or r["reserve_price"]["plnprc_kr"].endswith("만원")
assert [d["sno"] for d in r["reserve_price"]["drawn"]] == ["2", "5", "9", "13"]
assert len(r["reserve_price"]["all"]) == 15
assert "failure_reason" not in r

# search_awards: 통계, 낙찰업체 필터, 정렬
calls.clear()
r = s.search_awards(category="용역", period="최근 7일", min_price="1억")
st = r["stats"]
assert st["all"]["count"] == 3 and st["all"]["sucsfbidRate_pct"]["median"] == 88.1
assert st["all"]["sucsfbidAmt_won"]["median"] == 200000000 and st["all"]["prtcptCnum"]["max"] == 10
# 경쟁(2개사 이상)과 단독(1개사)을 나눈다: A3는 참가 1개사
assert st["competitive"]["count"] == 2 and st["single_bidder"]["count"] == 1
assert st["competitive"]["sucsfbidRate_pct"]["median"] == 87.9
assert [w["name"] for w in st["top_winners"]] == ["가나다 주식회사"] and st["top_winners"][0]["wins"] == 2
assert r["items"][0]["bidNtceNo"] == "A3"  # 개찰일 최신순
ppss = [c for c in calls if c[1].endswith("PPSSrch")][0][2]
assert ppss["inqryDiv"] == 2 and ppss["presmptPrceBgn"] == 100000000, ppss  # 개찰일시 기준 = 2
r = s.search_awards(category="용역", winner="라마바")
assert [i["bidNtceNo"] for i in r["items"]] == ["A3"]
r = s.search_awards(category="용역", date_basis="공고일시")
assert [c for c in calls if c[1].endswith("PPSSrch")][-1][2]["inqryDiv"] == 1

print("award offline tests: all passed")

# ---------------------------------------------------------------- 4차: A값 플래그, 실제 하한율, 방법별 하한 대비, 사업기간
b = {"bssamt": "100000000", "rsrvtnPrceRngBgnRate": "-2", "rsrvtnPrceRngEndRate": "+2",
     "sftyMngcst": "3000000", "qltyMngcst": "2000000", "qltyMngcstAObjYn": "N"}
r = aw.bid_calc({**b, "bidPrceCalclAYn": "N"}, "87.745")
assert "a_value" not in r and r["reference_floor_at_base"] == 87745000 and r.get("a_value_note"), r
r = aw.bid_calc({**b, "bidPrceCalclAYn": "Y"}, "87.745")
assert r["a_value"] == 3000000, r  # 품질관리비는 AObjYn=N이라 빠진다
assert r["reference_floor_at_base"] == int(3000000 + (100000000 - 3000000) * 0.87745), r
eff = aw.effective_floor_rate("89.745", 23147404, 364360000)
assert abs(eff - 90.397) < 0.01, eff  # SILVER 계산(약 90.34~90.40%)과 같은 범위
bm = aw.by_method([{"method": "적격심사제", "sucsfbidRate": "89.0", "lwlt": "87.745"},
                   {"method": "적격심사제", "sucsfbidRate": "90.0", "lwlt": "89.745"}])
assert bm["적격심사제"]["nominal_rate_minus_floor_pp"]["median"] == 0.755, bm
sch = s._project_schedule("사업기간 산정[붙임 1호 서식] 일반현황 2026. 1. 1.\n2. 사업기간: 계약체결일로부터 2026. 12. 31.까지",
                         {"opengDt": "2026-12-10 11:00:00"})  # 목차·서식 줄은 건너뛴다
assert sch["days_after_opening"] == 20 and "risk" in sch, sch
assert s._project_schedule("과업 내용만 있다", {"opengDt": "2026-12-10 11:00:00"}) is None

# 판정 저장과 재사용: 같은 프로필·같은 차수면 두 번째는 API를 부르지 않는다(GOLD 3차 평가)
import company as co  # noqa: E402
co.update_profile({"region": "경기도 성남시", "licenses": ["소프트웨어사업자/1468"], "company_size": "중소기업",
                   "direct_production": []}, replace=True)
item = {"bidNtceNo": "R26BK09990001", "bidNtceOrd": "000", "bidNtceNm": "시험", "bidClseDt": "2099-12-31 10:00:00"}
s._read_docs = lambda it, max_files=2: {"read": True, "files": ["공고문"], "conditions": {}}
calls.clear()
j1 = s._judge_item(co.get_profile(), item, True)
n1 = len(calls)
j2 = s._judge_item(co.get_profile(), item, True)
assert n1 > 0 and len(calls) == n1 and j2.get("reused") and j2["verdict"] == j1["verdict"], (n1, len(calls), j2)
co.update_profile({"company_size": "소기업"})  # 프로필이 바뀌면 다시 판정한다
j3 = s._judge_item(co.get_profile(), item, True)
assert not j3.get("reused")
j4 = s._judge_item(co.get_profile(), {**item, "ntceKindNm": "취소공고"}, True)  # 저장본이어도 취소는 지금 기준으로
assert j4["verdict"] == "참가 어려움", j4

sch = s._project_schedule("전체 납품기한: 계약 후 60일", {"opengDt": "2026-12-10 11:00:00"})
assert sch["days_from_contract"] == 60 and "risk" not in sch, sch
sch = s._project_schedule("사업기간: 계약일로부터 45일", {"opengDt": "2026-12-10 11:00:00"})
assert sch["days_from_contract"] == 45 and "risk" in sch, sch

# 저장된 판정은 시간 항목을 다시 계산한다: 자격등록 마감이 지나면 '참가 가능'이 '확인 필요'로 바뀌고 checks도 맞춘다(RED 4차)
from datetime import datetime as _dt  # noqa: E402
saved = {"verdict": "참가 가능(자격 기준)", "checks": [
    {"check": "공고 상태", "result": "충족", "detail": "진행중 D-9"},
    {"check": "자격등록 마감", "result": "충족", "detail": "x"},
    {"check": "면허(업종)", "result": "충족", "detail": "y"},
    {"check": "중소기업 제한", "result": "충족", "detail": "z"}]}
it2 = {"bidNtceNo": "A", "bidNtceOrd": "000", "bidClseDt": "2026-12-01 10:00:00", "bidQlfctRgstDt": "2026-11-20 18:00"}
r = co.refresh(saved, it2, _dt(2026, 11, 22, 9, 0))
assert r["verdict"] == "확인 필요" and [c["result"] for c in r["checks"] if c["check"] == "자격등록 마감"] == ["확인 필요"], r
r = co.refresh(saved, {**it2, "ntceKindNm": "취소공고"}, _dt(2026, 11, 22, 9, 0))
assert r["verdict"] == "참가 어려움" and r["checks"][0]["result"] == "불충족", r
p1 = s._profile_hash({"a": 1})
co.RULES_VERSION, old = "x", co.RULES_VERSION
assert s._profile_hash({"a": 1}) != p1, "규칙 버전이 바뀌면 저장 판정을 다시 쓰지 않는다"
co.RULES_VERSION = old

print("award round4 tests: all passed")
