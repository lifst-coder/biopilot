# BIOPILOT - XLSX / CP949 시험 파일 생성. openpyxl이라는 독립 구현으로 만들어 자체 XLSX 판독기를 교차 검증한다.
#   uv run --with openpyxl python scripts/gen-fixtures.py
import csv, pathlib
from openpyxl import Workbook

root = pathlib.Path(__file__).resolve().parent.parent
data = root / "data"

def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))

def typed(v):
    try:
        if v.strip() == "":
            return None
        x = float(v)
        return int(x) if x.is_integer() and "." not in v and "e" not in v.lower() else x
    except ValueError:
        return v

# 1) 전체 합성 배치를 XLSX로 (숫자는 숫자 셀, 문자열은 공유 문자열)
rows = read_csv(data / "synthetic_all_batches.csv")
wb = Workbook()
ws = wb.active
ws.title = "LCMS Results"
for r in rows:
    ws.append([typed(c) for c in r])
notes = wb.create_sheet("Notes")
notes.append(["이 시트는 메모입니다"])
notes.append(["합성 데이터", 2026])
wb.save(data / "synthetic_all_batches.xlsx")

# 2) 한글 머리글 + 여러 시트 + 수식 셀이 있는 XLSX
ko = read_csv(data / "test_inputs" / "korean_headers_utf8.csv")
wb2 = Workbook()
s1 = wb2.active
s1.title = "결과"
for r in ko:
    s1.append([typed(c) for c in r])
s1["N1"] = "면적비(수식)"
for i in range(2, 6):
    s1[f"N{i}"] = f"=G{i}/H{i}"
wb2.save(data / "test_inputs" / "korean_headers.xlsx")

# 3) 한국어 Excel의 기본 CSV 인코딩(CP949)
text = (data / "test_inputs" / "korean_headers_utf8.csv").read_text(encoding="utf-8-sig")
(data / "test_inputs" / "korean_headers_cp949.csv").write_bytes(text.encode("cp949"))
print("fixtures written")
