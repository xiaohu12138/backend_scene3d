param([switch]$CheckOnly, [switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonExe = 'D:\Anaconda\envs\weather-agent\python.exe'
$logRoot = Join-Path $projectRoot '.local\launcher'
$runner = Join-Path $projectRoot 'service-runner.ps1'

function Quote-PowerShell([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}

function Test-LocalPort([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        return ($task.Wait(400) -and $client.Connected)
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Test-ServiceReady($Service) {
    if ($Service.Protocol -eq 'tcp') { return (Test-LocalPort $Service.Port) }
    try {
        $request = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:$($Service.Port)$($Service.Health)")
        # AgentScope's aggregate health probe may spend 3 seconds checking external services.
        $request.Timeout = $(if ($Service.Port -eq 8012) { 7000 } else { 2000 })
        $request.ReadWriteTimeout = $request.Timeout
        $response = $request.GetResponse()
        try {
            if ([int]$response.StatusCode -ne 200) { return $false }
            if ($Service.Port -in @(8002, 8003, 8004, 8005, 8012, 8013, 18013)) {
                $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
                try { $body = $reader.ReadToEnd() | ConvertFrom-Json }
                finally { $reader.Dispose() }
                switch ($Service.Port) {
                    8002 { return ($body.data.status -eq 'online' -and $body.data.adapter_worker.status -eq 'running') }
                    8003 { return ($body.data.status -eq 'online' -and $body.data.database -eq 'online') }
                    8004 { return ($body.data.service -eq 'backend_agent') }
                    8005 { return ($body.data.service -eq 'backend_auth') }
                    8012 { return ($null -ne $body.agentscope -and $null -ne $body.checks) }
                    8013 { return ($body.service -eq 'backend_scene3d_gateway' -and $body.remote_ready -eq $true) }
                    18013 { return ($body.service -eq 'backend_scene3d' -and $body.data_ready -eq $true) }
                }
            }
            return $true
        }
        finally { $response.Close() }
    } catch { return $false }
}

function Start-ManagedService([string]$Title, [int]$Port, [string]$Directory, [string]$Command) {
    New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
    $metadata = Join-Path $logRoot "$Port.json"
    if (Test-Path -LiteralPath $metadata) {
        $old = Get-Content -LiteralPath $metadata -Raw | ConvertFrom-Json
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($old.SupervisorPid)" -ErrorAction SilentlyContinue
        if ($process -and $process.CommandLine.Contains($runner) -and $process.CommandLine -match "-Port\s+$Port\b" -and $process.CreationDate.ToUniversalTime().ToString('o') -eq $old.CreatedAt) {
            Write-Host "[MANAGED] $Title is already supervised; waiting for readiness."
            return
        }
    }
    $definition = @{Name=$Title; Directory=$Directory; Command=$Command} | ConvertTo-Json -Compress
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($definition))
    $process = Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $runner + '"'), '-Port', $Port, '-Definition', $encoded
    ) -WorkingDirectory $Directory -WindowStyle Hidden -PassThru
    $identity = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
    @{SupervisorPid=$process.Id; CreatedAt=$identity.CreationDate.ToUniversalTime().ToString('o'); Port=$Port; Name=$Title; Directory=$Directory} |
        ConvertTo-Json | Set-Content -LiteralPath $metadata -Encoding UTF8
}

$agentRoot = Join-Path $projectRoot 'weather_agentscope'
$agentFrontend = Join-Path $agentRoot 'examples\web_ui\frontend'
$mainFrontend = Join-Path $projectRoot 'webpage_sys'
$npmExe = (Get-Command npm.cmd -ErrorAction Stop).Source
$services = @(
    @{
        Name = 'Weather Login API'; Port = 8005; Health = '/api/health'; Directory = (Join-Path $projectRoot 'backend_auth')
        Required = @($pythonExe, (Join-Path $projectRoot 'backend_auth\main.py'), (Join-Path $projectRoot 'backend_auth\.env'))
        Command = '& ' + (Quote-PowerShell $pythonExe) + ' -m uvicorn main:app --host 127.0.0.1 --port 8005'
    },
    @{
        Name = 'Upload and Catalog API'; Port = 8003; Health = '/api/health'; Directory = (Join-Path $projectRoot 'backend_upload')
        # backend_upload imports the shared data backend as 'backend'. The local junction points to backend_system.
        Required = @($pythonExe, (Join-Path $projectRoot 'backend_upload\main.py'), (Join-Path $projectRoot 'backend_upload\.env'), (Join-Path $projectRoot 'backend\services\asset_catalog.py'))
        Command = '& ' + (Quote-PowerShell $pythonExe) + ' -m uvicorn main:app --host 127.0.0.1 --port 8003'
    },
    @{
        Name = 'Weather Data API and Adapter Worker'; Port = 8002; Health = '/api/health'; Directory = (Join-Path $projectRoot 'backend_system')
        Required = @($pythonExe, (Join-Path $projectRoot 'backend_system\main.py'), (Join-Path $projectRoot 'backend_system\.env'))
        Command = '& ' + (Quote-PowerShell $pythonExe) + ' -m uvicorn main:app --host 127.0.0.1 --port 8002'
    },
    @{
        Name = 'Legacy Weather Agent API'; Port = 8004; Health = '/api/health'; Directory = (Join-Path $projectRoot 'backend_agent')
        Required = @($pythonExe, (Join-Path $projectRoot 'backend_agent\main.py'), (Join-Path $projectRoot 'backend_agent\.env'))
        Command = '& ' + (Quote-PowerShell $pythonExe) + ' -m uvicorn main:app --host 127.0.0.1 --port 8004'
    },
    @{
        Name = 'Scene3D SSH transport and remote compute'; Port = 18013; Health = '/api/health'; Directory = (Join-Path $projectRoot 'backend_scene3d')
        Required = @($pythonExe, (Join-Path $projectRoot 'backend_scene3d\backend_scene3d\tunnel.py'), (Join-Path $projectRoot 'backend_scene3d\.env'), (Join-Path $projectRoot 'backend_scene3d\.local\known_hosts'), (Join-Path $projectRoot 'backend_scene3d\.local\ssh-password.xml'))
        Command = '& ' + (Quote-PowerShell $pythonExe) + ' -m backend_scene3d.tunnel'
    },
    @{
        Name = 'Scene3D authenticated gateway'; Port = 8013; Health = '/api/health'; Directory = (Join-Path $projectRoot 'backend_scene3d')
        Required = @($pythonExe, (Join-Path $projectRoot 'backend_scene3d\backend_scene3d\gateway.py'))
        Command = '& ' + (Quote-PowerShell $pythonExe) + ' -m uvicorn backend_scene3d.gateway:create_app --factory --host 127.0.0.1 --port 8013'
    },
    @{
        Name = 'AgentScope API'; Port = 8012; Health = '/api/weather-agent/health'; Directory = $agentRoot
        Required = @($pythonExe, (Join-Path $agentRoot 'examples\icing_agent_service\main.py'))
        Command = '& ' + (Quote-PowerShell $pythonExe) + " 'examples\icing_agent_service\main.py'"
    },
    @{
        Name = 'AgentScope Web'; Port = 5173; Health = '/'; Directory = $agentFrontend
        Required = @((Join-Path $agentFrontend 'node_modules\vite\bin\vite.js'))
        Command = '& ' + (Quote-PowerShell $npmExe) + ' run dev -- --host 127.0.0.1 --port 5173 --strictPort'
    },
    @{
        Name = 'Weather Main Web'; Port = 5177; Health = '/'; Directory = $mainFrontend
        Required = @((Join-Path $mainFrontend 'node_modules\vite\bin\vite.js'))
        Command = '& ' + (Quote-PowerShell $npmExe) + ' run dev -- --port 5177 --strictPort'
    }
)

$mutexDigest = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot))).Replace('-', '').Substring(0,16)
$launcherMutex = New-Object Threading.Mutex($false, "Local\WeatherAgentLauncher-$mutexDigest")
$ownsMutex = $false
try {
try { $ownsMutex = $launcherMutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
if (-not $ownsMutex) { Write-Host 'Another launch is in progress. Please wait for its health checks.'; return }
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { throw "Service runner missing: $runner" }
# Complete file checks before starting any new process. Never install dependencies here.
foreach ($service in $services) {
    foreach ($path in $service.Required) {
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Required file not found: $path"
        }
    }
}

if (Test-LocalPort 6379) {
    Write-Host '[READY] Existing local Redis: 127.0.0.1:6379' -ForegroundColor Green
} else {
    # Reuse the existing native executable discovered on this computer.
    $memuraiCandidates = @(
        (Join-Path $projectRoot '.local\memurai\Memurai\memurai.exe'),
        'C:\Users\12877\Desktop\weather agent\weather_agentscope\weather_agentscope\.local\memurai\Memurai\memurai.exe',
        'C:\Program Files\Memurai\memurai.exe'
    )
    $memurai = $memuraiCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($CheckOnly) {
        Write-Host "[CHECK] Redis is stopped. Existing native executable: $memurai"
    } elseif ($memurai) {
        # Use the existing data directory instead of creating a second Redis database.
        $existingDataRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $memurai))
        $dataRoot = Join-Path $existingDataRoot 'redis-data'
        if (-not (Test-Path -LiteralPath $dataRoot -PathType Container)) {
            throw 'Redis is stopped. Start your existing Memurai instance before running this launcher; its data directory could not be identified safely.'
        }
        $command = '& ' + (Quote-PowerShell $memurai) +
            ' --bind 127.0.0.1 --port 6379 --appendonly yes --dir ' + (Quote-PowerShell $dataRoot)
        Start-ManagedService 'Local Redis (6379)' 6379 $dataRoot $command
        for ($i = 0; $i -lt 20 -and -not (Test-LocalPort 6379); $i++) { Start-Sleep -Milliseconds 500 }
        if (-not (Test-LocalPort 6379)) { throw 'Redis did not start. Check the Redis console.' }
    } else {
        throw 'Redis is stopped and its existing executable was not found. Start your local Redis, then retry.'
    }
}

