$TaskName = "YonghuiDailyUpdate"
$AtTime = "10:30"
$ScriptDir = "C:\Users\45454\Documents\Codex\drf-price-dashboard\automation"
$RunScript = Join-Path $ScriptDir "run_daily_yonghui.ps1"

if (-not (Test-Path $RunScript)) { throw "Missing $RunScript" }

$trigger = New-ScheduledTaskTrigger -Daily -At $AtTime

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunScript`"" `
    -WorkingDirectory $ScriptDir

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Trigger $trigger `
    -Action $action `
    -Principal $principal `
    -Settings $settings `
    -Description "Daily 10:30 Yonghui portal download -> merge -> dashboard rebuild -> GitHub publish." `
    -Force | Out-Null

Write-Host "Registered '$TaskName' at $AtTime daily."
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object NextRunTime
