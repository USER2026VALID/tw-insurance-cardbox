"""
保發中心壽險商品公開結果頁爬蟲。

Query.aspx 目前要求人工驗證碼，不能可靠地作為無人值守入口；本爬蟲改用
保發中心公開的 ResultQueryAll.aspx 結果頁，從公開列表擷取壽險商品名稱、銷售日、停售狀態與明細頁連結。
"""

import json
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 壽險公會名錄：18 家本國公司 + 2 家外商在台分公司。
LIFE_INSURANCE_COMPANIES = [
    {"code": "224", "name": "臺銀人壽", "aliases": ["臺銀人壽", "台銀人壽", "Bank Taiwan"]},
    {"code": "202", "name": "台灣人壽", "aliases": ["台灣人壽", "臺灣人壽", "Taiwan Life"]},
    {"code": "203", "name": "保誠人壽", "aliases": ["保誠人壽", "PCA", "Prudential"]},
    {"code": "204", "name": "國泰人壽", "aliases": ["國泰人壽", "Cathay"]},
    {"code": "205", "name": "凱基人壽", "aliases": ["凱基人壽", "中國人壽", "KGI"]},
    {"code": "206", "name": "南山人壽", "aliases": ["南山人壽", "Nan Shan"]},
    {"code": "208", "name": "新光人壽", "aliases": ["新光人壽", "Shin Kong"]},
    {"code": "210", "name": "富邦人壽", "aliases": ["富邦人壽", "Fubon"]},
    {"code": "211", "name": "三商美邦人壽", "aliases": ["三商美邦人壽", "三商美邦", "Mercuries"]},
    {"code": "213", "name": "遠雄人壽", "aliases": ["遠雄人壽", "Farglory"]},
    {"code": "214", "name": "宏泰人壽", "aliases": ["宏泰人壽", "Hontai"]},
    {"code": "215", "name": "安聯人壽", "aliases": ["安聯人壽", "Allianz"]},
    {"code": "216", "name": "第一金人壽", "aliases": ["第一金人壽", "第一人壽", "First Life"]},
    {"code": "217", "name": "元大人壽", "aliases": ["元大人壽", "Yuanta"]},
    {"code": "219", "name": "全球人壽", "aliases": ["全球人壽", "Transglob"]},
    {"code": "220", "name": "中華郵政壽險", "aliases": ["中華郵政", "郵政壽險", "Chungwa Post"]},
    {"code": "221", "name": "安達國際人壽", "aliases": ["安達國際人壽", "安達人壽", "Chubb"]},
    {"code": "223", "name": "友邦人壽", "aliases": ["友邦人壽", "AIA"]},
    {"code": "222", "name": "法國巴黎人壽", "aliases": ["法國巴黎人壽", "法商法國巴黎人壽", "BNP Paribas", "Cardif"]},
    {"code": "225", "name": "合作金庫人壽", "aliases": ["合作金庫人壽", "合庫人壽", "TCB Life"]},
]

TII_RESULT_URL = "https://insprod.tii.org.tw/ResultQueryAll.aspx"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "tii_insurance_data")
PDF_DIR = os.path.join(OUTPUT_DIR, "pdf_files")
SCAN_START_PAGE = 2000
PAGE_SIZE = 50
MAX_WORKERS = 8
REQUEST_TIMEOUT = 30
PAGES_PER_WORKER = 100


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").replace("台", "臺")


def company_for_product(name: str) -> Optional[Dict[str, str]]:
    normalized = normalize(name)
    for company in LIFE_INSURANCE_COMPANIES:
        aliases = company.get("aliases", []) + [company["name"]]
        if any(normalize(alias) in normalized for alias in aliases):
            return company
    return None


def make_session() -> requests.Session:
    session = requests.Session()
    session.verify = False
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; InsuranceCatalogBot/1.0)"})
    # 結果頁的公開表單允許每頁 50 筆；不繞過驗證碼或存取控制。
    session.get(TII_RESULT_URL + "?page=1", timeout=REQUEST_TIMEOUT)
    session.post(TII_RESULT_URL + "?page=1", data={"PageCrt": str(PAGE_SIZE)}, timeout=REQUEST_TIMEOUT)
    return session


