"""
壽險條款、DM 與商品名稱【免 API 純規則引擎】批次分類與標籤解析器
完全不需任何外部 LLM API Key，零成本、無速率限制！
結合「商品名稱語意規則」與「PyMuPDF (fitz) 條款/DM 內文正規表示式萃取」
自動產出前端卡片盒所需的 structured_products_final.json
"""

import os
import re
import json
import urllib.request
from typing import Dict, Any, List
import pymupdf as fitz  # PyMuPDF

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "tii_insurance_data")
INPUT_METADATA_FILE = os.path.join(DATA_DIR, "all_products_metadata.json")
PDF_STORAGE_DIR = os.path.join(DATA_DIR, "pdf_files")
OUTPUT_STRUCTURED_FILE = os.path.join(DATA_DIR, "structured_products_final.json")

# 品牌代表色對照表
BRAND_COLORS = {
    "南山": "bg-sky-500",
    "安聯": "bg-[#0b2f64]",
    "國泰": "bg-emerald-600",
    "富邦": "bg-blue-600",
    "中華郵政": "bg-red-600",
    "台灣": "bg-amber-600",
    "新光": "bg-red-600",
    "凱基": "bg-teal-600",
    "保誠": "bg-rose-700",
    "全球": "bg-indigo-600",
    "遠雄": "bg-cyan-700",
    "三商美邦": "bg-blue-700",
    "元大": "bg-blue-800",
    "宏泰": "bg-orange-600",
    "台新": "bg-red-700",
    "友邦": "bg-rose-600",
}

# 已由官方商品頁／官方文件核對的代碼；其餘商品不猜測，保留 TII 編號。
OFFICIAL_CODE_HINTS = {
    "南山人壽安心溢百重大傷病終身保險": "NCIC",
    "南山人壽長享平安終身傷害保險": "SUPA",
    "南山人壽鑫富雙享外幣變額壽險": "URVLSP",
    "南山人壽鑫富雙享變額壽險": "RVLSP",
    "富邦人壽新安心悠遊海外突發疾病醫療健康保險附約": "EOHM",
    "國泰人壽醫定安心手術醫療終身保險": "JWI",
}

def download_pdf(url: str, save_path: str) -> bool:
    """下載條款或 DM PDF 並快取於本地"""
    if not url:
        return False
    if os.path.exists(save_path) and os.path.getsize(save_path) > 1024:
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(save_path, "wb") as f:
            f.write(resp.read())
        return True
    except Exception as e:
        print(f"      [!] 下載 PDF 略過 ({url}): {e}")
        return False

