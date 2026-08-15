# Diagnose Arelis Notify LAN ingest (port 8765).
# Run on the PC while Arelis desktop is open:
#   powershell -ExecutionPolicy Bypass -File scripts\check_inbound.ps1

$ErrorActionPreference = "Continue"
$port = 8765
$lan = $null

Write-Host "== Adapters (IPv4) ==" -ForegroundColor Cyan
Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
  ForEach-Object {
    Write-Host ("  {0,-20} {1}" -f $_.InterfaceAlias, $_.IPAddress)
    if (-not $lan -and $_.InterfaceAlias -match "Ethernet|Wi-Fi|WiFi") {
      $lan = $_.IPAddress
    }
  }
if (-not $lan) { $lan = "127.0.0.1" }

Write-Host ""
Write-Host "== Listening on $port ==" -ForegroundColor Cyan
$listen = netstat -ano | Select-String ":$port\s"
if ($listen) { $listen | ForEach-Object { Write-Host "  $_" } }
else { Write-Host "  NOTHING listening on $port — open Arelis desktop first." -ForegroundColor Red }

Write-Host ""
Write-Host "== Localhost health ==" -ForegroundColor Cyan
try {
  $r = & curl.exe -s -S -m 3 "http://127.0.0.1:$port/inbound/health"
  Write-Host "  OK: $r" -ForegroundColor Green
} catch {
  Write-Host "  FAIL: $_" -ForegroundColor Red
  Write-Host "  (Older Arelis builds have no /health — try ping with token next.)"
}

Write-Host ""
Write-Host "== LAN IP health ($lan) ==" -ForegroundColor Cyan
try {
  $r = & curl.exe -s -S -m 3 "http://${lan}:$port/inbound/health"
  Write-Host "  OK: $r" -ForegroundColor Green
} catch {
  Write-Host "  FAIL: $_" -ForegroundColor Red
  Write-Host "  If localhost worked but this failed, something is binding only to loopback." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "== Firewall rules mentioning $port or Arelis ==" -ForegroundColor Cyan
Get-NetFirewallRule -ErrorAction SilentlyContinue |
  Where-Object { $_.DisplayName -match "8765|Arelis|python" } |
  Select-Object -First 20 DisplayName, Enabled, Direction, Action, Profile |
  Format-Table -AutoSize

Write-Host "== Network profile ==" -ForegroundColor Cyan
Get-NetConnectionProfile | Format-Table Name, InterfaceAlias, NetworkCategory -AutoSize

Write-Host @"

Next:
  1) Arelis must stay open. Thinking should show a listen URL.
  2) Companion URL: http://$lan`:$port
  3) If localhost health works but the phone fails, allow inbound TCP $port
     for the Private profile (Admin PowerShell):

       New-NetFirewallRule -DisplayName "Arelis inbound notify 8765" ``
         -Direction Inbound -Protocol TCP -LocalPort $port ``
         -Action Allow -Profile Private

  4) Ethernet PC + Wi-Fi phone on Google Nest: both must be on the main
     LAN (not Guest). Client isolation on guest Wi-Fi blocks the phone.
"@
