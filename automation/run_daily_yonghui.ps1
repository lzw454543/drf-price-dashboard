$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $ScriptDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir ("yonghui-task-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
Start-Transcript -Path $LogPath -Append | Out-Null
try {
    Write-Host "Starting Yonghui daily update at $(Get-Date -Format s)"
    $py = $ScriptDir + "\daily_yonghui.py"
    python $py
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
    Write-Host "daily_yonghui.py exited with code $code"
    Stop-Transcript | Out-Null
    exit $code
}
catch {
    Write-Host "ERROR: $($_.Exception.Message)"
    Write-Host $_.ScriptStackTrace
    Stop-Transcript | Out-Null
    exit 1
}
