param(
    [Parameter(Mandatory=$true)][int]$Port,
    [Parameter(Mandatory=$true)][string]$Definition
)
$ErrorActionPreference = 'Stop'
$entry = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Definition)) | ConvertFrom-Json
$logRoot = Join-Path $PSScriptRoot '.local\launcher'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$log = Join-Path $logRoot "$Port.log"
$PSDefaultParameterValues['Out-File:Encoding']='utf8'
$PSDefaultParameterValues['Add-Content:Encoding']='utf8'
Set-Location -LiteralPath $entry.Directory
$env:PYTHONUNBUFFERED = '1'
while ($true) {
    Add-Content -LiteralPath $log -Value "`r`n[$(Get-Date -Format o)] Starting $($entry.Name)"
    try {
        $global:LASTEXITCODE = 0
        # This command comes only from the local launcher definitions.
        # Windows PowerShell wraps native stderr (including normal Uvicorn INFO
        # logs) as ErrorRecords. Keep them in the log without killing the server.
        $ErrorActionPreference='Continue'
        try { & ([scriptblock]::Create($entry.Command)) *>> $log }
        finally { $ErrorActionPreference='Stop' }
        Add-Content -LiteralPath $log -Value "[$(Get-Date -Format o)] Exited ($LASTEXITCODE); restarting in 5 seconds."
    } catch {
        Add-Content -LiteralPath $log -Value "[$(Get-Date -Format o)] $($_.Exception.Message); retrying in 5 seconds."
    }
    Start-Sleep -Seconds 5
}
