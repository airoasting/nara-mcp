"""watchlist 커서 시험. 결과가 많을 때 남은 공고가 영구히 빠지지 않는지 본다(RED 2차 평가 재현).

사용: uv run python test_watchlist_offline.py
"""
import os
import tempfile

os.environ["G2B_DATA_DIR"] = tempfile.mkdtemp(prefix="g2b-wl-")
import server as s  # noqa: E402

N = 300
ITEMS = [{"bidNtceNo": f"R26BK{900000 + i:08d}", "bidNtceOrd": "000", "ntceKindNm": "등록공고",
          "bidNtceNm": f"AI 시험 공고 {i}", "bidNtceDt": f"2026-11-2{i % 2} {8 + i // 60:02d}:{i % 60:02d}:00",
          "bidClseDt": "2026-12-31 10:00:00"} for i in range(N)]


def fake_call(op, params, retries=2, service="bid"):
    page, n = int(params.get("pageNo", 1)), int(params.get("numOfRows", 10))
    return {"totalCount": N, "items": ITEMS[(page - 1) * n: page * n]}


s.call = fake_call
s.watchlist("add", name="t", keyword="AI")
got = set()
for _ in range(10):
    r = s.watchlist("check", name="t")["results"]["t"]
    got |= {i["bidNtceNo"] for i in r["new"]}
    if not r["truncated"] and r["remaining"] == 0 and not r["new"]:
        break
assert len(got) == N, f"{len(got)}/{N}건만 나왔다"
print("watchlist offline test: all passed")

# 45일 공백: 7일 한도로 앞 구간을 못 보면 커서를 조회 구간으로 옮기고 놓친 구간을 밝힌다(RED 3차 평가)
import company as co  # noqa: E402
wl = co.list_watch()
wl["t"]["last_checked"] = "202610080000"
co.save_watch(wl)
starts = []
for _ in range(10):
    r = s.watchlist("check", name="t")["results"]["t"]
    starts.append(r["checked_from"])
    if r["new_count"] == 0 and not r["truncated"]:
        break
assert len(set(starts)) > 1 or len(starts) == 1, starts  # 커서가 멈추지 않는다
first = s.watchlist("check", name="t")["results"]["t"]
assert first["checked_from"] != "202610080000"
print("watchlist gap test: all passed")
