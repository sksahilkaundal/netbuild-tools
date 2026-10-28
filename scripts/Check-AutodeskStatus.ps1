<#
.SYNOPSIS
    Checks Autodesk's public health dashboard for Revit-related service issues.

.DESCRIPTION
    Queries the Statuspage.io API behind https://health.autodesk.com and reports
    the status of Revit / BIM / APS-related components, plus any active incidents.
    No login or API key needed — this is Autodesk's own public status feed.

.PARAMETER All
    Show every monitored component, not just Revit-related ones.

.EXAMPLE
    .\Check-AutodeskStatus.ps1
    .\Check-AutodeskStatus.ps1 -All
#>

param(
    [switch]$All
)

$summaryUrl  = "https://health.autodesk.com/api/v2/summary.json"
$incidentUrl = "https://health.autodesk.com/api/v2/incidents/unresolved.json"

$statusColor = @{
    "operational"           = "Green"
    "degraded_performance"  = "Yellow"
    "partial_outage"        = "DarkYellow"
    "major_outage"          = "Red"
    "under_maintenance"     = "Cyan"
}

try {
    $summary = Invoke-RestMethod -Uri $summaryUrl -TimeoutSec 15
} catch {
    Write-Host "Could not reach Autodesk status feed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "`nAutodesk Health Dashboard — checked $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host "Source: https://health.autodesk.com" -ForegroundColor DarkGray
Write-Host ("=" * 60)

$keywordPattern = "revit|bim|forge|aps -|construction cloud|docs|informed design"

$components = $summary.components
if (-not $All) {
    $components = $components | Where-Object { $_.name -match $keywordPattern }
}

$problems = $components | Where-Object { $_.status -ne "operational" }

foreach ($c in $components | Sort-Object name) {
    $color = $statusColor[$c.status]
    if (-not $color) { $color = "White" }
    Write-Host ("{0,-55} {1}" -f $c.name, $c.status) -ForegroundColor $color
}

Write-Host ("=" * 60)

if ($problems.Count -eq 0) {
    Write-Host "`nAll checked components are operational." -ForegroundColor Green
} else {
    Write-Host "`n$($problems.Count) component(s) with issues:" -ForegroundColor Yellow
    $problems | ForEach-Object { Write-Host " - $($_.name): $($_.status)" -ForegroundColor Yellow }
}

try {
    $incidents = Invoke-RestMethod -Uri $incidentUrl -TimeoutSec 15
    if ($incidents.incidents.Count -gt 0) {
        Write-Host "`nActive incidents:" -ForegroundColor Red
        foreach ($i in $incidents.incidents) {
            Write-Host "`n[$($i.impact)] $($i.name)" -ForegroundColor Red
            Write-Host "  Status: $($i.status)  |  Started: $($i.created_at)"
            $latestUpdate = $i.incident_updates | Select-Object -First 1
            if ($latestUpdate) {
                Write-Host "  Latest update: $($latestUpdate.body)"
            }
        }
    } else {
        Write-Host "`nNo active incidents reported." -ForegroundColor Green
    }
} catch {
    Write-Host "`nCould not fetch incident list: $($_.Exception.Message)" -ForegroundColor DarkYellow
}

Write-Host ""
