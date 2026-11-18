param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$BackendRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RepoRoot = (Resolve-Path (Join-Path $BackendRoot "..")).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$EnvFile = Join-Path $BackendRoot ".env"
$LogRoot = Join-Path $BackendRoot "logs\local-services"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtualenv Python not found: $Python"
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Backend env file not found: $EnvFile"
}

New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

# Load simple KEY=value entries so Uvicorn child processes inherit a consistent
# config. Existing process variables take precedence over values in .env.
foreach ($line in Get-Content -LiteralPath $EnvFile) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$' -and $line -notmatch '^\s*#') {
        $key = $matches[1]
        $value = $matches[2].Trim('"', "'")
        if (-not (Test-Path "Env:$key")) {
            Set-Item -Path "Env:$key" -Value $value
        }
    }
}

# These overrides are for this local launcher only. They ensure each service
# talks to its sibling over loopback regardless of stale values in backend/.env.
$env:AI_SERVICES_ENABLED = "true"
$env:INFERENCE_SERVICE_ENABLED = "true"
$env:INFERENCE_SERVICE_URL = "http://127.0.0.1:8002"
$env:INFERENCE_ALLOW_REMOTE_HTTP = "false"
$env:MCP_ENABLED = "true"
$env:MCP_SERVER_URL = "http://127.0.0.1:8001/mcp"
$env:BACKEND_API_BASE_URL = "http://127.0.0.1:8000"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
if (-not $env:OLLAMA_MODEL) { $env:OLLAMA_MODEL = "qwen2.5:3b" }

foreach ($requiredSetting in @("DATABASE_URL", "JWT_SECRET_KEY", "MCP_SERVICE_TOKEN", "INFERENCE_SERVICE_TOKEN")) {
    if (-not (Get-Item -Path "Env:$requiredSetting" -ErrorAction SilentlyContinue).Value) {
        throw "Missing required setting '$requiredSetting' in backend/.env."
    }
}
if ($env:MCP_SERVICE_TOKEN -eq $env:JWT_SECRET_KEY) {
    throw "MCP_SERVICE_TOKEN must be different from JWT_SECRET_KEY."
}
if ($env:MCP_SERVICE_TOKEN.Length -lt 32 -or $env:INFERENCE_SERVICE_TOKEN.Length -lt 32) {
    throw "MCP_SERVICE_TOKEN and INFERENCE_SERVICE_TOKEN must each be at least 32 characters."
}

$serviceSpecs = @(
    [pscustomobject]@{
        Name = "crm-api"
        Port = 8000
        App = "app.main:app"
        Log = Join-Path $LogRoot "crm-api.log"
    },
    [pscustomobject]@{
        Name = "mcp"
        Port = 8001
        App = "app.modules.chatbot.mcp_service:app"
        Log = Join-Path $LogRoot "mcp.log"
    },
    [pscustomobject]@{
        Name = "inference"
        Port = 8002
        App = "app.modules.ai.inference_service:app"
        Log = Join-Path $LogRoot "inference.log"
    }
)

foreach ($service in $serviceSpecs) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $service.Port -ErrorAction SilentlyContinue
    if ($listener) {
        throw "Port $($service.Port) is already in use (needed for $($service.Name)). Stop the existing process and retry."
    }
}

$started = [System.Collections.Generic.List[object]]::new()
try {
    foreach ($service in $serviceSpecs) {
        $stdout = "$($service.Log).out"
        $stderr = "$($service.Log).err"
        $process = Start-Process -FilePath $Python `
            -ArgumentList @(
                "-m", "uvicorn", $service.App,
                "--host", "127.0.0.1",
                "--port", [string]$service.Port,
                "--env-file", $EnvFile
            ) `
            -WorkingDirectory $BackendRoot `
            -RedirectStandardOutput $stdout `
            -RedirectStandardError $stderr `
            -PassThru
        $started.Add([pscustomobject]@{ Name = $service.Name; Process = $process; Log = $service.Log })
        Write-Host "Started $($service.Name) (PID $($process.Id)) -> http://127.0.0.1:$($service.Port)"
    }

    $healthChecks = @(
        [pscustomobject]@{ Name = "CRM API"; Url = "http://127.0.0.1:8000/health" },
        [pscustomobject]@{ Name = "MCP"; Url = "http://127.0.0.1:8001/health" },
        [pscustomobject]@{ Name = "Inference"; Url = "http://127.0.0.1:8002/health" }
    )

    $deadline = (Get-Date).AddSeconds(30)
    $pending = [System.Collections.Generic.List[object]]::new()
    foreach ($check in $healthChecks) { $pending.Add($check) }
    while ($pending.Count -gt 0 -and (Get-Date) -lt $deadline) {
        foreach ($check in @($pending)) {
            try {
                $response = Invoke-RestMethod -Uri $check.Url -TimeoutSec 2
                if ($response.status -eq "ok") {
                    Write-Host "Healthy: $($check.Name) at $($check.Url)" -ForegroundColor Green
                    [void]$pending.Remove($check)
                }
            } catch {
                Start-Sleep -Milliseconds 500
            }
        }
    }

    if ($pending.Count -gt 0) {
        $failedNames = ($pending | ForEach-Object { $_.Name }) -join ", "
        Write-Warning "Health check timed out for: $failedNames. Inspect logs under $LogRoot"
    }

    try {
        $ollama = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
        $modelAvailable = @($ollama.models | Where-Object { $_.name -eq $env:OLLAMA_MODEL }).Count -gt 0
        if ($modelAvailable) {
            Write-Host "Healthy: Ollama has model '$env:OLLAMA_MODEL' at http://127.0.0.1:11434" -ForegroundColor Green
        } else {
            Write-Warning "Ollama is reachable, but model '$env:OLLAMA_MODEL' is not in /api/tags. Run: ollama pull $env:OLLAMA_MODEL"
        }
    } catch {
        Write-Warning "Ollama is not reachable at http://127.0.0.1:11434. Start Ollama, then check the inference log."
    }
    Write-Host "Logs: $LogRoot"
    Write-Host "Stop services with Ctrl+C in this window, or stop their listed PIDs."

    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:8000/docs"
    }

    while ($true) {
        Start-Sleep -Seconds 2
        foreach ($entry in $started) {
            $process = Get-Process -Id $entry.Process.Id -ErrorAction SilentlyContinue
            if (-not $process) {
                Write-Warning "$($entry.Name) stopped. Check $($entry.Log).err"
            }
        }
    }
} finally {
    foreach ($entry in $started) {
        $current = Get-Process -Id $entry.Process.Id -ErrorAction SilentlyContinue
        if ($current) {
            Stop-Process -Id $entry.Process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
