#Requires -Version 5.1
<#
.SYNOPSIS
  One controller for the full local AgentForge stack: start / stop / restart /
  check status of all three layers, or any subset. Run with no arguments for
  an interactive wizard (no switches to remember).

.DESCRIPTION
  The stack has three layers:
    target      OpenEMR Clinical Co-Pilot host  -- docker compose (EMR-SO)
    sidecar     Co-Pilot FastAPI sidecar        -- python -m uvicorn, port 8000
    agentforge  AgentForge platform (API + UI)  -- docker compose (this repo)

  Dependency order is target -> sidecar -> agentforge. `up` starts selected
  layers in that order; `down` stops them in reverse; `restart` does both.
  Every operation is idempotent -- a layer already in the desired state is
  left alone.

  CRITICAL: teardown never passes `-v` to docker compose down. The OpenEMR
  patient-database volumes and the AgentForge SQLite volume always survive.

.PARAMETER Action
  up | down | restart | status | wizard
  Omit entirely to launch the wizard.

.PARAMETER Layers
  One or more of: target, sidecar, agentforge, all  (default: all).
  e.g.  stack.ps1 up sidecar agentforge
        stack.ps1 down agentforge
        stack.ps1 status target

.PARAMETER Build
  For `up` / `restart`: rebuild the AgentForge Docker image first.

.PARAMETER EmrSoRoot
  Override the EMR-SO repo root. Default: ../../EMR-SO relative to this repo.

.PARAMETER Python
  Python interpreter that has the copilot-api deps. Default: system Python 3.11.

.PARAMETER TimeoutSec
  Health-check timeout for sidecar + agentforge layers. Default 180s.

.PARAMETER TargetTimeoutSec
  Health-check timeout for the OpenEMR target. Its development-easy image
  rsyncs the OneDrive-backed repo into the container on a cold boot --
  routinely 15-25 min. Default 1500s.

.NOTES
  ROUTINE WORKFLOW: the OpenEMR target is heavy and stable; leave it up for
  days. Cycle only the fast layers:
      stack.ps1 down sidecar agentforge
      stack.ps1 up sidecar agentforge
  A full cold start (target included) is the rare post-reboot case.

.EXAMPLE
  stack.ps1                              # interactive wizard
  stack.ps1 status                       # status of all three layers
  stack.ps1 up                           # start everything (cold start: slow)
  stack.ps1 up sidecar agentforge        # start just the fast layers
  stack.ps1 down                         # stop everything
  stack.ps1 down agentforge              # stop just AgentForge
  stack.ps1 restart sidecar              # bounce the sidecar
  stack.ps1 up agentforge -Build         # rebuild + start AgentForge
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Action,

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Layers,

    [switch]$Build,
    [string]$EmrSoRoot,
    [string]$Python = "C:\Program Files\Python311\python.exe",
    [int]$TimeoutSec = 180,
    [int]$TargetTimeoutSec = 1500
)

# --- path anchoring -------------------------------------------------------
$RepoRoot          = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StackDir          = Join-Path $RepoRoot ".stack"
$AgentForgeCompose = Join-Path $RepoRoot "docker-compose.local.yml"
$SidecarPidFile    = Join-Path $StackDir "sidecar.pid"
$SidecarLog        = Join-Path $StackDir "sidecar.log"
$SidecarOutLog     = Join-Path $StackDir "sidecar.stdout.log"

if (-not $EmrSoRoot) { $EmrSoRoot = Join-Path $RepoRoot "..\..\EMR-SO" }
$TargetComposeDir      = Join-Path $EmrSoRoot "openemr\docker\development-easy"
$TargetComposeBase     = Join-Path $TargetComposeDir "docker-compose.yml"
$TargetComposeOverride = Join-Path $TargetComposeDir "docker-compose.override.yml"
$SidecarDir            = Join-Path $EmrSoRoot "openemr\agent\copilot-api"

$TargetContainer = "development-easy-openemr-1"

if (-not (Test-Path $StackDir)) { New-Item -ItemType Directory -Path $StackDir | Out-Null }

