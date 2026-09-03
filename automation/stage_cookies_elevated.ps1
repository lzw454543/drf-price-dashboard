# Requires admin. Stages locked Edge profile files via a VSS shadow copy.
# Triggered on demand by daily_yonghui.py through the YonghuiStageCookies scheduled task.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$staging = Join-Path $here "cookie-staging"
$done = Join-Path $staging "_STAGE_DONE.txt"
$err  = Join-Path $staging "_STAGE_ERROR.txt"
Remove-Item $done,$err -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $staging | Out-Null

$shadow = $null
$link = Join-Path $env:TEMP ("yh-vss-link-" + [guid]::NewGuid().ToString("N"))
try {
    $src = Join-Path $env:LOCALAPPDATA "Microsoft\Edge\User Data"
    $drive = (Get-Item $src).PSDrive.Root  # e.g. C:\
    $res = Invoke-CimMethod -ClassName Win32_ShadowCopy -MethodName Create -Arguments @{ Volume = $drive; Context = "ClientAccessible" }
    if ($res.ReturnValue -ne 0) { throw "ShadowCopy.Create returned $($res.ReturnValue)" }
    $shadow = Get-CimInstance Win32_ShadowCopy -Filter "ID='$($res.ShadowID)'"
    $dev = $shadow.DeviceObject.TrimEnd("\")
    cmd /c mklink /d "$link" "$dev\" | Out-Null
    if (-not (Test-Path $link)) { throw "shadow link not created: $dev" }

    $relRoot = $src.Substring(3)  # strip "C:\"
    function Copy-Shadow($rel, [switch]$IsDir) {
        $s = Join-Path $link (Join-Path $relRoot $rel)
        $d = Join-Path $staging $rel
        New-Item -ItemType Directory -Force (Split-Path -Parent $d) | Out-Null
        if ($IsDir) {
            if (Test-Path $s) { robocopy "$s" "$d" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null }
        } else {
            if (Test-Path $s) { Copy-Item -LiteralPath $s -Destination $d -Force }
        }
    }
    Copy-Shadow "Local State"
    Copy-Shadow "Default\Network\Cookies"
    Copy-Shadow "Default\Network\Cookies-journal"
    Copy-Shadow "Default\Local Storage\leveldb" -IsDir
    Remove-Item (Join-Path $staging "Default\Local Storage\leveldb\LOCK") -Force -ErrorAction SilentlyContinue

    $cookieDest = Join-Path $staging "Default\Network\Cookies"
    if (-not (Test-Path $cookieDest)) { throw "staged Cookies file missing" }
    "staged at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), size=$((Get-Item $cookieDest).Length)" | Out-File -FilePath $done -Encoding utf8
}
catch {
    "ERROR at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'): $($_.Exception.Message)" | Out-File -FilePath $err -Encoding utf8
    exit 1
}
finally {
    if (Test-Path $link) { cmd /c rmdir "$link" | Out-Null }
    if ($shadow) { Invoke-CimMethod -InputObject $shadow -MethodName Delete | Out-Null }
}
