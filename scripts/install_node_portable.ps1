# Per-user (no admin) Node.js for the Desktop Commander plugin, which starts with
# "npx -y @wonderwhy-er/desktop-commander@latest".
#  1. download the official nodejs.org Windows zip and check it against SHASUMS256.txt
#  2. unpack to %LOCALAPPDATA%\Programs\nodejs  (stops if that folder already exists)
#  3. add that folder to the USER Path (HKCU; no admin)
#  4. pre-fetch the Desktop Commander package into the npx cache
# Run through install_desktop_commander.cmd from Explorer, not inside the Claude app
# sandbox (its AppData writes are hidden from other programs). Log: install_desktop_commander.log
$ErrorActionPreference = "Stop"
$ver  = "v24.20.0"
$name = "node-$ver-win-x64"
$root = Join-Path $env:LOCALAPPDATA "Programs"
$dest = Join-Path $root "nodejs"
$log  = Join-Path $PSScriptRoot "install_desktop_commander.log"
function Log($m) { "$(Get-Date -Format 'HH:mm:ss') $m" | Tee-Object -FilePath $log -Append }

Set-Content -Path $log -Value "$(Get-Date) portable Node.js install"
try {
    if (Test-Path $dest) { throw "$dest already exists -- not touching it" }
    $zip = Join-Path $env:TEMP "$name.zip"
    Log "download https://nodejs.org/dist/$ver/$name.zip"
    Invoke-WebRequest "https://nodejs.org/dist/$ver/$name.zip" -OutFile $zip -UseBasicParsing
    $sums = (Invoke-WebRequest "https://nodejs.org/dist/$ver/SHASUMS256.txt" -UseBasicParsing).Content
    $want = (($sums -split "`n") | Where-Object { $_ -match "\s$([regex]::Escape($name)).zip\s*$" } | Select-Object -First 1).Split(" ")[0].Trim()
    $got  = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
    Log "sha256 expected $want"
    Log "sha256 actual   $got"
    if (-not $want -or $want -ne $got) { throw "checksum mismatch -- nothing installed" }

    New-Item -ItemType Directory -Force $root | Out-Null
    Log "unpack to $dest"
    tar.exe -xf $zip -C $root
    Rename-Item (Join-Path $root $name) "nodejs"
    Remove-Item $zip -Force

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }
    if (($userPath -split ";") -notcontains $dest) {
        [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $dest).TrimStart(";"), "User")
        Log "added to user Path: $dest"
    }
    $env:Path = "$dest;$env:Path"
    Log ("node " + (& "$dest\node.exe" --version))
    Log ("npx " + (cmd /c "`"$dest\npx.cmd`" --version"))

    Log "pre-fetch @wonderwhy-er/desktop-commander@latest (server starts and exits on empty stdin)"
    $out = cmd /c "`"$dest\npx.cmd`" -y @wonderwhy-er/desktop-commander@latest < nul 2>&1"
    $out | Select-Object -Last 8 | ForEach-Object { Log "  $_" }
    Log "OK -- restart the Claude app so the Desktop Commander plugin connects"
} catch {
    Log "FAILED: $($_.Exception.Message)"
}
