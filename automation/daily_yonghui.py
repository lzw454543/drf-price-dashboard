# -*- coding: utf-8 -*-
"""
Yonghui daily auto-update orchestrator.
Runs end-to-end: ensure logged-in Edge CDP -> download yesterday's store detail
-> merge into latest.xlsx -> rebuild dashboard -> commit & push to GitHub.
Logged to automation/logs/. Invoked by run_daily_yonghui.ps1 scheduled task.
"""
import subprocess
import sys
import os
import time
import glob
import shutil
import datetime
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DOWNLOADS = os.path.join(HERE, "downloads")
LOGDIR = os.path.join(HERE, "logs")
os.makedirs(LOGDIR, exist_ok=True)
os.makedirs(DOWNLOADS, exist_ok=True)

LOGPATH = os.path.join(LOGDIR, "yonghui-daily-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".log")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

def log(msg):
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOGPATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def run(cmd, cwd=REPO, timeout=600, check=True):
    log("RUN: " + " ".join(str(c) for c in cmd))
    proc = subprocess.run(cmd, cwd=cwd, timeout=timeout,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    out = proc.stdout or ""
    for line in out.splitlines():
        log("  | " + line)
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(str(c) for c in cmd)}")
    return proc.returncode, out

def cdp_ready():
    try:
        urllib.request.urlopen("http://127.0.0.1:9223/json/version", timeout=3).read()
        return True
    except Exception:
        return False

def is_isolated_edge(proc):
    try:
        cmd = proc.CommandLine or ""
    except Exception:
        return False
    return "edge-cdp-profile" in cmd

def kill_isolated_edge():
    import psutil
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if p.info["name"] and p.info["name"].lower().startswith("msedge") and p.info.get("cmdline"):
                if any("edge-cdp-profile" in str(a) for a in p.info["cmdline"]):
                    p.kill()
        except Exception:
            pass
    time.sleep(4)

def start_edge():
    run([sys.executable, os.path.join(HERE, "launch_cdp.py")], timeout=120)
    for _ in range(20):
        if cdp_ready():
            return True
        time.sleep(1)
    return False

def check_login():
    code = r'''
import sys
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9223")
    ctx = b.contexts[0]
    page = None
    for pg in ctx.pages:
        if "glzx.yonghui.cn" in pg.url:
            page = pg; break
    if page is None:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.bring_to_front()
    page.goto("https://glzx.yonghui.cn/glzs/CommoditySales", wait_until="domcontentloaded")
    page.wait_for_timeout(7000)
    url = page.url
    print("FINAL_URL:" + url)
    b.close()
sys.exit(0 if "login" not in url.lower() else 1)
'''
    rc, out = run([sys.executable, "-c", code], timeout=90, check=False)
    return rc == 0, out

def copy_default_cookies():
    default = os.path.join(os.environ["LOCALAPPDATA"], "Microsoft", "Edge", "User Data")
    isolated = os.path.join(HERE, "edge-cdp-profile")
    def cp(rel):
        s, d = os.path.join(default, rel), os.path.join(isolated, rel)
        if os.path.exists(s):
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
    def cpdir(rel):
        s, d = os.path.join(default, rel), os.path.join(isolated, rel)
        if os.path.isdir(s):
            os.makedirs(d, exist_ok=True)
            for name in os.listdir(s):
                sp, dp = os.path.join(s, name), os.path.join(d, name)
                try:
                    if os.path.isdir(sp):
                        shutil.copytree(sp, dp, dirs_exist_ok=True)
                    else:
                        shutil.copy2(sp, dp)
                except Exception as e:
                    log(f"  cookie copy skip {name}: {e}")
    cp(os.path.join("Local State"))
    cp(os.path.join("Default", "Network", "Cookies"))
    cp(os.path.join("Default", "Login Data"))
    cp(os.path.join("Default", "Preferences"))
    cpdir(os.path.join("Default", "Local Storage"))
    cpdir(os.path.join("Default", "Session Storage"))
    log("cookies refreshed from default Edge profile")

def main():
    target = datetime.date.today() - datetime.timedelta(days=1)
    dstr = target.strftime("%Y-%m-%d")
    stamp = target.strftime("%Y%m%d")
    report = f"永辉{stamp}_01"
    log(f"=== Yonghui daily update for {dstr} (report {report}) ===")

    # 1. Browser
    log("ensuring Edge CDP ...")
    if not cdp_ready():
        kill_isolated_edge()
        if not start_edge():
            raise RuntimeError("CDP failed to start")
    else:
        log("CDP already running")

    ok, out = check_login()
    if not ok:
        log("session expired; attempting cookie refresh from default Edge profile")
        kill_isolated_edge()
        copy_default_cookies()
        if not start_edge():
            raise RuntimeError("CDP failed to restart after cookie refresh")
        ok, out = check_login()
        if not ok:
            raise RuntimeError("LOGIN_REQUIRED: isolated Edge session expired and default profile has no valid session either; manual login needed")
    log("login OK")

    # 2. Download
    log("downloading store detail ...")
    run([sys.executable, os.path.join(HERE, "download_range.py"), dstr, dstr, report], timeout=900)

    pattern = os.path.join(DOWNLOADS, f"*{stamp}*.csv")
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    if not files:
        raise RuntimeError(f"no downloaded CSV found for {stamp}")
    csv_path = files[0]
    log(f"CSV: {csv_path} ({os.path.getsize(csv_path)} bytes)")

    # 3. Merge
    log("merging into workbook ...")
    run([sys.executable, os.path.join(HERE, "merge_csv.py"), csv_path], timeout=600)

    # 4. Build
    log("rebuilding dashboard ...")
    run([sys.executable, os.path.join(REPO, "build_yonghui_dashboard.py")], timeout=600)

    # 5. Publish
    log("publishing to GitHub ...")
    run(["git", "add", "yonghui.html", "yonghui-offline.html"], cwd=REPO)
    _, status = run(["git", "status", "--porcelain", "yonghui.html", "yonghui-offline.html"], cwd=REPO, check=False)
    last_err = None
    if "yonghui.html" in status or "yonghui-offline.html" in status:
        run(["git", "commit", "-m", f"Update Yonghui dashboard through {dstr}"], cwd=REPO)
        for attempt in range(4):
            rc, push_out = run(["git", "push", "origin", "main"], cwd=REPO, timeout=180, check=False)
            if rc == 0:
                log("push OK")
                break
            last_err = push_out
            log(f"push failed (attempt {attempt+1}); retrying in 30s")
            time.sleep(30)
        else:
            raise RuntimeError(f"git push failed: {last_err}")
    else:
        log("no dashboard changes to commit")

    # 6. Close isolated browser to flush cookies
    kill_isolated_edge()
    log(f"=== daily update for {dstr} DONE ===")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"DAILY UPDATE FAILED: {e}")
        sys.exit(1)
