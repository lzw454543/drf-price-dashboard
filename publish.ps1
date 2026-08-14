$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DashboardDir = "C:\Users\45454\Documents\Codex\2026-08-10\new-chat-2\outputs\dashboard"

Copy-Item -LiteralPath (Join-Path $DashboardDir "index.html") -Destination (Join-Path $RepoDir "index.html") -Force
Copy-Item -LiteralPath (Join-Path $DashboardDir "echarts.min.js") -Destination (Join-Path $RepoDir "echarts.min.js") -Force
Copy-Item -LiteralPath (Join-Path $DashboardDir "大润发价格测试看板-离线版.html") -Destination (Join-Path $RepoDir "offline.html") -Force

python (Join-Path $RepoDir "build_yonghui_dashboard.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Push-Location $RepoDir
try {
  git config user.name "Codex DRF Dashboard"
  git config user.email "codex-drf@example.local"
  git add index.html yonghui.html offline.html yonghui-offline.html echarts.min.js build_yonghui_dashboard.py README.md .nojekyll publish.ps1
  $status = git status --porcelain
  if ($status) {
    git commit -m "Add Yonghui promotion dashboard" | Out-Host
    git push origin main | Out-Host
    Write-Host "Published updated dashboards to GitHub Pages."
  } else {
    Write-Host "Dashboards already up to date; nothing to publish."
  }
}
finally {
  Pop-Location
}
