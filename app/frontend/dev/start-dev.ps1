# Starts the local AIRA dev stand on Windows: test PostgreSQL + backend + frontend.
# Usage (regular PowerShell window):
#   powershell -ExecutionPolicy Bypass -File app\frontend\dev\start-dev.ps1
#   powershell -ExecutionPolicy Bypass -File app\frontend\dev\start-dev.ps1 -Analysis model
#   powershell -ExecutionPolicy Bypass -File app\frontend\dev\start-dev.ps1 -Reset   # recreate the test DB
# Then open http://127.0.0.1:8017/aira/
param(
  [ValidateSet('fixture', 'model')] [string]$Analysis = 'fixture',
  [string]$DevRoot = "$env:USERPROFILE\AIRA-dev",
  [int]$PgPort = 15435,
  [int]$Port = 8017,
  # Recreate the test database (removes test documents). Use after "recovery_required" at startup.
  [switch]$Reset
)
$ErrorActionPreference = 'Stop'
$backend = Resolve-Path (Join-Path $PSScriptRoot '..\..\backend')
$pg = Join-Path $DevRoot 'pgsql\bin'
$data = Join-Path $DevRoot 'pgdata'

if (-not (Test-Path (Join-Path $pg 'pg_ctl.exe'))) { throw "PostgreSQL not found in $pg" }
& cmd /c "`"$pg\pg_ctl.exe`" -D `"$data`" status" | Out-Null
if ($LASTEXITCODE -ne 0) {
  & cmd /c "`"$pg\pg_ctl.exe`" -D `"$data`" -o `"-p $PgPort -c listen_addresses=127.0.0.1`" -l `"$DevRoot\pg.log`" -w start"
}
if ($Reset) { & cmd /c "`"$pg\dropdb.exe`" -h 127.0.0.1 -p $PgPort -U postgres --if-exists --force aira_native_test" }
& cmd /c "`"$pg\psql.exe`" -h 127.0.0.1 -p $PgPort -U postgres -Atc `"select 1 from pg_database where datname='aira_native_test'`"" | Set-Variable exists
if (-not $exists) { & cmd /c "`"$pg\createdb.exe`" -h 127.0.0.1 -p $PgPort -U postgres aira_native_test" }

Set-Location $backend
# Base Python 3.12 with requirements.lock installed. Not .venv\Scripts\python.exe: on Windows
# it is a redirecting launcher and the native analysis worker fails through it.
$python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
if (-not (Test-Path $python)) { $python = (Get-Command python).Source }
& $python ..\frontend\dev\serve_dev.py --runtime-root (Join-Path $DevRoot 'runtime') `
  --pg-port $PgPort --port $Port --analysis $Analysis --initialize-test-database