def classify_by_name_and_text(name: str, full_text: str) -> Dict[str, Any]:
    """依據商品名稱、DM 與條款內文進行免 API 規則分類與標籤提取"""
    combined = f"{name}\n{full_text}"

    # 1. 主附約判定
    if "附約" in name:
        contract_type = "附約"
    else:
        contract_type = "主約"

    # 2. 現售 / 停售狀態判定
    if "停售" in name or "暫停銷售" in name:
        sales_status = "暫停銷售"
    else:
        sales_status = "現售"

    # 3. 險種大類 (categories) 與卡片盒標籤 (feature_chips)
    categories: List[str] = []
    chips: List[str] = []

    # 重大傷病 / 重大疾病 / 特定傷病
    if any(k in combined for k in ["重大傷病", "重大疾病", "特定傷病", "嚴重特定傷病"]):
        categories.append("重大傷病")
        if "重大傷病" in combined:
            chips.append("重大傷病")
        if "重大疾病" in combined:
            chips.append("重大疾病")
        if "特定傷病" in combined:
            chips.append("特定傷病")

    # 癌症險
    if any(k in name for k in ["癌", "防癌"]):
        categories.append("癌症險")
        chips.append("癌症")

    # 醫療險 (實支實付 vs 定額/手術/日額)
    if any(k in combined for k in ["實支實付", "醫療費用保險", "超過全民健康保險"]):
        categories.append("醫療(實支)")
        chips.append("實支實付")
    elif any(k in name for k in ["醫療", "住院", "手術", "健康保險"]):
        if "重大" not in name and "癌" not in name and "長照" not in name:
            categories.append("醫療(定額)")

    # 意外傷害險
    if any(k in name for k in ["傷害", "意外"]):
        categories.append("意外傷害")
        chips.append("傷害")

    # 長照與失能
    if any(k in combined for k in ["長期照顧", "長照", "失能"]):
        categories.append("長照失能")
        if "長照" in name or "長期照顧" in name:
            chips.append("長照")
        if "失能" in combined:
            chips.append("失能")

    # 年金、投資型與儲蓄型保險
    if any(k in combined for k in ["年金保險", "年金"]):
        categories.append("年金險")
        chips.append("年金")
    if any(k in combined for k in ["投資型", "變額萬能", "變額年金", "投資連結"]):
        categories.append("投資型")
        chips.append("投資型")
    if any(k in combined for k in ["利率變動型", "儲蓄型", "增額終身", "還本型"]):
        categories.append("儲蓄型")
        chips.append("儲蓄")

    # 其他常見保障分類
    if any(k in combined for k in ["失能扶助", "失能照護", "豁免保險費"]):
        if "長照失能" not in categories:
            categories.append("長照失能")
        if "失能" not in chips:
            chips.append("失能")
    if any(k in combined for k in ["重大疾病", "重大傷病"]):
        if "重大傷病" not in categories:
            categories.append("重大傷病")

    # 壽險
    if any(k in combined for k in ["壽險", "定期壽險", "終身壽險"]) and not categories:
        categories.append("壽險")
        chips.append("壽險")

    # 細部保障特徵標籤 (從名稱與條款標題萃取)
    tag_keywords = [
        ("住院", ["住院"]),
        ("日額", ["日額"]),
        ("手術", ["手術"]),
        ("門診", ["門診手術", "門診醫療"]),
        ("骨折", ["骨折"]),
        ("身故", ["身故保險金", "身故給付"]),
        ("實支實付", ["實支實付"]),
        ("美元", ["美元"]),
        ("外溢", ["外溢", "健走", "步數", "體況檢測"]),
    ]
    for chip_label, kw_list in tag_keywords:
        if any(k in combined for k in kw_list) and chip_label not in chips:
            chips.append(chip_label)

    # 期間標籤
    if "終身" in name:
        if "終身" not in categories:
            categories.append("終身")
        if "終身" not in chips:
            chips.append("終身")
    elif "一年" in name:
        chips.append("一年期")
    elif "定期" in name:
        chips.append("定期")

    if contract_type == "附約" and "附約" not in chips:
        chips.append("附約")
    elif contract_type == "主約" and "主約" not in chips:
        chips.append("主約")

    if not categories:
        categories.append("醫療(定額)")

    # 4. 保證續保與 2-2-7 手術限制偵測
    is_guaranteed_renewal = bool(
        re.search(r"保證續保|不得拒絕續保|終身保險", combined)
    )
    has_227_restriction = bool(
        re.search(r"第二部第二章第七節|2-2-7|二—二—七", full_text)
    )

    # 5. 等待期天數偵測
    waiting_days = 0
    if re.search(r"第九十日|90\s*日|九十日", full_text):
        waiting_days = 90
    elif re.search(r"第三十日|30\s*日|三十日", full_text):
        waiting_days = 30

    # 6. 投保年齡區間偵測 (從 DM 或條款文字匹配，若條款未載則依險種慣例給出預設參考值)
    min_age, max_age = 0, 65
    age_match = re.search(r"投保年齡[：:\s]*(?:自|從)?(?:出生滿\d+日|0\s*歲|(\d{1,2})\s*歲)[至~～\-](\d{2})\s*歲", full_text)
    if age_match:
        min_age = int(age_match.group(1)) if age_match.group(1) else 0
        max_age = int(age_match.group(2))
    elif "長享" in name or "樂齡" in name or "銀髮" in name:
        min_age, max_age = 50, 80
    elif "終身" in name:
        min_age, max_age = 0, 60

    age_range_display = f"{min_age}~{max_age} 歲"

    return {
        "contract_type": contract_type,
        "sales_status": sales_status,
        "categories": categories,
        "feature_chips": chips[:6],
        "is_guaranteed_renewal": is_guaranteed_renewal,
        "has_227_restriction": has_227_restriction,
        "waiting_days": waiting_days,
        "min_issue_age": min_age,
        "max_issue_age": max_age,
        "age_range_display": age_range_display,
    }