function Get-TargetComposeArgs {
    # The target needs BOTH compose files. docker-compose.override.yml injects
    # the COPILOT_* env vars (sidecar URL, gateway shared secret, demo-mode
    # flags) into the openemr container -- without them the PHP gateway can't
    # reach the sidecar. Passing -f explicitly suppresses Compose's automatic
    # override merge, so the override MUST be named explicitly too.
    $cargs = @("-f", $TargetComposeBase)
    if (Test-Path $TargetComposeOverride) {
        $cargs += @("-f", $TargetComposeOverride)
    } else {
        Write-Host "  WARNING: override not found ($TargetComposeOverride) --" -ForegroundColor Yellow
        Write-Host "           openemr will start WITHOUT the COPILOT_* env vars." -ForegroundColor Yellow
    }
    return $cargs
}

# --- generic helpers ------------------------------------------------------
function Test-Http {
    param([string]$Url, [int]$Timeout = 4)
    try {
        Invoke-WebRequest -Uri $Url -TimeoutSec $Timeout -UseBasicParsing -ErrorAction Stop | Out-Null
        return $true
    } catch [System.Net.WebException] {
        if ($_.Exception.Response -ne $null) { return $true }   # 4xx still = listening
        return $false
    } catch {
        return $false
    }
}

function Wait-Http {
    param([string]$Name, [string]$Url, [int]$Timeout)
    Write-Host ("  waiting for {0} ({1}) ..." -f $Name, $Url) -NoNewline
    $deadline = (Get-Date).AddSeconds($Timeout)
    while ((Get-Date) -lt $deadline) {
        if (Test-Http -Url $Url) { Write-Host " OK" -ForegroundColor Green; return $true }
        Start-Sleep -Seconds 2; Write-Host "." -NoNewline
    }
    Write-Host " TIMEOUT" -ForegroundColor Red
    return $false
}

function Get-ContainerHealth {
    # Returns: healthy | unhealthy | starting | nohealthcheck | running | absent
    param([string]$Container)
    $state = (docker inspect --format '{{.State.Status}}' $Container 2>$null)
    if (-not $state) { return "absent" }
    if ($state -ne "running") { return "absent" }
    $health = (docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}nohealthcheck{{end}}' $Container 2>$null)
    if (-not $health) { return "running" }
    return $health
}

function Wait-ContainerHealthy {
    param([string]$Name, [string]$Container, [int]$Timeout)
    Write-Host ("  waiting for {0} healthcheck ({1}) ..." -f $Name, $Container) -NoNewline
    $deadline = (Get-Date).AddSeconds($Timeout)
    while ((Get-Date) -lt $deadline) {
        $h = Get-ContainerHealth -Container $Container
        if ($h -eq "healthy") { Write-Host " OK" -ForegroundColor Green; return $true }
        if ($h -eq "nohealthcheck" -or $h -eq "running") {
            Write-Host " (no healthcheck -- assuming up)" -ForegroundColor DarkGray
            return $true
        }
        Start-Sleep -Seconds 5; Write-Host "." -NoNewline
    }
    Write-Host " TIMEOUT" -ForegroundColor Red
    return $false
}

