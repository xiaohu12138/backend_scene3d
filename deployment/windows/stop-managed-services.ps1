$ErrorActionPreference='Stop'
$runner=Join-Path $PSScriptRoot 'service-runner.ps1'
$logRoot=Join-Path $PSScriptRoot '.local\launcher'
if (-not (Test-Path -LiteralPath $logRoot)) { Write-Host 'No managed services.'; exit 0 }
foreach ($file in Get-ChildItem -LiteralPath $logRoot -Filter '*.json' -File) {
    $entry=Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
    $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($entry.SupervisorPid)" -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    if (-not $process.CommandLine.Contains($runner) -or $process.CommandLine -notmatch "-Port\s+$($entry.Port)\b" -or $process.CreationDate.ToUniversalTime().ToString('o') -ne $entry.CreatedAt) {
        Write-Warning "Skipped reused or unrelated PID $($entry.SupervisorPid)"; continue
    }
    # Snapshot only this verified supervisor's descendant processes.
    $all=@(Get-CimInstance Win32_Process)
    $tree=New-Object 'System.Collections.Generic.List[object]'
    function Add-Descendants([int]$ParentId) {
        foreach ($child in @($all | Where-Object { $_.ParentProcessId -eq $ParentId })) {
            Add-Descendants $child.ProcessId
            $tree.Add($child)
        }
    }
    Add-Descendants $process.ProcessId
    Stop-Process -Id $process.ProcessId -ErrorAction SilentlyContinue
    foreach ($child in $tree) {
        $live=Get-CimInstance Win32_Process -Filter "ProcessId=$($child.ProcessId)" -ErrorAction SilentlyContinue
        if ($live -and $live.CreationDate -eq $child.CreationDate) { Stop-Process -Id $live.ProcessId -ErrorAction SilentlyContinue }
    }
    Write-Host "Stopped managed service: $($entry.Name) ($($entry.Port))"
}
Write-Host 'Pre-existing unmanaged services and the remote compute service were left running.'