def extract_clauses_from_pdf(pdf_path: str, waiting_days: int) -> Dict[str, Any]:
    """使用 PyMuPDF 讀取條款 PDF，自動抓出【〇〇保險金】條次、頁碼與原文摘錄"""
    full_text = ""
    highlights = []
    evidence_quote = "詳見正式保單條款與商品簡介 DM 文件。"
    source_page = 1

    if not pdf_path or not os.path.exists(pdf_path):
        return {
            "full_text": "",
            "highlights": [],
            "evidence_quote": evidence_quote,
            "source_page": source_page,
        }

    try:
        doc = fitz.open(pdf_path)
        clause_pattern = re.compile(
            r"(第[一二三四五六七八九十百零\d]+條)\s*[\n\r\s]*[【\[]?([^】\]\n\r]{2,20}(?:保險金|津貼|給付|豁免)[^】\]\n\r]{0,10})[】\]]?"
        )

        for page_idx, page in enumerate(doc):
            p_num = page_idx + 1
            text = page.get_text("text")
            full_text += f"\n{text}"

            for match in clause_pattern.finditer(text):
                clause_no = match.group(1).strip()
                benefit_title = match.group(2).strip()
                # 擷取該條文後方 120 字作為摘要
                start_pos = match.end()
                snippet = re.sub(r"\s+", "", text[start_pos:start_pos + 160])
                if len(snippet) > 15 and len(highlights) < 6:
                    highlights.append({
                        "name": benefit_title,
                        "summary": snippet[:95] + ("..." if len(snippet) > 95 else ""),
                        "waiting_period": waiting_days,
                        "clause": clause_no,
                        "page": p_num
                    })
                    if evidence_quote.startswith("詳見"):
                        evidence_quote = snippet[:120]
                        source_page = p_num
        doc.close()
    except Exception as e:
        print(f"      [!] PyMuPDF 解析略過: {e}")

    return {
        "full_text": full_text,
        "highlights": highlights,
        "evidence_quote": evidence_quote,
        "source_page": source_page,
    }

def extract_code_from_name(name: str, default_code: str) -> str:
    """從商品名稱括號中自動提取英文商品代號 (如 (HMRA), (CHR2), (NCIC))"""
    if default_code and re.match(r"^[A-Z0-9]{2,8}$", default_code.strip()):
        return default_code.strip()
    matches = re.findall(r"[\(（]([A-Z0-9]{2,8})[\)）]", name)
    if matches:
        return matches[-1]
    return default_code or "TII"


def extract_official_code(name: str) -> str:
    for product_name, code in OFFICIAL_CODE_HINTS.items():
        if product_name in name:
            return code
    matches = re.findall(r"[\(（]([A-Z][A-Z0-9-]{1,8})[\)）]", name)
    return matches[-1] if matches else ""


def normalize_approval_date(value: str) -> tuple[str, str]:
    """將民國／西元日期統一成 YYYY/MM 與 MM-DD。"""
    value = (value or "").replace("-", "/").strip()
    match = re.search(r"(\d{3,4})/(\d{1,2})(?:/(\d{1,2}))?", value)
    if not match:
        return "", "待補日期"
    year, month, day = match.groups()
    month = int(month)
    if len(year) == 3:
        year = str(int(year) + 1911)
    release_month = f"{year}/{month:02d}"
    mm_dd = f"{month:02d}-{int(day):02d}" if day else f"{month:02d}"
    return release_month, mm_dd

