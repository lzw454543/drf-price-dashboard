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
    ps_cmd = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
              "Where-Object { $_.CommandLine -like '*edge-cdp-profile*' } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd],
                   capture_output=True, text=True, timeout=60)
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
    staging = {"dir": None}

    def stage_via_vss():
        if staging["dir"]:
            return staging["dir"]
        stg = os.path.join(HERE, "cookie-staging")
        done, err = os.path.join(stg, "_STAGE_DONE.txt"), os.path.join(stg, "_STAGE_ERROR.txt")
        for m in (done, err):
            try:
                os.remove(m)
            except OSError:
                pass
        rc, out = run(["schtasks", "/run", "/tn", "YonghuiStageCookies"], timeout=60, check=False)
        if rc != 0:
            raise RuntimeError(f"failed to start YonghuiStageCookies task: {out.strip()}")
        for _ in range(36):
            time.sleep(5)
            if os.path.exists(done):
                log("VSS staging done: " + open(done, encoding="utf-8", errors="replace").read().strip())
                staging["dir"] = stg
                return stg
            if os.path.exists(err):
                raise RuntimeError("elevated cookie staging failed: " + open(err, encoding="utf-8", errors="replace").read().strip())
        raise RuntimeError("timed out waiting for YonghuiStageCookies staging task")

    def readable(path):
        try:
            with open(path, "rb"):
                return True
        except OSError:
            return False

    def resolve(rel, is_dir=False):
        s = os.path.join(default, rel)
        if is_dir:
            if not os.path.isdir(s):
                return None
            locked = False
            for root, _dirs, files in os.walk(s):
                for n in files:
                    if n == "LOCK":
                        continue
                    if not readable(os.path.join(root, n)):
                        locked = True
                        break
                if locked:
                    break
        else:
            if not os.path.exists(s):
                return None
            locked = not readable(s)
        if locked:
            log(f"default Edge profile file locked ({rel}); using elevated VSS staging")
            stg = stage_via_vss()
            s2 = os.path.join(stg, rel)
            return s2 if (os.path.isdir(s2) if is_dir else os.path.exists(s2)) else None
        return s

    def cp(rel, critical=False):
        s = resolve(rel)
        if not s:
            return
        d = os.path.join(isolated, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        try:
            shutil.copy2(s, d)
        except OSError as e:
            if critical:
                raise
            log(f"  cookie copy skip {rel}: {e}")

    def cpdir(rel):
        s = resolve(rel, is_dir=True)
        if not s:
            return
        d = os.path.join(isolated, rel)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        for name in os.listdir(s):
            sp, dp = os.path.join(s, name), os.path.join(d, name)
            try:
                if os.path.isdir(sp):
                    shutil.copytree(sp, dp, dirs_exist_ok=True, ignore=shutil.ignore_patterns("LOCK"))
                else:
                    shutil.copy2(sp, dp)
            except Exception as e:
                log(f"  cookie copy skip {name}: {e}")
        lock = os.path.join(d, "LOCK")
        if os.path.exists(lock):
            try:
                os.remove(lock)
            except OSError:
                pass

    cp(os.path.join("Local State"), critical=True)
    cp(os.path.join("Default", "Network", "Cookies"), critical=True)
    cp(os.path.join("Default", "Network", "Cookies-journal"))
    cp(os.path.join("Default", "Login Data"))
    cp(os.path.join("Default", "Preferences"))
    cpdir(os.path.join("Default", "Local Storage"))
    cpdir(os.path.join("Default", "Session Storage"))
    log("cookies refreshed from default Edge profile")

def close_isolated_edge():
    """Graceful CDP close so Chromium flushes cookies; hard kill as fallback."""
    code = r'''
from playwright.sync_api import sync_playwright
try:
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp("http://127.0.0.1:9223")
        b.close()
except Exception:
    pass
'''
    run([sys.executable, "-c", code], timeout=60, check=False)
    time.sleep(3)
    kill_isolated_edge()

def notify_login_needed():
    """Leave the isolated Edge window open at the login page and alert the user.
    Yonghui auth is an in-memory session cookie: it cannot be copied from disk,
    so a one-time manual login in the automation Edge window is required."""
    flag = os.path.join(LOGDIR, "LOGIN_NEEDED.txt")
    msg = ("永辉销售看板自动化无法登录。\n\n"
           "请在自动打开的 Edge 自动化窗口里完成永辉供零易商登录，\n"
           "登录成功后无需其他操作，次日 10:30 的任务将自动恢复。\n\n"
           f"时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    try:
        with open(flag, "w", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass
    ps = (
        "Add-Type -AssemblyName PresentationFramework; "
        f"[System.Windows.MessageBox]::Show('{msg.replace(chr(10), ' ')}', "
        "'永辉自动化需要重新登录', 'OK', 'Warning') | Out-Null"
    )
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-Command", ps])
    except Exception:
        pass


def start_github_proxy(port=18443, ip="140.82.112.4"):
    """Start a local CONNECT proxy mapping github.com to a reachable IP."""
    import socket
    import threading
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(50)
    override = {"github.com": ip, "api.github.com": ip}

    def pipe(a, b):
        try:
            while True:
                d = a.recv(65536)
                if not d:
                    break
                b.sendall(d)
        except Exception:
            pass
        finally:
            for x in (a, b):
                try:
                    x.shutdown(socket.SHUT_RD)
                except Exception:
                    pass

    def handle(client):
        up = None
        try:
            client.settimeout(15)
            req = b""
            while b"\r\n\r\n" not in req:
                chunk = client.recv(4096)
                if not chunk:
                    break
                req += chunk
            parts = req.split(b"\r\n", 1)[0].decode("latin1").split()
            if not parts or parts[0].upper() != "CONNECT":
                client.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                return
            host, prt = parts[1].rsplit(":", 1)
            up = socket.create_connection((override.get(host, host), int(prt)), timeout=15)
            client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            client.settimeout(None)
            up.settimeout(None)
            t1 = threading.Thread(target=pipe, args=(client, up), daemon=True)
            t2 = threading.Thread(target=pipe, args=(up, client), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        except Exception as e:
            log(f"proxy conn error: {e}")
        finally:
            for s in (client, up):
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass

    def loop():
        while True:
            try:
                c, _ = srv.accept()
                threading.Thread(target=handle, args=(c,), daemon=True).start()
            except Exception:
                break

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return f"http://127.0.0.1:{port}"


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
        log("LOGIN_REQUIRED: isolated Edge session is gone (yonghui auth is memory-only, cannot be copied from disk)")
        notify_login_needed()
        raise RuntimeError("LOGIN_REQUIRED: please log in manually in the automation Edge window (left open at the login page)")
    log("login OK")
    flag = os.path.join(LOGDIR, "LOGIN_NEEDED.txt")
    if os.path.exists(flag):
        try:
            os.remove(flag)
        except OSError:
            pass

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
        pushed = False
        for attempt in range(4):
            rc, push_out = run(["git", "push", "origin", "main"], cwd=REPO, timeout=180, check=False)
            if rc == 0:
                log("push OK")
                pushed = True
                break
            last_err = push_out
            log(f"direct push failed (attempt {attempt+1}): {str(push_out)[-200:]}")
            if attempt == 1:
                log("starting local GitHub proxy fallback")
                proxy = start_github_proxy()
                rc2, push_out2 = run(["git", "-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}",
                                       "push", "origin", "main"], cwd=REPO, timeout=240, check=False)
                if rc2 == 0:
                    log("push OK via proxy")
                    pushed = True
                    break
                last_err = push_out2
                log(f"proxy push failed: {str(push_out2)[-200:]}")
            time.sleep(20)
        if not pushed:
            raise RuntimeError(f"git push failed: {last_err}")
    else:
        log("no dashboard changes to commit")

    # 6. Keep the isolated browser running: Yonghui auth is an in-memory
    # session cookie, so closing the browser would force a manual re-login.
    log(f"=== daily update for {dstr} DONE (isolated Edge kept alive) ===")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"DAILY UPDATE FAILED: {e}")
        sys.exit(1)
