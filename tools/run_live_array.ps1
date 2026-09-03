# Turnkey runner for the live 2-phone SHRUTI phased array demo.
param(
    [int]$Seconds = 20,
    [string]$Beamformer = "das",
    [string]$RecordToggle = "data/toggle_live"
)

$adb = "C:/Users/DELL/AppData/Local/Microsoft/WinGet/Packages/Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe/platform-tools/adb.exe"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "    SHRUTI 2-PHONE PHASED ARRAY LIVE DEMO LAUNCHER       " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Reverse port forwarding
Write-Host "[1/3] Setting up USB reverse port forward on both devices..." -ForegroundColor Yellow
& $adb -s 001593529000048 reverse tcp:8765 tcp:8765
& $adb -s Y5GI8XVGPVRO99W8 reverse tcp:8765 tcp:8765

# 2. Launch applications
Write-Host "[2/3] Launching dev.shruti on Phone 0 (Nothing) & Phone 1 (realme)..." -ForegroundColor Yellow
& $adb -s 001593529000048 shell am start -n dev.shruti/.ui.MainActivity --ez dev.shruti.auto_start true --ei dev.shruti.phone_id 0 --ez dev.shruti.is_master true
& $adb -s Y5GI8XVGPVRO99W8 shell am start -n dev.shruti/.ui.MainActivity --ez dev.shruti.auto_start true --ei dev.shruti.phone_id 1 --ez dev.shruti.is_master false

# 3. Start Live Array Processor
Write-Host "[3/3] Starting Live Array Processor & Offline ASR ($Seconds seconds)..." -ForegroundColor Green
python tools/live_two_phones_radar.py --seconds $Seconds --beamformer $Beamformer --record-toggle $RecordToggle --ascii

# 4. Stop capture on exit to silence chirps
Write-Host "`nDemo run finished. Stopping capture and chirp service..." -ForegroundColor Yellow
& $adb -s 001593529000048 shell am force-stop dev.shruti
& $adb -s Y5GI8XVGPVRO99W8 shell am force-stop dev.shruti
Write-Host "All devices silenced. Stems preserved in $RecordToggle." -ForegroundColor Green
