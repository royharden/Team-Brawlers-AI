# smoke_local_openemr.ps1
# Verifies the local Co-Pilot target Docker stack is reachable before the
# adversarial platform sends any traffic. Idempotent and read-only -- does NOT
# start containers, does NOT seed patients. Run from anywhere; uses absolute URLs.
#
# Usage:
#   pwsh -File scripts/smoke_local_openemr.ps1
#   pwsh -File scripts/smoke_local_openemr.ps1 -SkipHttpsCheck
#
# Exits 0 on all-green, 1 on any failure. Prints a colored status table.

[CmdletBinding()]
param(
    [string]$TargetBase = $env:TARGET_BASE_URL,
    [string]$SidecarBase = $env:COPILOT_SIDECAR_URL,
    [switch]$SkipHttpsCheck,
    [int]$TimeoutSec = 5
)

if (-not $TargetBase)  { $TargetBase  = "http://localhost:8300" }
if (-not $SidecarBase) { $SidecarBase = "http://localhost:8000" }

$results = @()

function Test-Endpoint {
    param(
        [string]$Name,
        [string]$Url,
        [int]$Timeout = 5,
        [bool]$AllowAnyStatus = $false
    )
    # Compatibility note: -SkipHttpErrorCheck and -SkipCertificateCheck are PowerShell 7+ only.
    # On Windows PowerShell 5.1 we approximate via [Net.ServicePointManager] + try/catch on 4xx.
    if ($PSVersionTable.PSVersion.Major -ge 7) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -TimeoutSec $Timeout -Method GET `
                      -UseBasicParsing -SkipHttpErrorCheck -SkipCertificateCheck -ErrorAction Stop
            $code = $resp.StatusCode
        } catch {
            return [pscustomobject]@{ Name=$Name; Url=$Url; Status="DOWN ($($_.Exception.Message))"; Ok=$false }
        }
    } else {
        # PS 5.1 fallback: skip SSL validation via callback; treat 4xx as OK if AllowAnyStatus
        [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
        try {
            $resp = Invoke-WebRequest -Uri $Url -TimeoutSec $Timeout -Method GET -UseBasicParsing -ErrorAction Stop
            $code = $resp.StatusCode
        } catch [System.Net.WebException] {
            $r = $_.Exception.Response
            if ($r -ne $null) {
                $code = [int]$r.StatusCode
            } else {
                return [pscustomobject]@{ Name=$Name; Url=$Url; Status="DOWN ($($_.Exception.Message))"; Ok=$false }
            }
        } catch {
            return [pscustomobject]@{ Name=$Name; Url=$Url; Status="DOWN ($($_.Exception.Message))"; Ok=$false }
        }
    }
    if ($AllowAnyStatus -or ($code -ge 200 -and $code -lt 500)) {
        return [pscustomobject]@{ Name=$Name; Url=$Url; Status="OK ($code)"; Ok=$true }
    } else {
        return [pscustomobject]@{ Name=$Name; Url=$Url; Status="HTTP $code"; Ok=$false }
    }
}

Write-Host "AgentForge -- local Co-Pilot target smoke check" -ForegroundColor Cyan
Write-Host "  TargetBase   = $TargetBase"
Write-Host "  SidecarBase  = $SidecarBase"
Write-Host ""

$results += Test-Endpoint -Name "OpenEMR HTTP login page"   -Url "$TargetBase/interface/login/login.php?site=default" -Timeout $TimeoutSec -AllowAnyStatus $true
if (-not $SkipHttpsCheck) {
    $results += Test-Endpoint -Name "OpenEMR HTTPS login page"  -Url "https://localhost:9300/interface/login/login.php?site=default" -Timeout $TimeoutSec -AllowAnyStatus $true
}
$results += Test-Endpoint -Name "Co-Pilot sidecar /healthz"    -Url "$SidecarBase/healthz"                            -Timeout $TimeoutSec
$results += Test-Endpoint -Name "phpMyAdmin"                   -Url "http://localhost:8310"                          -Timeout $TimeoutSec -AllowAnyStatus $true
$results += Test-Endpoint -Name "Mailpit web UI"               -Url "http://localhost:8025"                          -Timeout $TimeoutSec -AllowAnyStatus $true

$results | Format-Table Name, Status, Url -AutoSize

$failed = $results | Where-Object { -not $_.Ok }
if ($failed) {
    Write-Host ""
    Write-Host "[FAIL] $($failed.Count) endpoint(s) not reachable." -ForegroundColor Red
    Write-Host "If Docker stack is down, start with:" -ForegroundColor Yellow
    Write-Host '  cd <openemr-repo>; docker compose -f docker/development-easy/docker-compose.yml up -d'
    Write-Host "Then start the sidecar separately:"
    Write-Host '  cd openemr/agent/copilot-api; uvicorn app.main:app --host 0.0.0.0 --port 8000'
    exit 1
} else {
    Write-Host ""
    Write-Host "[OK] All endpoints reachable. Target ready for adversarial runs." -ForegroundColor Green
    exit 0
}
