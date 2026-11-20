param([string]$HostName,[int]$Port=22,[string]$UserName)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
if(-not $HostName){$HostName=Read-Host 'SSH host'}
if(-not $UserName){$UserName=Read-Host 'SSH user'}
New-Item -ItemType Directory -Force -Path (Join-Path $root '.local') | Out-Null
Read-Host 'SSH password (stored for this Windows user using DPAPI)' -AsSecureString | Export-Clixml -LiteralPath (Join-Path $root '.local/ssh-password.xml')
Write-Host 'Encrypted credential saved. Set SCENE3D_SSH_HOST/PORT/USER in .env and verify the server host key in .local/known_hosts.'
