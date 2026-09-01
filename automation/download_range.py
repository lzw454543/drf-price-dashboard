# -*- coding: utf-8 -*-
import sys, os, time
from playwright.sync_api import sync_playwright

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def main():
    if len(sys.argv) < 3:
        print('usage: download_range.py YYYY-MM-DD YYYY-MM-DD [report_name]')
        sys.exit(1)
    start_date, end_date = sys.argv[1], sys.argv[2]
    report = sys.argv[3] if len(sys.argv) > 3 else f'yh-{start_date}-{end_date}'
    d1 = '/'.join([start_date[:4], start_date[5:7], start_date[8:]])
    d2 = '/'.join([end_date[:4], end_date[5:7], end_date[8:]])
    print(f'target {d1} ~ {d2}, report {report}', flush=True)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp('http://127.0.0.1:9223')
        ctx = browser.contexts[0]
        page = None
        for pg in ctx.pages:
            if 'CommoditySales' in pg.url:
                page = pg
                break
        if not page:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.bring_to_front()
            if 'userCenter' in page.url or ('login' not in page.url and 'glzs' not in page.url):
                try:
                    page.get_by_text('\u4f9b\u96f6\u6613\u5546', exact=True).first.click(timeout=8000)
                    time.sleep(12)
                except Exception:
                    page.goto('https://glzx.yonghui.cn/glzs/CommoditySales', wait_until='domcontentloaded')
                    time.sleep(12)
                for pg in ctx.pages:
                    if 'CommoditySales' in pg.url:
                        page = pg
                        break
            else:
                page.goto('https://glzx.yonghui.cn/glzs/CommoditySales', wait_until='domcontentloaded')
                time.sleep(12)
        page.bring_to_front()
        time.sleep(2)
        print('page:', page.url, flush=True)
        if 'login' in page.url.lower():
            print('LOGIN_REQUIRED')
            sys.exit(3)

        def close_dialogs():
            page.evaluate("""() => {
                document.querySelectorAll('.el-dialog__wrapper').forEach(e => e.style.display='none');
                document.querySelectorAll('.v-modal').forEach(e => e.remove());
            }""")
            page.keyboard.press('Escape')
            time.sleep(0.5)

        def set_date(inp, val):
            inp.click(click_count=3)
            time.sleep(0.3)
            page.keyboard.press('Control+a')
            time.sleep(0.15)
            page.keyboard.type(val, delay=40)
            time.sleep(0.4)
            page.keyboard.press('Enter')
            time.sleep(1.0)

        close_dialogs()
        inputs = page.locator('input.el-input__inner')
        start = inputs.nth(0)
        end = inputs.nth(1)
        print(f'before: {start.input_value()} ~ {end.input_value()}', flush=True)
        set_date(start, d1)
        set_date(end, d2)
        page.mouse.click(700, 400)
        time.sleep(1.5)
        print(f'set: {start.input_value()} ~ {end.input_value()}', flush=True)

        print('querying...', flush=True)
        page.locator('button.el-button--primary').filter(has_text='\u67e5\u8be2').click()
        time.sleep(20)

        print('exporting...', flush=True)
        page.locator('button.export-btn').nth(1).click()
        time.sleep(4)
        dialog = page.locator('.el-dialog').filter(has_text='\u62a5\u8868\u547d\u540d')
        inp = dialog.locator('input').first
        inp.click(click_count=3)
        page.keyboard.press('Control+a')
        time.sleep(0.15)
        page.keyboard.type(report, delay=40)
        time.sleep(0.5)
        dialog.locator('button').filter(has_text='\u786e \u5b9a').click()
        print(f'submitted {report}', flush=True)
        time.sleep(8)

        close_dialogs()
        page.locator('.offline-center').first.click()
        time.sleep(5)
        print('waiting for offline report...', flush=True)
        for attempt in range(60):
            time.sleep(5)
            items = page.locator('.async-task-item')
            n = items.count()
            if n == 0:
                continue
            for i in range(min(n, 10)):
                item = items.nth(i)
                try:
                    name = item.locator('.task-name').inner_text().strip()
                    txt = item.inner_text().replace('\n', ' ')
                except Exception:
                    continue
                if name == report and '100%' in txt:
                    print(f'  [{attempt*5}s] match[{i}] {txt[:100]}', flush=True)
                    btn = item.locator('.task-download')
                    try:
                        if not btn.is_visible(timeout=3000):
                            item.scroll_into_view_if_needed(timeout=5000)
                            time.sleep(0.5)
                        with page.expect_download(timeout=30000) as dl_info:
                            btn.click(timeout=10000)
                        dl = dl_info.value
                        sp = os.path.join(DOWNLOAD_DIR, dl.suggested_filename)
                        dl.save_as(sp)
                        print(f'SAVED:{sp}|{os.path.getsize(sp)}', flush=True)
                        return
                    except Exception as e:
                        print(f'  item {i} click failed: {e}; trying next', flush=True)
                        continue
        print('TIMEOUT waiting for report')
        sys.exit(4)

if __name__ == '__main__':
    main()
