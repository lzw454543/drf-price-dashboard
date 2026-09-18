from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EAST_DIR = Path(r"C:\Users\45454\Documents\ChatGPT\销售中台数据分析\大润发看板")
CONFIG_PATH = EAST_DIR / "config.json"
BUILDER_PATH = EAST_DIR / "build_dashboard_custom.py"
OUTPUT_DIR = EAST_DIR / "output"


def latest_workbook() -> Path:
    workbooks = sorted(
        EAST_DIR.glob("华东大润发*.xlsx"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not workbooks:
        raise FileNotFoundError(f"No 华东大润发 workbook found in {EAST_DIR}")
    return workbooks[0]


def main() -> None:
    workbook = latest_workbook()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            str(BUILDER_PATH),
            "--input",
            str(workbook),
            "--config",
            str(CONFIG_PATH),
            "--output-dir",
            str(OUTPUT_DIR),
            "--echarts",
            str(ROOT / "echarts.min.js"),
        ],
        cwd=EAST_DIR,
        check=True,
    )
    shutil.copyfile(OUTPUT_DIR / "index.html", ROOT / "huadong.html")
    shutil.copyfile(OUTPUT_DIR / "offline.html", ROOT / "huadong-offline.html")
    print(f"Updated huadong dashboard from {workbook.name}")


if __name__ == "__main__":
    main()
