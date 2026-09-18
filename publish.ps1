$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DashboardDir = "C:\Users\45454\Documents\Codex\2026-08-10\new-chat-2\outputs\dashboard"
$Owner = "lzw454543"
$RepoName = "drf-price-dashboard"

$GitCandidates = @(
  (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe"),
  (Join-Path ${env:ProgramFiles} "Git\cmd\git.exe"),
  (Join-Path ${env:ProgramFiles(x86)} "Git\cmd\git.exe")
)
$Git = $GitCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Git) { throw "Git executable not found." }

function Publish-ViaGitHubApi {
  param([Parameter(Mandatory=$true)][string]$LocalCommitSha)

  $credLines = "protocol=https`nhost=github.com`n" | & $Git credential fill
  $cred = @{}
  foreach ($line in $credLines) {
    if ($line -match "^(.*?)=(.*)$") { $cred[$matches[1]] = $matches[2] }
  }
  $pair = "{0}:{1}" -f $cred["username"], $cred["password"]
  $encodedCred = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
  $headers = @{
    Authorization = "Basic $encodedCred"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
  }
  $apiRoot = "https://api.github.com/repos/$Owner/$RepoName"
  $changedFiles = @(& $Git show --name-only --format= $LocalCommitSha | Where-Object { $_.Trim().Length -gt 0 })
  if (-not $changedFiles) { throw "Local commit $LocalCommitSha has no files to publish." }

  $ref = Invoke-RestMethod -Uri "$apiRoot/git/ref/heads/main" -Headers $headers -Method Get
  $remoteSha = $ref.object.sha
  $remoteCommit = Invoke-RestMethod -Uri "$apiRoot/git/commits/$remoteSha" -Headers $headers -Method Get

  $treeItems = @()
  foreach ($file in $changedFiles) {
    $path = Join-Path $RepoDir $file
    if (-not (Test-Path $path)) { throw "API publish does not support deleted files; missing $file." }
    $bytes = [IO.File]::ReadAllBytes($path)
    $blobBody = @{ content = [Convert]::ToBase64String($bytes); encoding = "base64" } | ConvertTo-Json
    $blob = Invoke-RestMethod -Uri "$apiRoot/git/blobs" -Headers $headers -Method Post -Body $blobBody -ContentType "application/json"
    $treeItems += @{ path = $file; mode = "100644"; type = "blob"; sha = $blob.sha }
    Write-Host "API blob created for $file"
  }

  $treeBody = @{ base_tree = $remoteCommit.tree.sha; tree = $treeItems } | ConvertTo-Json -Depth 8
  $tree = Invoke-RestMethod -Uri "$apiRoot/git/trees" -Headers $headers -Method Post -Body $treeBody -ContentType "application/json"
  $now = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
  $person = @{ name = "Codex DRF Dashboard"; email = "codex-drf@example.local"; date = $now }
  $commitBody = @{
    message = "Update dashboards with latest data"
    tree = $tree.sha
    parents = @($remoteSha)
    author = $person
    committer = $person
  } | ConvertTo-Json -Depth 8
  $commit = Invoke-RestMethod -Uri "$apiRoot/git/commits" -Headers $headers -Method Post -Body $commitBody -ContentType "application/json"
  $updateBody = @{ sha = $commit.sha; force = $false } | ConvertTo-Json
  Invoke-RestMethod -Uri "$apiRoot/git/refs/heads/main" -Headers $headers -Method Patch -Body $updateBody -ContentType "application/json" | Out-Null
  Write-Host "Published updated dashboards to GitHub Pages via API commit $($commit.sha)."
}

Copy-Item -LiteralPath (Join-Path $DashboardDir "index.html") -Destination (Join-Path $RepoDir "huadong.html") -Force
Copy-Item -LiteralPath (Join-Path $DashboardDir "echarts.min.js") -Destination (Join-Path $RepoDir "echarts.min.js") -Force
Copy-Item -LiteralPath (Join-Path $DashboardDir "大润发价格测试看板-离线版.html") -Destination (Join-Path $RepoDir "huadong-offline.html") -Force

# Normalize the East China page title using Unicode code points so Windows PowerShell 5.1 cannot misread the script encoding.
$HuadongPath = Join-Path $RepoDir "huadong.html"
$HuadongTitle = -join @(
  [char]0x534e, [char]0x4e1c, [char]0x5927, [char]0x6da6, [char]0x53d1,
  " 70g ",
  [char]0x7389, [char]0x7c73, [char]0x7247, [char]0x4ef7, [char]0x683c,
  [char]0x6d4b, [char]0x8bd5, [char]0x770b, [char]0x677f
)
$html = [System.IO.File]::ReadAllText($HuadongPath, [System.Text.Encoding]::UTF8)
$html = [regex]::Replace($html, "<title>.*?</title>", "<title>$HuadongTitle</title>", [Text.RegularExpressions.RegexOptions]::Singleline)
$html = [regex]::Replace($html, "<h1>.*?</h1>", "<h1>$HuadongTitle</h1>", [Text.RegularExpressions.RegexOptions]::Singleline)
[System.IO.File]::WriteAllText($HuadongPath, $html, (New-Object System.Text.UTF8Encoding($false)))

python (Join-Path $RepoDir "build_yonghui_dashboard.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python (Join-Path $RepoDir "build_xinshiji_dashboard.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Push-Location $RepoDir
try {
  & $Git config user.name "Codex DRF Dashboard"
  & $Git config user.email "codex-drf@example.local"
  & $Git add index.html huadong.html yonghui.html xinshiji.html offline.html huadong-offline.html yonghui-offline.html xinshiji-offline.html echarts.min.js build_yonghui_dashboard.py build_xinshiji_dashboard.py README.md .nojekyll publish.ps1
  $status = & $Git status --porcelain
  if ($status) {
    & $Git commit -m "Update dashboards with latest data" | Out-Host
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $commitSha = ((& $Git rev-parse HEAD).Trim())
    & $Git push origin main | Out-Host
    if ($LASTEXITCODE -ne 0) {
      Write-Warning "Git push failed; falling back to GitHub API."
      Publish-ViaGitHubApi -LocalCommitSha $commitSha
    } else {
      Write-Host "Published updated dashboards to GitHub Pages."
    }
  } else {
    Write-Host "Dashboards already up to date; nothing to publish."
  }
}
finally {
  Pop-Location
}