foreach ($service in $services) {
    if (Test-LocalPort $service.Port) {
        if (Test-ServiceReady $service) { Write-Host "[READY] $($service.Name): existing service passed health check." }
        else { Write-Host "[NOT READY] $($service.Name): occupied port has not passed health check. No unrelated process will be stopped." -ForegroundColor Yellow }
    } elseif ($CheckOnly) {
        Write-Host "[CHECK] Would start $($service.Name) on port $($service.Port)."
    } else {
        Write-Host "[START] $($service.Name) ($($service.Port))"
        Start-ManagedService $service.Name $service.Port $service.Directory $service.Command
    }
}

$externalMissing = @()
foreach ($external in @(
    @{Name='Model API'; Port=8006; Repo='backend_model'},
    @{Name='WRF API'; Port=8007; Repo='backend_wrf'},
    @{Name='ERA5 History API'; Port=8010; Repo='ERA5 history server'}
)) {
    if (-not (Test-LocalPort $external.Port)) {
        $externalMissing += "$($external.Name) ($($external.Port))"
        Write-Host "[UNAVAILABLE] $($external.Name) ($($external.Port)): no running local service. No runnable server entry for $($external.Repo) was found in this project. Its related features will remain unavailable." -ForegroundColor Yellow
    }
}

if ($CheckOnly) {
    Write-Host 'Check complete. No services or browsers were started.'
    exit 0
}

