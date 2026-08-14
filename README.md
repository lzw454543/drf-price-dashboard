# 销售数据看板

在线地址：https://lzw454543.github.io/drf-price-dashboard/

静态 GitHub Pages 看板，目前包含三个并列子菜单：

- `大润发 70g 价格测试`：展示大润发渠道三个 70g 玉米片产品的销量、销额、单价和周度 PSD。
- `永辉 112g 促销分析`：展示永辉渠道黄油太妃巴旦木玉米片 112g 与其他玉米片的每日走势、周度 PSD、门店分层和 7/21-8/1 推广效果。
- `新世纪 70g 价格弹性`：展示新世纪厚厚奶酪、生椰奶酪、七窨茉莉、浓浓巧克力四个 70g 玉米片 SKU 从 7/27 起的每日销量、销额、成交单价、完整周 PSD、降价首周价格弹性和门店分层。

文件说明：

- `index.html`：大润发在线看板
- `yonghui.html`：永辉在线看板
- `xinshiji.html`：新世纪在线看板
- `offline.html`、`yonghui-offline.html`、`xinshiji-offline.html`：单文件离线版
- `build_yonghui_dashboard.py`：从飞书同步后的 `latest.xlsx` 生成永辉看板
- `build_xinshiji_dashboard.py`：从飞书同步后的 `latest.xlsx` 生成新世纪看板
- `echarts.min.js`：图表库本地副本
- `publish.ps1`：生成静态页面并发布到 GitHub Pages

每日同步任务会更新飞书数据、重新生成三个看板，并推送到 GitHub Pages。新世纪周度 PSD 只纳入完整自然周，数据截止日所在的未满周会自动剔除。