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
r = s.search_awards(category="용역", keyword="시험", period="최근 7일", min_price="1억")
st = r["stats"]
assert st["count"] == 3 and st["sucsfbidRate_pct"]["median"] == 88.1
assert st["sucsfbidAmt_won"]["median"] == 200000000 and st["prtcptCnum"]["max"] == 10
assert st["top_winners"] == [{"name": "가나다 주식회사", "wins": 2}]
assert r["items"][0]["bidNtceNo"] == "A3"  # 개찰일 최신순
ppss = [c for c in calls if c[1].endswith("PPSSrch")][0][2]
assert ppss["inqryDiv"] == 2 and ppss["presmptPrceBgn"] == 100000000, ppss  # 개찰일시 기준 = 2
r = s.search_awards(category="용역", winner="라마바")
assert [i["bidNtceNo"] for i in r["items"]] == ["A3"]
r = s.search_awards(category="용역", date_basis="공고일시")
assert [c for c in calls if c[1].endswith("PPSSrch")][-1][2]["inqryDiv"] == 1

print("award offline tests: all passed")