$deadline = (Get-Date).AddSeconds(90)
$pending = @($services)
do {
    $pending = @($pending | Where-Object { -not (Test-ServiceReady $_) })
    if ($pending.Count -gt 0) { Start-Sleep -Milliseconds 500 }
} while ($pending.Count -gt 0 -and (Get-Date) -lt $deadline)
if ($pending.Count -gt 0) {
    $failed = @($pending | ForEach-Object { "$($_.Name) ($($_.Port))" })
    throw "These services did not pass HTTP health checks: $($failed -join ', '). Logs: $logRoot. No webpages were opened."
}

foreach ($service in $services) {
    Write-Host "[READY] $($service.Name): http://127.0.0.1:$($service.Port)" -ForegroundColor Green
}

if (-not $NoBrowser) {
    Start-Process 'http://127.0.0.1:5177'
    Start-Process 'http://127.0.0.1:5177/agent'
    Start-Process 'http://127.0.0.1:5177/scene3d'
    Start-Process 'http://127.0.0.1:5173'
}
Write-Host "Services run in the background. Closing this launcher will not stop them. Logs: $logRoot" -ForegroundColor Green
if ($externalMissing.Count -gt 0) { Write-Host "Unavailable feature services: $($externalMissing -join ', '). These features are not included in the local readiness result." -ForegroundColor Yellow }
} finally {
    if ($ownsMutex) { $launcherMutex.ReleaseMutex() }
    $launcherMutex.Dispose()
}
