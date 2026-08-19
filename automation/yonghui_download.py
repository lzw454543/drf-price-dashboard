"""
永辉供零在线 - 商品销售门店明细自动下载
用法:
  python yonghui_download.py [YYYY-MM-DD] [序号]
  默认日期=昨天, 序号=1
  文件名: 永辉YYYYMMDD_01.csv

入口自动处理:
  1. 用户中心页 -> 点击顶部"供零易商"进入
  2. 已在供零易商 -> 直接导航到商品销售
前提: Edge 以调试端口启动 (--remote-debugging-port=9223) 且已登录
"""
import sys, os, time, datetime
from playwright.sync_api import sync_playwright

CDP_URL = "http://127.0.0.1:9223"
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def close_dialogs(page):
    page.evaluate("""() => {
        document.querySelectorAll('.el-dialog__wrapper').forEach(e => { e.style.display='none'; });
        document.querySelectorAll('.v-modal').forEach(e => e.remove());
    }""")
    page.keyboard.press("Escape")
    time.sleep(0.5)


def set_date(input_el, date_str, page):
    input_el.click(click_count=3)
    time.sleep(0.2)
    page.keyboard.press("Control+a")
    time.sleep(0.1)
    page.keyboard.type(date_str, delay=30)
    time.sleep(0.3)
    page.keyboard.press("Enter")
    time.sleep(0.5)


def main():
    if len(sys.argv) > 1:
        target_date = datetime.datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    else:
        target_date = datetime.date.today() - datetime.timedelta(days=1)
    seq = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    date_str = target_date.strftime("%Y/%m/%d")
    report_name = f"永辉{target_date.strftime('%Y%m%d')}_{seq:02d}"
    print(f"目标日期: {date_str}, 报表: {report_name}")

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]

        # Find existing CommoditySales page
        page = None
        for pg in ctx.pages:
            if "CommoditySales" in pg.url:
                page = pg
                break

        if page:
            print("已在商品销售页面")
            page.bring_to_front()
        else:
            # Use first page
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.bring_to_front()
            url = page.url

            # Wait for login if needed
            if "/login" in url:
                print("等待登录...")
                for i in range(120):
                    time.sleep(3)
                    if "/login" not in page.url and page.locator(".login-btn").count() == 0:
                        print("已登录:", page.url)
                        break
                time.sleep(3)
                url = page.url

            # Case 1: userCenter -> click 供零易商
            if "userCenter" in url:
                print("在用户中心，点击供零易商...")
                page.get_by_text("供零易商", exact=True).first.click()
                time.sleep(12)
                for pg in ctx.pages:
                    if "CommoditySales" in pg.url:
                        page = pg
                        break
            # Case 2: in glzs but not commodity sales
            elif "glzs" in url:
                print("在供零易商内，导航到商品销售...")
                page.goto("https://glzx.yonghui.cn/glzs/CommoditySales", wait_until="domcontentloaded")
                time.sleep(10)
            else:
                # Just navigate directly
                print(f"当前页面 {url}，直接导航到商品销售...")
                page.goto("https://glzx.yonghui.cn/glzs/CommoditySales", wait_until="domcontentloaded")
                time.sleep(12)

        page.bring_to_front()
        time.sleep(2)
        print("页面:", page.url)

        # Close any blocking dialogs
        close_dialogs(page)

        # Set dates
        start = page.locator("input.el-input__inner").nth(0)
        end = page.locator("input.el-input__inner").nth(1)
        set_date(start, date_str, page)
        set_date(end, date_str, page)
        page.mouse.click(700, 400)
        time.sleep(1)
        print(f"日期: {start.input_value()} ~ {end.input_value()}")

        # Query
        print("查询...")
        page.locator("button.el-button--primary").filter(has_text="查询").click()
        time.sleep(15)

        # Export store detail (second export button)
        print("导出商品销售门店明细...")
        page.locator("button.export-btn").nth(1).click()
        time.sleep(3)

        # Name report
        dialog = page.locator(".el-dialog").filter(has_text="报表命名")
        inp = dialog.locator("input").first
        inp.click(click_count=3)
        page.keyboard.press("Control+a")
        time.sleep(0.1)
        page.keyboard.type(report_name, delay=50)
        time.sleep(0.3)
        dialog.locator("button").filter(has_text="确 定").click()
        print(f"报表 {report_name} 已提交离线中心")
        time.sleep(5)

        # Close any confirmation dialog then open offline center
        close_dialogs(page)
        print("打开离线中心...")
        page.locator(".offline-center").first.click()
        time.sleep(4)

        # Wait for completion and download
        print("等待生成...")
        downloaded = False
        for attempt in range(36):
            time.sleep(5)
            items = page.locator(".async-task-item")
            if items.count() == 0:
                continue
            for i in range(min(items.count(), 5)):
                name = items.nth(i).locator(".task-name").inner_text().strip()
                txt = items.nth(i).inner_text().replace("\n", " ")
                if name == report_name and "100%" in txt:
                    print(f"生成完成 ({attempt*5}s)，开始下载...")
                    with page.expect_download(timeout=30000) as dl_info:
                        items.nth(i).locator(".task-download").click()
                    dl = dl_info.value
                    save_path = os.path.join(DOWNLOAD_DIR, dl.suggested_filename)
                    dl.save_as(save_path)
                    print(f"已保存: {save_path} ({os.path.getsize(save_path)} bytes)")
                    downloaded = True
                    break
            if downloaded:
                break
            if attempt % 3 == 0:
                for i in range(min(items.count(), 3)):
                    n = items.nth(i).locator(".task-name").inner_text().strip()
                    print(f"  队首: {n}")

        if not downloaded:
            print("警告: 未在3分钟内完成，请手动在离线中心下载")


if __name__ == "__main__":
    main()