# --- status ---------------------------------------------------------------
function Get-LayerStatus {
    # Returns a pscustomobject: Layer, State (UP/DOWN/PARTIAL/STARTING), Detail
    param([string]$Layer)
    switch ($Layer) {
        "target" {
            $h = Get-ContainerHealth -Container $TargetContainer
            switch ($h) {
                "healthy"       { return [pscustomobject]@{ Layer="target"; State="UP";       Detail="container healthy, http://localhost:8300" } }
                "starting"      { return [pscustomobject]@{ Layer="target"; State="STARTING"; Detail="cold boot in progress (rsync) -- can take 15-25 min" } }
                "unhealthy"     { return [pscustomobject]@{ Layer="target"; State="STARTING"; Detail="container up but healthcheck failing (still booting)" } }
                "running"       { return [pscustomobject]@{ Layer="target"; State="UP";       Detail="container running (no healthcheck)" } }
                "nohealthcheck" { return [pscustomobject]@{ Layer="target"; State="UP";       Detail="container running (no healthcheck)" } }
                default         { return [pscustomobject]@{ Layer="target"; State="DOWN";     Detail="container not running" } }
            }
        }
        "sidecar" {
            if (Test-Http -Url "http://localhost:8000/healthz" -Timeout 3) {
                return [pscustomobject]@{ Layer="sidecar"; State="UP"; Detail="http://localhost:8000/healthz responding" }
            }
            $pidNote = ""
            if (Test-Path $SidecarPidFile) {
                $p = (Get-Content $SidecarPidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
                $pidNote = " (stale pidfile $p)"
            }
            return [pscustomobject]@{ Layer="sidecar"; State="DOWN"; Detail="not responding on :8000$pidNote" }
        }
        "agentforge" {
            # Container-authoritative: a port squatter (e.g. a stale non-Docker
            # uvicorn on 127.0.0.1:8100) must NOT read as "up". The HTTP probe
            # only counts when the matching container is actually running.
            $apiState = (docker inspect --format '{{.State.Status}}' agentforge-api 2>$null)
            $uiState  = (docker inspect --format '{{.State.Status}}' agentforge-ui  2>$null)
            $apiRunning = ($apiState -eq "running")
            $uiRunning  = ($uiState -eq "running")
            if (-not $apiRunning -and -not $uiRunning) {
                return [pscustomobject]@{ Layer="agentforge"; State="DOWN"; Detail="API + UI containers not running" }
            }
            $apiUp = $apiRunning -and (Test-Http -Url "http://localhost:8100/healthz" -Timeout 3)
            $uiUp  = $uiRunning  -and (Test-Http -Url "http://localhost:8501" -Timeout 3)
            if ($apiUp -and $uiUp) {
                return [pscustomobject]@{ Layer="agentforge"; State="UP"; Detail="API :8100 + UI :8501 responding" }
            }
            $bits = @()
            if ($apiRunning) { if ($apiUp) { $bits += "API up" } else { $bits += "API container running, not ready" } } else { $bits += "API down" }
            if ($uiRunning)  { if ($uiUp)  { $bits += "UI up" }  else { $bits += "UI container running, not ready" } }  else { $bits += "UI down" }
            return [pscustomobject]@{ Layer="agentforge"; State="PARTIAL"; Detail=($bits -join ", ") }
        }
        default { return [pscustomobject]@{ Layer=$Layer; State="?"; Detail="unknown layer" } }
    }
}

function Show-Status {
    param([string[]]$Wanted)
    Write-Host ""
    Write-Host "  Layer        State      Detail" -ForegroundColor Cyan
    Write-Host "  -----------  ---------  ---------------------------------------------"
    foreach ($l in $Wanted) {
        $s = Get-LayerStatus -Layer $l
        $color = switch ($s.State) {
            "UP"       { "Green" }
            "DOWN"     { "DarkGray" }
            "STARTING" { "Yellow" }
            "PARTIAL"  { "Yellow" }
            default    { "White" }
        }
        $line = "  {0,-11}  {1,-9}  {2}" -f $s.Layer, $s.State, $s.Detail
        Write-Host $line -ForegroundColor $color
    }
    Write-Host ""
}

# --- per-layer start ------------------------------------------------------
function Start-Target {
    Write-Host "[target] OpenEMR" -ForegroundColor Cyan
    if (-not (Test-Path $TargetComposeBase)) {
        Write-Host "  ERROR: target compose not found: $TargetComposeBase" -ForegroundColor Red
        return $false
    }
    # Always run `docker compose up -d` with both files. It is idempotent: a
    # near-instant no-op when the container already matches the desired config,
    # a recreate when config drifted (e.g. the override was missing before).
    # This is more correct than a health-based skip -- a container that's
    # "healthy" but missing the COPILOT_* env still needs recreating.
    $composeArgs = Get-TargetComposeArgs
    docker compose @composeArgs up -d
    if ($LASTEXITCODE -ne 0) { Write-Host "  ERROR: docker compose up exited $LASTEXITCODE" -ForegroundColor Red; return $false }
    # If the container is still healthy a beat after `up -d`, it was a no-op.
    # Otherwise a recreate kicked off a cold boot -- warn about the duration.
    # Wait-ContainerHealthy returns instantly when already healthy, so the long
    # timeout costs nothing in the no-op case.
    Start-Sleep -Seconds 2
    if ((Get-ContainerHealth -Container $TargetContainer) -ne "healthy") {
        Write-Host "  NOTE: recreate triggered a cold boot -- rsync of the OneDrive-backed" -ForegroundColor Yellow
        Write-Host "        repo into the container routinely takes 15-25 min. Be patient." -ForegroundColor Yellow
    }
    return (Wait-ContainerHealthy -Name "OpenEMR" -Container $TargetContainer -Timeout $TargetTimeoutSec)
}

function Start-Sidecar {
    Write-Host "[sidecar] Co-Pilot" -ForegroundColor Cyan
    if (Test-Http -Url "http://localhost:8000/healthz") {
        Write-Host "  already up -- leaving it alone" -ForegroundColor DarkGray
        return $true
    }
    if (-not (Test-Path $SidecarDir)) { Write-Host "  ERROR: sidecar dir not found: $SidecarDir" -ForegroundColor Red; return $false }
    if (-not (Test-Path $Python))     { Write-Host "  ERROR: python not found: $Python (pass -Python)" -ForegroundColor Red; return $false }
    Write-Host "  launching: $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
    $proc = Start-Process -FilePath $Python `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $SidecarDir `
        -RedirectStandardError $SidecarLog `
        -RedirectStandardOutput $SidecarOutLog `
        -WindowStyle Hidden -PassThru
    $proc.Id | Out-File -FilePath $SidecarPidFile -Encoding ascii
    Write-Host ("  sidecar PID {0} -> {1}" -f $proc.Id, $SidecarPidFile)
    $ok = Wait-Http -Name "sidecar /healthz" -Url "http://localhost:8000/healthz" -Timeout $TimeoutSec
    if (-not $ok) {
        Write-Host "  last 20 lines of ${SidecarLog}:" -ForegroundColor Yellow
        if (Test-Path $SidecarLog) { Get-Content $SidecarLog -Tail 20 }
    }
    return $ok
}

function Start-AgentForge {
    Write-Host "[agentforge] platform" -ForegroundColor Cyan
    if (-not (Test-Path $AgentForgeCompose)) {
        Write-Host "  ERROR: compose not found: $AgentForgeCompose" -ForegroundColor Red
        return $false
    }
    if ($Build) {
        Write-Host "  building image (-Build) ..."
        docker compose -f $AgentForgeCompose build
        if ($LASTEXITCODE -ne 0) { Write-Host "  ERROR: build exited $LASTEXITCODE" -ForegroundColor Red; return $false }
    }
    docker compose -f $AgentForgeCompose up -d
    if ($LASTEXITCODE -ne 0) { Write-Host "  ERROR: docker compose up exited $LASTEXITCODE" -ForegroundColor Red; return $false }
    $ok = Wait-Http -Name "AgentForge API /healthz" -Url "http://localhost:8100/healthz" -Timeout $TimeoutSec
    Wait-Http -Name "AgentForge UI" -Url "http://localhost:8501" -Timeout 60 | Out-Null
    return $ok
}

# --- per-layer stop -------------------------------------------------------
function Stop-Target {
    Write-Host "[target] OpenEMR" -ForegroundColor Cyan
    if (-not (Test-Path $TargetComposeBase)) {
        Write-Host "  compose not found -- skipping" -ForegroundColor Yellow
        return $true
    }
    # Pass both files on `down` too so Compose resolves the same project/config
    # it was brought up with. NO -v -- patient DB + site volumes survive.
    $composeArgs = Get-TargetComposeArgs
    docker compose @composeArgs down
    if ($LASTEXITCODE -eq 0) { Write-Host "  stopped" -ForegroundColor Green; return $true }
    Write-Host "  docker compose down exited $LASTEXITCODE" -ForegroundColor Yellow
    return $false
}

function Stop-Sidecar {
    Write-Host "[sidecar] Co-Pilot" -ForegroundColor Cyan
    $stopped = $false
    if (Test-Path $SidecarPidFile) {
        $pidText = (Get-Content $SidecarPidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        $sidecarPid = 0
        if ([int]::TryParse(($pidText -as [string]).Trim(), [ref]$sidecarPid) -and $sidecarPid -gt 0) {
            if (Get-Process -Id $sidecarPid -ErrorAction SilentlyContinue) {
                Stop-Process -Id $sidecarPid -Force -ErrorAction SilentlyContinue
                Write-Host "  stopped sidecar PID $sidecarPid (from pidfile)" -ForegroundColor Green
            } else {
                Write-Host "  pidfile PID $sidecarPid not running (already gone)" -ForegroundColor DarkGray
            }
            $stopped = $true
        }
        Remove-Item $SidecarPidFile -ErrorAction SilentlyContinue
    }
    if (-not $stopped) {
        $conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) {
            $owner = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            if ($owner) {
                Write-Host ("  no pidfile; :8000 owned by PID {0} ({1}) -- stopping it" -f $owner.Id, $owner.ProcessName) -ForegroundColor Yellow
                Stop-Process -Id $owner.Id -Force -ErrorAction SilentlyContinue
                Write-Host "  stopped" -ForegroundColor Green
            }
        } else {
            Write-Host "  nothing listening on :8000 -- already down" -ForegroundColor DarkGray
        }
    }
    return $true
}

function Stop-AgentForge {
    Write-Host "[agentforge] platform" -ForegroundColor Cyan
    if (-not (Test-Path $AgentForgeCompose)) {
        Write-Host "  compose not found -- skipping" -ForegroundColor Yellow
        return $true
    }
    docker compose -f $AgentForgeCompose down   # NO -v -- agentforge-data volume survives
    if ($LASTEXITCODE -eq 0) { Write-Host "  stopped" -ForegroundColor Green; return $true }
    Write-Host "  docker compose down exited $LASTEXITCODE" -ForegroundColor Yellow
    return $false
}

# --- orchestration --------------------------------------------------------
$CanonicalOrder = @("target", "sidecar", "agentforge")

function Resolve-Layers {
    param([string[]]$Raw)
    if (-not $Raw -or $Raw.Count -eq 0) { return $CanonicalOrder }
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($r in $Raw) {
        switch ($r.ToLower()) {
            "all"        { return $CanonicalOrder }
            "target"     { if (-not $out.Contains("target"))     { $out.Add("target") } }
            "openemr"    { if (-not $out.Contains("target"))     { $out.Add("target") } }
            "sidecar"    { if (-not $out.Contains("sidecar"))    { $out.Add("sidecar") } }
            "copilot"    { if (-not $out.Contains("sidecar"))    { $out.Add("sidecar") } }
            "agentforge" { if (-not $out.Contains("agentforge")) { $out.Add("agentforge") } }
            "af"         { if (-not $out.Contains("agentforge")) { $out.Add("agentforge") } }
            "platform"   { if (-not $out.Contains("agentforge")) { $out.Add("agentforge") } }
            default      { Write-Host "  WARNING: unknown layer '$r' ignored" -ForegroundColor Yellow }
        }
    }
    if ($out.Count -eq 0) { return $CanonicalOrder }
    # Keep canonical order regardless of how the user listed them.
    return ($CanonicalOrder | Where-Object { $out.Contains($_) })
}

function Invoke-Up {
    param([string[]]$Sel)
    foreach ($l in $Sel) {       # canonical order: target -> sidecar -> agentforge
        $ok = switch ($l) {
            "target"     { Start-Target }
            "sidecar"    { Start-Sidecar }
            "agentforge" { Start-AgentForge }
        }
        if (-not $ok) {
            Write-Host ""
            Write-Host "[FAIL] layer '$l' did not come up -- stopping here." -ForegroundColor Red
            return $false
        }
    }
    return $true
}

function Invoke-Down {
    param([string[]]$Sel)
    $reverse = [array]($Sel)[($Sel.Count - 1)..0]
    foreach ($l in $reverse) {   # reverse order: agentforge -> sidecar -> target
        switch ($l) {
            "target"     { Stop-Target     | Out-Null }
            "sidecar"    { Stop-Sidecar    | Out-Null }
            "agentforge" { Stop-AgentForge | Out-Null }
        }
    }
    return $true
}

function Invoke-StackAction {
    param([string]$Act, [string[]]$Sel)
    switch ($Act) {
        "up" {
            Write-Host ("AgentForge stack -- UP  [{0}]" -f ($Sel -join ", ")) -ForegroundColor Cyan
            Write-Host ""
            $ok = Invoke-Up -Sel $Sel
            if ($ok) { Write-Host ""; Write-Host "[OK] requested layers are up." -ForegroundColor Green }
            Show-Status -Wanted $CanonicalOrder
            return $ok
        }
        "down" {
            Write-Host ("AgentForge stack -- DOWN  [{0}]" -f ($Sel -join ", ")) -ForegroundColor Cyan
            Write-Host ""
            Invoke-Down -Sel $Sel | Out-Null
            Write-Host ""
            Write-Host "[OK] requested layers are down. Docker volumes preserved (no -v)." -ForegroundColor Green
            Show-Status -Wanted $CanonicalOrder
            return $true
        }
        "restart" {
            Write-Host ("AgentForge stack -- RESTART  [{0}]" -f ($Sel -join ", ")) -ForegroundColor Cyan
            Write-Host ""
            Invoke-Down -Sel $Sel | Out-Null
            Write-Host ""
            $ok = Invoke-Up -Sel $Sel
            if ($ok) { Write-Host ""; Write-Host "[OK] requested layers restarted." -ForegroundColor Green }
            Show-Status -Wanted $CanonicalOrder
            return $ok
        }
        "status" {
            Write-Host "AgentForge stack -- STATUS" -ForegroundColor Cyan
            Show-Status -Wanted $Sel
            return $true
        }
        default {
            Write-Host "Unknown action: $Act" -ForegroundColor Red
            Write-Host "Valid actions: up | down | restart | status   (or run with no args for the wizard)"
            return $false
        }
    }
}

# --- wizard ---------------------------------------------------------------
function Read-LayerSelection {
    Write-Host ""
    Write-Host "  Which layer(s)? Enter numbers comma-separated (e.g. 2,3), or A for all:"
    Write-Host "    1) target      (OpenEMR  -- SLOW to cold-start, 15-25 min)"
    Write-Host "    2) sidecar     (Co-Pilot -- seconds)"
    Write-Host "    3) agentforge  (platform -- seconds)"
    $raw = Read-Host "  >"
    if ($raw -match '^\s*[Aa]\s*$') { return $CanonicalOrder }
    $picked = New-Object System.Collections.Generic.List[string]
    foreach ($tok in $raw.Split(',')) {
        switch ($tok.Trim()) {
            "1" { if (-not $picked.Contains("target"))     { $picked.Add("target") } }
            "2" { if (-not $picked.Contains("sidecar"))    { $picked.Add("sidecar") } }
            "3" { if (-not $picked.Contains("agentforge")) { $picked.Add("agentforge") } }
            ""  { }
            default { Write-Host "  (ignored: '$tok')" -ForegroundColor DarkGray }
        }
    }
    if ($picked.Count -eq 0) {
        Write-Host "  nothing selected." -ForegroundColor Yellow
        return @()
    }
    return ($CanonicalOrder | Where-Object { $picked.Contains($_) })
}

function Show-Wizard {
    while ($true) {
        Clear-Host
        Write-Host "==============================================" -ForegroundColor Cyan
        Write-Host "  AgentForge Stack Control" -ForegroundColor Cyan
        Write-Host "==============================================" -ForegroundColor Cyan
        Show-Status -Wanted $CanonicalOrder
        Write-Host "  What would you like to do?"
        Write-Host "    1) Start   all layers"
        Write-Host "    2) Stop    all layers"
        Write-Host "    3) Restart all layers"
        Write-Host "    4) Start   specific layer(s)"
        Write-Host "    5) Stop    specific layer(s)"
        Write-Host "    6) Restart specific layer(s)"
        Write-Host "    7) Refresh status"
        Write-Host "    Q) Quit"
        Write-Host ""
        $choice = Read-Host "  Choice"
        $sel = $null
        $act = $null
        switch ($choice.Trim().ToUpper()) {
            "1" { $act = "up";      $sel = $CanonicalOrder }
            "2" { $act = "down";    $sel = $CanonicalOrder }
            "3" { $act = "restart"; $sel = $CanonicalOrder }
            "4" { $act = "up";      $sel = Read-LayerSelection }
            "5" { $act = "down";    $sel = Read-LayerSelection }
            "6" { $act = "restart"; $sel = Read-LayerSelection }
            "7" { continue }   # loop -> re-renders status
            "Q" { Write-Host ""; Write-Host "  bye." -ForegroundColor DarkGray; return }
            default { Write-Host "  (unrecognized choice)" -ForegroundColor Yellow; Start-Sleep -Seconds 1; continue }
        }
        if ($sel -and $sel.Count -gt 0) {
            Write-Host ""
            Invoke-StackAction -Act $act -Sel $sel | Out-Null
        }
        Write-Host ""
        Read-Host "  press Enter to return to the menu" | Out-Null
    }
}

# --- entry point ----------------------------------------------------------
if (-not $Action -or $Action.ToLower() -eq "wizard") {
    Show-Wizard
    exit 0
}

$selected = Resolve-Layers -Raw $Layers
$result = Invoke-StackAction -Act $Action.ToLower() -Sel $selected
if ($result) { exit 0 } else { exit 1 }
