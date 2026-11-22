"""나라장터 첨부파일(공고문, 제안요청서, 과업지시서)을 내려받아 본문 텍스트를 뽑는다.

지원 형식: HWP(5.x), HWPX, PDF, DOCX, XLSX, ZIP(안의 위 형식).
보안 원칙
- g2b.go.kr 도메인 링크만 받는다. 임의 URL은 거부한다.
- 파일은 디스크에 쓰지 않고 메모리에서만 다룬다.
- 크기 상한을 둔다(다운로드 30MB, 압축 해제 항목당 50MB).
"""

from __future__ import annotations

import io
import re
import struct
import zipfile
import zlib
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

import httpx

MAX_DOWNLOAD = 30 * 1024 * 1024
MAX_UNZIP = 50 * 1024 * 1024
ALLOWED_HOST = re.compile(r"(^|\.)g2b\.go\.kr$")

# 파일 이름으로 '읽을 가치' 순위를 매긴다. 낮을수록 먼저.
NAME_PRIORITY = ["제안요청서", "과업지시서", "과업내용서", "과업설명서", "시방서", "규격서",
                 "사업계획", "공고문", "공고서", "입찰공고"]
EXT_PRIORITY = [".hwp", ".hwpx", ".pdf", ".docx", ".zip", ".xlsx"]

_text_cache: dict[str, tuple[str, str]] = {}


def rank_file(name: str) -> tuple[int, int]:
    n = name.lower()
    np_ = next((i for i, k in enumerate(NAME_PRIORITY) if k in name), len(NAME_PRIORITY))
    ext = next((i for i, e in enumerate(EXT_PRIORITY) if n.endswith(e)), len(EXT_PRIORITY))
    return np_, ext


# ---------------------------------------------------------------- 다운로드

def download(url: str) -> tuple[bytes, str]:
    host = urlparse(url).hostname or ""
    if urlparse(url).scheme != "https" or not ALLOWED_HOST.search(host):
        raise ValueError(f"g2b.go.kr의 https 링크만 받는다: {url}")
    with httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=False) as c:
        with c.stream("GET", url) as r:
            r.raise_for_status()
            buf = io.BytesIO()
            for chunk in r.iter_bytes():
                buf.write(chunk)
                if buf.tell() > MAX_DOWNLOAD:
                    raise ValueError("파일이 30MB를 넘어 읽지 않았다.")
            cd = r.headers.get("content-disposition", "")
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
    name = unquote(m.group(1)) if m else ""
    return buf.getvalue(), name


# ---------------------------------------------------------------- 형식별 추출

_HWP_EXT_CTRL = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
HWPTAG_PARA_TEXT = 67


def _hwp_para_text(data: bytes) -> str:
    out = []
    i, n = 0, len(data) - 1
    while i < n:
        ch = struct.unpack_from("<H", data, i)[0]
        if ch in _HWP_EXT_CTRL:
            if ch == 9:
                out.append("\t")
            i += 16  # 확장/인라인 컨트롤은 8 WCHAR를 차지한다
            continue
        if ch in (10, 13):
            out.append("\n")
        elif ch >= 32:
            out.append(chr(ch))
        i += 2
    return "".join(out)


