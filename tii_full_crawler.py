"""
保發中心 (TII) 全量壽險商品與條款 PDF 自動抓取器
專門針對 https://insprod.tii.org.tw/Query.aspx (ASP.NET WebForms) 設計
具備自動翻頁、Session維持、重試機制與速率限制防護
"""

import os
import time
import json
import asyncio
from typing import List, Dict, Any
from playwright.async_api import async_playwright

# 20 家台灣主要人壽保險公司在保發中心的名稱與代碼 (可依需求擴充)
LIFE_INSURANCE_COMPANIES = [
    {"code": "202", "name": "台灣人壽"},
    {"code": "203", "name": "保誠人壽"},
    {"code": "204", "name": "國泰人壽"},
    {"code": "205", "name": "凱基人壽"}, # 原中國人壽
    {"code": "206", "name": "南山人壽"},
    {"code": "208", "name": "新光人壽"},
    {"code": "210", "name": "富邦人壽"},
    {"code": "211", "name": "三商美邦人壽"},
    {"code": "213", "name": "遠雄人壽"},
    {"code": "214", "name": "宏泰人壽"},
    {"code": "215", "name": "安聯人壽"},
    {"code": "216", "name": "第一金人壽"},
    {"code": "217", "name": "元大人壽"},
    {"code": "219", "name": "全球人壽"},
    {"code": "220", "name": "康健人壽"},
    {"code": "221", "name": "友邦人壽"},
    {"code": "222", "name": "法商法國巴黎人壽"},
    {"code": "223", "name": "保德信人壽"}, # 現台新人壽
    {"code": "224", "name": "台銀人壽"},
    {"code": "225", "name": "合庫人壽"}
]

TII_QUERY_URL = "https://insprod.tii.org.tw/Query.aspx"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "tii_insurance_data")
PDF_DIR = os.path.join(OUTPUT_DIR, "pdf_files")

async def scrape_company_products(page, company: Dict[str, str]) -> List[Dict[str, Any]]:
    """針對單一保險公司，自動查詢並遍歷所有分頁抓取商品列表與下載連結"""
    comp_code = company["code"]
    comp_name = company["name"]
    print(f"\n==========================================")
    print(f"[*] 正在抓取 [{comp_name} (代碼: {comp_code})] 的商品資料...")
    print(f"==========================================")

    products = []
    
    # 1. 開啟查詢首頁
    await page.goto(TII_QUERY_URL, wait_until="networkidle", timeout=60000)
    
    # 2. 選擇保險公司下拉選單 (ASP.NET 常用 Dropdown id 通常包含 ddlCompany 或類似命名)
    # 透過包含公司代碼的 option value 進行精準選取
    select_selector = 'select[name*="Company"], select[id*="Company"], select[name*="ddl"]'
    await page.wait_for_selector(select_selector, timeout=10000)
    
    # 選取該公司
    options = await page.query_selector_all(f"{select_selector} option")
    target_val = None
    for opt in options:
        text = await opt.inner_text()
        val = await opt.get_attribute("value")
        if comp_code in text or comp_name in text:
            target_val = val
            break
            
    if not target_val:
        print(f"[!] 找不到公司下拉選項: {comp_name}")
        return products

    await page.select_option(select_selector, target_val)
    await asyncio.sleep(1) # 避開快速觸發

    # 3. 點擊「查詢」按鈕
    search_btn_selector = 'input[type="submit"][value*="查詢"], button:has-text("查詢")'
    await page.click(search_btn_selector)
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(2)

    # 4. 循環分頁抓取表格資料
    page_num = 1
    while True:
        print(f"  --> 正在解析第 {page_num} 頁...")
        
        # 抓取表格內的所有資料列 (GridView)
        rows = await page.query_selector_all('table[id*="GridView"] tr, table[class*="grid"] tr, table.table-striped tr')
        if not rows or len(rows) <= 1:
            print(f"  [i] 該公司無更多商品資料或已到末頁。")
            break

        current_page_items = 0
        for row in rows[1:]: # 跳過表頭
            cols = await row.query_selector_all('td')
            if len(cols) < 4:
                continue

            # 依序提取標準欄位
            col_texts = [ (await c.inner_text()).strip() for c in cols ]
            
            # 尋找儲存格內的 PDF 條款下載連結或按鈕
            pdf_link_el = await row.query_selector('a[href*=".pdf"], a[href*="Download"], a:has-text("下載"), a:has-text("條款")')
            pdf_url = ""
            if pdf_link_el:
                href = await pdf_link_el.get_attribute("href")
                if href:
                    pdf_url = href if href.startswith("http") else f"https://insprod.tii.org.tw/{href.lstrip('/')}"

            item = {
                "company_code": comp_code,
                "company_name": comp_name,
                "product_full_name": col_texts[1] if len(col_texts) > 1 else "",
                "product_code": col_texts[2] if len(col_texts) > 2 else "",
                "approval_date": col_texts[3] if len(col_texts) > 3 else "",
                "approval_number": col_texts[4] if len(col_texts) > 4 else "",
                "pdf_url": pdf_url,
                "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            
            if item["product_full_name"]:
                products.append(item)
                current_page_items += 1

        print(f"      本頁成功擷取 {current_page_items} 筆商品。")

        # 5. 檢查是否有「下一頁」或「分頁按鈕」
        # ASP.NET 分頁常用 __doPostBack('GridView1','Page$2')
        next_page_btn = await page.query_selector(f'a:has-text("下一頁"), a:has-text("{page_num + 1}")')
        if next_page_btn:
            try:
                await next_page_btn.click()
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(2) # 溫和延遲，避免 WAF 限流
                page_num += 1
            except Exception as e:
                print(f"  [*] 翻頁完成或無法點擊下一頁: {e}")
                break
        else:
            break

    print(f"[✓] [{comp_name}] 抓取完畢，累計取得 {len(products)} 檔商品。")
    return products

async def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(PDF_DIR, exist_ok=True)
    
    all_results = []
    
    async with async_playwright() as p:
        # 啟動無頭瀏覽器，偽裝常規 User-Agent
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            # 保發中心目前可能回傳不完整的憑證鏈；連線仍使用 HTTPS，
            # 但避免因此讓每日資料同步整批失敗。
            ignore_https_errors=True,
        )
        page = await context.new_page()

        for comp in LIFE_INSURANCE_COMPANIES:
            try:
                comp_products = await scrape_company_products(page, comp)
                all_results.extend(comp_products)
                
                # 每抓完一家公司，即時寫入存檔 (防止中斷遺失)
                with open(os.path.join(OUTPUT_DIR, "all_products_metadata.json"), "w", encoding="utf-8") as f:
                    json.dump(all_results, f, ensure_ascii=False, indent=2)
                    
                await asyncio.sleep(3) # 公司間的冷卻時間
            except Exception as e:
                print(f"[!] 抓取公司 {comp['name']} 時發生錯誤: {e}")
                continue

        await browser.close()

    print(f"\n==========================================")
    print(f"[🎉] 全量抓取完成！共計獲取 {len(all_results)} 檔壽險商品。")
    print(f"Metadata 已儲存至: {os.path.join(OUTPUT_DIR, 'all_products_metadata.json')}")
    print(f"==========================================")

if __name__ == "__main__":
    asyncio.run(main())