def main():
    if not os.path.exists(INPUT_METADATA_FILE):
        print(f"[!] 找不到輸入檔案: {INPUT_METADATA_FILE}，請先執行 tii_full_crawler.py！")
        return

    os.makedirs(PDF_STORAGE_DIR, exist_ok=True)
    with open(INPUT_METADATA_FILE, "r", encoding="utf-8") as f:
        meta_list = json.load(f)

    print(f"[*] 載入 {len(meta_list)} 檔商品，啟動【免 API 規則與條款解析引擎】...")
    final_cards = []

    for idx, item in enumerate(meta_list):
        pname = item.get("product_full_name", "").strip()
        if not pname:
            continue

        pdf_url = item.get("pdf_url", "")
        pdf_path = ""
        if pdf_url:
            pdf_filename = f"{item['company_code']}_{idx}.pdf"
            pdf_path = os.path.join(PDF_STORAGE_DIR, pdf_filename)
            download_pdf(pdf_url, pdf_path)

        # 1. 先解析 PDF 條款文字與給付條次
        pdf_info = extract_clauses_from_pdf(pdf_path, waiting_days=0)

        # 2. 執行名稱與內文分類規則
        rules = classify_by_name_and_text(pname, pdf_info["full_text"])

        # 更新等待期至條款摘要
        highlights = pdf_info["highlights"]
        for h in highlights:
            h["waiting_period"] = rules["waiting_days"]

        if not highlights:
            highlights = [{
                "name": "主要契約保障項目",
                "summary": f"依據「{pname}」正式保單條款與核保規定辦理給付。",
                "waiting_period": rules["waiting_days"],
                "clause": "保單條款",
                "page": 1
            }]

        short_comp = item.get("company_name", "").replace("人壽", "").replace("保險股份有限公司", "").replace("法商法國巴黎", "法巴")
        release_month, mm_dd = normalize_approval_date(item.get("approval_date", ""))
        from datetime import datetime
        now = datetime.now()
        is_new = release_month == f"{now.year}/{now.month:02d}"

        card = {
            "id": f"prod-{item['company_code']}-{idx+1:04d}",
            "company": short_comp,
            "company_color": BRAND_COLORS.get(short_comp, "bg-slate-700"),
            "release_month": release_month,
            "is_new": is_new,
            "new_tag": f"新 {mm_dd}" if is_new else mm_dd,
            "product_full_name": pname,
            "product_code": extract_code_from_name(pname, item.get("product_code", "")),
            "official_product_code": item.get("official_product_code") or extract_official_code(pname),
            "tii_product_code": item.get("product_code", ""),
            "contract_type": rules["contract_type"],
            "sales_status": item.get("sales_status", rules["sales_status"]),
            "approval_number": item.get("approval_number", "依保發中心備查文號"),
            "age_range_display": rules["age_range_display"],
            "min_issue_age": rules["min_issue_age"],
            "max_issue_age": rules["max_issue_age"],
            "max_renewal_age": 75 if rules["contract_type"] == "附約" else None,
            "is_guaranteed_renewal": rules["is_guaranteed_renewal"],
            "has_227_restriction": rules["has_227_restriction"],
            "categories": rules["categories"],
            "feature_chips": rules["feature_chips"],
            "age_rules": [
                {"term": "標準年期", "max_age": rules["max_issue_age"]}
            ],
            "sum_assured_limits": {
                "unit": "依保單條款/DM",
                "min": "依投保規則",
                "max": "依投保規則",
                "notes": "免 API 規則引擎自動分類，詳細保額限制請參閱商品 DM。"
            },
            "coverage_highlights": highlights,
            "evidence_quote": pdf_info["evidence_quote"],
            "source_page": pdf_info["source_page"],
            "source_url": item.get("source_url", "")
        }
        final_cards.append(card)

    os.makedirs(os.path.dirname(OUTPUT_STRUCTURED_FILE), exist_ok=True)
    with open(OUTPUT_STRUCTURED_FILE, "w", encoding="utf-8") as f:
        json.dump(final_cards, f, ensure_ascii=False, indent=2)

    print(f"[✓] 免 API 批次分類完成！共產出 {len(final_cards)} 張保單卡片至 {OUTPUT_STRUCTURED_FILE}")

if __name__ == "__main__":
    main()
