$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DashboardDir = "C:\Users\45454\Documents\Codex\2026-08-10\new-chat-2\outputs\dashboard"

$GitCandidates = @(
  (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"),
  (Join-Path ${env:ProgramFiles} "Git\cmd\git.exe"),
  (Join-Path ${env:ProgramFiles(x86)} "Git\cmd\git.exe")
)
$Git = $GitCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Git) { throw "Git executable not found." }

Copy-Item -LiteralPath (Join-Path $DashboardDir "index.html") -Destination (Join-Path $RepoDir "index.html") -Force
Copy-Item -LiteralPath (Join-Path $DashboardDir "echarts.min.js") -Destination (Join-Path $RepoDir "echarts.min.js") -Force
Copy-Item -LiteralPath (Join-Path $DashboardDir "大润发价格测试看板-离线版.html") -Destination (Join-Path $RepoDir "offline.html") -Force

# Normalize shared page title so link previews and browser tabs are consistent
$IndexPath = Join-Path $RepoDir "index.html"
$html = [System.IO.File]::ReadAllText($IndexPath, [System.Text.Encoding]::UTF8)
$html = $html -replace "<title>.*?</title>", "<title>大单品相关测试看板</title>"
$html = $html -replace "<h1>.*?</h1>", "<h1>大单品相关测试看板</h1>"
[System.IO.File]::WriteAllText($IndexPath, $html, (New-Object System.Text.UTF8Encoding($false)))

python (Join-Path $RepoDir "build_yonghui_dashboard.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python (Join-Path $RepoDir "build_xinshiji_dashboard.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Push-Location $RepoDir
try {
  & $Git config user.name "Codex DRF Dashboard"
  & $Git config user.email "codex-drf@example.local"
  & $Git add index.html yonghui.html xinshiji.html offline.html yonghui-offline.html xinshiji-offline.html echarts.min.js build_yonghui_dashboard.py build_xinshiji_dashboard.py README.md .nojekyll publish.ps1
  $status = & $Git status --porcelain
  if ($status) {
    & $Git commit -m "Update dashboards with latest data" | Out-Host
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Git push origin main | Out-Host
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Published updated dashboards to GitHub Pages."
  } else {
    Write-Host "Dashboards already up to date; nothing to publish."
  }
}
finally {
  Pop-Location
}

