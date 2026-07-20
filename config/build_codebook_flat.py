"""config/codebook.xlsx의 Codebook_KR 시트를 config/codebook_flat.json으로 평탄화한다.

코드북(xlsx)이 개정될 때마다 재실행:
    python config/build_codebook_flat.py
"""
import json
import re
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
XLSX_PATH = ROOT / "config" / "codebook.xlsx"
JSON_PATH = ROOT / "config" / "codebook_flat.json"

CODE_ITEM_RE = re.compile(r"^(\d+)\s+(.*)$")


def parse_options(raw: str, var_type: str):
    """'코딩값/허용값' 문자열을 옵션 리스트로 분해한다."""
    items = [s.strip() for s in raw.split(";") if s.strip()]
    if var_type in ("Categorical", "Binary"):
        options = []
        all_coded = True
        for item in items:
            m = CODE_ITEM_RE.match(item)
            if m:
                options.append({"code": int(m.group(1)), "label": m.group(2).strip()})
            else:
                all_coded = False
                options.append({"code": None, "label": item})
        return options if all_coded else options
    if var_type == "Multiple / Text":
        # 예: '신체폭력; 경제적 손실; ...; 없음; 기타' — 코드 없이 라벨만 나열
        return [{"code": None, "label": item} for item in items]
    # Text / Numeric / Date 등 자유 입력형은 허용 형식 설명만 남긴다.
    return None


def main():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    ws = wb["Codebook_KR"]

    variables = []
    for row in ws.iter_rows(min_row=4, values_only=True):
        var_id, dimension, name, var_type, raw_codes, definition, rule, example = row
        if not var_id:
            continue
        entry = {
            "variable_id": var_id,
            "dimension": dimension,
            "name": name,
            "type": var_type,
            "definition": definition,
            "coding_rule": rule,
            "example": example,
        }
        options = parse_options(raw_codes, var_type) if raw_codes else None
        if options is not None:
            entry["allowed_codes"] = options
        else:
            entry["allowed_format"] = raw_codes
        variables.append(entry)

    flat = {
        "source": "SSCI_온라인스캠센터_내용분석_3개국어_코드북.xlsx :: Codebook_KR",
        "unit_of_analysis": "개별 뉴스기사",
        "variable_count": len(variables),
        "variables": variables,
    }

    JSON_PATH.write_text(
        json.dumps(flat, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {len(variables)} variables -> {JSON_PATH}")


if __name__ == "__main__":
    main()