def parse_total(html: str) -> int:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    match = re.search(r"總共找到\s*([\d,]+)", text)
    return int(match.group(1).replace(",", "")) if match else 0


def parse_result_page(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    products: List[Dict[str, Any]] = []
    for link in soup.select('a[href*="DetailList.aspx?productId="]'):
        name = link.get_text(" ", strip=True)
        company = company_for_product(name)
        if not company:
            continue
        row = link.find_parent("tr")
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")] if row else []
        product_id = re.search(r"productId=([^&]+)", link.get("href", ""))
        sale_date = cells[2] if len(cells) >= 3 else ""
        stop_date = cells[3] if len(cells) >= 4 else ""
        href = link.get("href", "")
        products.append({
            "company_code": company["code"],
            "company_name": company["name"],
            "product_full_name": name,
            "product_code": product_id.group(1)[:32] if product_id else "",
            "approval_date": sale_date,
            "approval_number": "保發中心商品資料",
            "pdf_url": "",
            "source_url": "https://insprod.tii.org.tw/" + href.lstrip("/"),
            "sales_status": "暫停銷售" if stop_date and stop_date != "未停售" else "現售",
            "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
    return products


def fetch_result_pages(page_numbers: List[int]) -> List[Dict[str, Any]]:
    """每個工作執行緒只建立一次 session，避免每頁重複初始化造成逾時。"""
    session = make_session()
    products: List[Dict[str, Any]] = []
    for page_num in page_numbers:
        response = session.get(TII_RESULT_URL + f"?page={page_num}", timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        products.extend(parse_result_page(response.text))
    return products


def fetch_result_page(page_num: int) -> Tuple[int, List[Dict[str, Any]]]:
    """保留單頁介面供測試使用。"""
    session = make_session()
    response = session.get(TII_RESULT_URL + f"?page={page_num}", timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return parse_total(response.text), parse_result_page(response.text)


def main() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(PDF_DIR, exist_ok=True)

    first_session = make_session()
    first_response = first_session.get(TII_RESULT_URL + "?page=1", timeout=REQUEST_TIMEOUT)
    first_response.raise_for_status()
    total = parse_total(first_response.text)
    max_page = math.ceil(total / PAGE_SIZE)
    if not total or max_page < SCAN_START_PAGE:
        raise RuntimeError(f"保發中心回傳的總筆數異常：{total}")

    page_numbers = list(range(SCAN_START_PAGE, max_page + 1))
    page_ranges = [page_numbers[i:i + PAGES_PER_WORKER] for i in range(0, len(page_numbers), PAGES_PER_WORKER)]
    all_results: List[Dict[str, Any]] = []
    print(f"[*] 公開結果頁共 {total} 筆，使用每頁 {PAGE_SIZE} 筆掃描第 {SCAN_START_PAGE}~{max_page} 頁。")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_result_pages, page_range): page_range for page_range in page_ranges}
        for index, future in enumerate(as_completed(futures), 1):
            page_range = futures[future]
            try:
                page_products = future.result()
                all_results.extend(page_products)
                print(f"  --> 已完成區段 {index}/{len(page_ranges)}（第 {page_range[0]}~{page_range[-1]} 頁），取得 {len(page_products)} 筆壽險商品。")
            except Exception as exc:
                print(f"[!] 第 {page_range[0]}~{page_range[-1]} 頁略過：{exc}")

    unique = {item["source_url"]: item for item in all_results if item.get("source_url")}
    all_results = list(unique.values())
    all_results.sort(key=lambda item: (item["company_name"], item["product_full_name"]))
    if not all_results:
        raise RuntimeError("未抓到任何壽險商品；拒絕用空資料覆蓋網站。")

    output_path = os.path.join(OUTPUT_DIR, "all_products_metadata.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"[OK] 共抓取 {len(all_results)} 檔壽險商品。")
    print(f"Metadata 已儲存至: {output_path}")


if __name__ == "__main__":
    main()
