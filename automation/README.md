# 永辉数据自动化

## 每日流程

1. **自动下载** (需要 Edge 以调试端口运行):
   ```
   python automation/yonghui_download.py
   ```
   默认下载昨天的数据，也可指定日期和序号:
   ```
   python automation/yonghui_download.py 2026-08-18 01
   ```

2. **合并到数据源**:
   ```
   python automation/merge_csv.py automation/downloads/永辉20260818_01.csv
   ```

3. **重建看板**:
   ```
   python build_yonghui_dashboard.py
   ```

4. **发布**:
   ```
   git add yonghui.html yonghui-offline.html
   git commit -m "Update Yonghui dashboard"
   git push
   ```

## Edge 调试模式启动

关闭所有 Edge 后运行:
```
msedge.exe --remote-debugging-port=9223 --user-data-dir=automation/edge-cdp-profile https://glzx.yonghui.cn/userCenter
```
首次需要手动登录（含滑块验证码），之后会话会保留。