def extract_hwp(b: bytes) -> str:
    import olefile

    ole = olefile.OleFileIO(io.BytesIO(b))
    header = ole.openstream("FileHeader").read()
    flags = struct.unpack_from("<I", header, 36)[0]
    compressed, encrypted, distribution = flags & 1, flags & 2, flags & 4
    if encrypted:
        return "[암호가 걸린 HWP라 읽을 수 없다]"
    if distribution:
        # 배포용 문서는 본문이 암호화돼 있어 미리보기 텍스트만 읽는다.
        if ole.exists("PrvText"):
            return "[배포용 문서라 앞부분 미리보기만 읽었다]\n" + ole.openstream("PrvText").read().decode("utf-16-le", "ignore")
        return "[배포용 HWP라 읽을 수 없다]"
    sections = sorted(
        (e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
        key=lambda e: int(e[1][7:] or 0),
    )
    paras = []
    for sec in sections:
        data = ole.openstream(sec).read()
        if compressed:
            data = zlib.decompress(data, -15)
        pos = 0
        while pos + 4 <= len(data):
            h = struct.unpack_from("<I", data, pos)[0]
            tag, size = h & 0x3FF, (h >> 20) & 0xFFF
            pos += 4
            if size == 0xFFF:
                size = struct.unpack_from("<I", data, pos)[0]
                pos += 4
            if tag == HWPTAG_PARA_TEXT:
                paras.append(_hwp_para_text(data[pos:pos + size]))
            pos += size
    return "\n".join(p.rstrip() for p in paras)


def _xml_text(xml: bytes, para_tag: str, text_tag: str) -> str:
    root = ET.fromstring(xml)
    lines = []
    for p in root.iter():
        if p.tag.endswith("}" + para_tag):
            t = "".join(x.text or "" for x in p.iter() if x.tag.endswith("}" + text_tag))
            if t.strip():
                lines.append(t)
    return "\n".join(lines)


def _safe_read(z: zipfile.ZipFile, name: str) -> bytes:
    if z.getinfo(name).file_size > MAX_UNZIP:
        raise ValueError(f"{name}의 압축 해제 크기가 너무 크다.")
    return z.read(name)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _hwpx_section_text(xml: bytes) -> str:
    """HWPX 문단(p)마다 그 문단에 직접 딸린 run/t만 모은다.

    표 셀 안의 문단은 바깥 문단의 run 아래(run/tbl/.../p)에 중첩된다. 바깥 문단에서 모든 하위 t를 모으면
    표 내용이 두 번 나온다(실측). 직접 자식 run의 t만 모으고, 중첩 문단은 자기 차례에 따로 읽는다.
    """
    root = ET.fromstring(xml)
    lines = []
    for p in root.iter():
        if _local(p.tag) != "p":
            continue
        parts = []
        for run in p:
            if _local(run.tag) != "run":
                continue
            for t in run:
                if _local(t.tag) == "t":
                    parts.append("".join(t.itertext()))
        line = "".join(parts)
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def extract_hwpx(b: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        secs = sorted((n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
                      key=lambda n: int(re.findall(r"\d+", n)[-1]))
        return "\n".join(_hwpx_section_text(_safe_read(z, s)) for s in secs)


def extract_docx(b: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        return _xml_text(_safe_read(z, "word/document.xml"), "p", "t")


def extract_xlsx(b: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        if "xl/sharedStrings.xml" not in z.namelist():
            return ""
        return _xml_text(_safe_read(z, "xl/sharedStrings.xml"), "si", "t")


def extract_pdf(b: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(b))
    return "\n".join((pg.extract_text() or "") for pg in reader.pages)


def _kind(b: bytes, name: str) -> str:
    n = name.lower()
    if b[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "hwp"  # OLE 컨테이너. 나라장터 첨부에서는 사실상 HWP 5.x
    if b[:4] == b"%PDF":
        return "pdf"
    if b[:2] == b"PK":
        for ext in ("hwpx", "docx", "xlsx"):
            if n.endswith("." + ext):
                return ext
        try:
            names = zipfile.ZipFile(io.BytesIO(b)).namelist()
        except zipfile.BadZipFile:
            return "unknown"
        if any(x.startswith("Contents/section") for x in names):
            return "hwpx"
        if "word/document.xml" in names:
            return "docx"
        if "xl/workbook.xml" in names:
            return "xlsx"
        return "zip"
    return "unknown"


def extract_bytes(b: bytes, name: str, depth: int = 0) -> str:
    kind = _kind(b, name)
    if kind == "hwp":
        return extract_hwp(b)
    if kind == "hwpx":
        return extract_hwpx(b)
    if kind == "pdf":
        return extract_pdf(b)
    if kind == "docx":
        return extract_docx(b)
    if kind == "xlsx":
        return extract_xlsx(b)
    if kind == "zip" and depth == 0:
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            members = [i for i in z.infolist() if not i.is_dir()][:30]
            members.sort(key=lambda i: rank_file(i.filename))
            parts = []
            for info in members[:5]:
                try:
                    txt = extract_bytes(_safe_read(z, info.filename), info.filename, depth + 1)
                except Exception as e:  # noqa: BLE001
                    txt = f"[읽기 실패: {type(e).__name__}]"
                if txt.strip():
                    parts.append(f"===== {info.filename} =====\n{txt}")
            return "\n\n".join(parts) or "[압축 안에서 읽을 수 있는 문서를 찾지 못했다]"
    return f"[지원하지 않는 형식이다: {name or '이름 없음'}]"


def tidy(text: str) -> str:
    # HWP는 UTF-16 코드 단위로 읽으므로 짝이 맞는 서로게이트는 합치고, 짝 없는 것은 버린다(GOLD 평가: JSON 직렬화 실패)
    text = text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "ignore")
    text = re.sub(r"[\ud800-\udfff]", "", text)
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


BID_NO = re.compile(r"R\d{2}BK\d{8}")


def foreign_bid_numbers(bid_no: str, name: str, text: str) -> list[str]:
    """파일 이름이나 본문 앞부분에 다른 공고번호가 있으면 돌려준다(다른 공고의 파일이 붙은 경우, 실측)."""
    seen = set(BID_NO.findall(name or "")) | set(BID_NO.findall((text or "")[:3000]))
    seen.discard(bid_no)
    return sorted(seen) if bid_no not in (name or "") + (text or "")[:3000] else []


def read_url(url: str) -> tuple[str, str]:
    """(파일명, 본문 텍스트). 같은 URL은 프로세스가 살아 있는 동안 다시 받지 않는다."""
    if url in _text_cache:
        return _text_cache[url]
    b, name = download(url)
    text = tidy(extract_bytes(b, name))
    _text_cache[url] = (name, text)
    return name, text
