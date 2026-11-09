# Собирает пилотный установщик AIRA для Windows: AIRA-Setup-<версия>.exe
#
#   powershell -ExecutionPolicy Bypass -File app\frontend\packaging\windows\build.ps1 `
#       -ModelDir C:\AIRA-models\models-0.2m -PgDir C:\pgsql
#
# Нужны: Python 3.12 (обычная установка, с tkinter), портативный PostgreSQL 18 для Windows (bin, lib, share),
# распакованный пакет модели models-0.2m (релиз GitHub) и Inno Setup 6. Бэкенд копируется без изменений.
param(
  [string]$ModelDir = "$env:USERPROFILE\AIRA-dev\models\unpacked\models-0.2m",
  [string]$PgDir = "$env:USERPROFILE\AIRA-dev\pgsql",
  [string]$Python = "$env:LOCALAPPDATA\Programs\Python\Python312",
  [string]$Out = "$env:USERPROFILE\AIRA-dev\build",
  [string]$Version = '0.1.0',
  [string]$Iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
  [switch]$NoModel,
  [switch]$StageOnly
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$repo = (Resolve-Path (Join-Path $here '..\..\..\..')).Path
$stage = Join-Path $Out 'stage'
$py = Join-Path $Python 'python.exe'

function Copy-Tree($from, $to, [string[]]$excludeDirs = @(), [string[]]$excludeFiles = @()) {
  $rc = @($from, $to, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1', '/XD', '__pycache__') + $excludeDirs
  $rc += '/XF'; $rc += @('*.pyc', '*.pdb') + $excludeFiles
  robocopy @rc | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "robocopy failed: $from" }
}

foreach ($p in @($py, (Join-Path $PgDir 'bin\postgres.exe'))) { if (-not (Test-Path $p)) { throw "Not found: $p" } }
if (-not $NoModel -and -not (Test-Path (Join-Path $ModelDir 'manifest.json'))) { throw "Model manifest not found in $ModelDir (or use -NoModel)" }
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force $stage | Out-Null

Write-Host '1/6 Python'
Copy-Tree $Python "$stage\python" @("$Python\Lib\site-packages", "$Python\Lib\test", "$Python\Lib\idlelib", "$Python\Doc", "$Python\Scripts", "$Python\include", "$Python\libs", "$Python\Tools")
$req = Join-Path $Out 'requirements-runtime.txt'
# Только то, что нужно для работы: без инструментов тестов и проверки кода.
Get-Content (Join-Path $repo 'app\backend\requirements.lock') | Where-Object { $_ -notmatch '^(pytest|ruff|iniconfig|pluggy|Pygments)==' } | Set-Content $req -Encoding ascii
& $py -m pip install --disable-pip-version-check --no-warn-script-location -q --target "$stage\python\Lib\site-packages" `
  -r $req -r (Join-Path $repo 'engine\requirements-engine.txt') -r (Join-Path $here 'requirements-desktop.txt')
if ($LASTEXITCODE) { throw 'pip install failed' }
Remove-Item -Recurse -Force "$stage\python\Lib\site-packages\bin" -ErrorAction SilentlyContinue

Write-Host '2/6 PostgreSQL'
foreach ($d in 'bin', 'lib', 'share') { Copy-Tree (Join-Path $PgDir $d) "$stage\pgsql\$d" }

Write-Host '3/6 Backend (без изменений) и модель'
Copy-Tree (Join-Path $repo 'app\backend\src') "$stage\app\backend\src" @('*.egg-info')
Copy-Tree (Join-Path $repo 'app\backend\migrations') "$stage\app\backend\migrations"
Copy-Item (Join-Path $repo 'app\backend\alembic.ini') "$stage\app\backend\alembic.ini"
if (-not $NoModel) {
  & $py (Join-Path $repo 'tools\prepare_ml_bundle.py') --models $ModelDir --destination "$stage\app\backend\ml_bundle"
  if ($LASTEXITCODE) { throw 'prepare_ml_bundle failed' }
}

Write-Host '4/6 Frontend и запуск'
Copy-Tree (Join-Path $repo 'app\frontend\static') "$stage\app\frontend\static"
Copy-Item (Join-Path $repo 'app\frontend\aira_host.py') "$stage\app\frontend\aira_host.py"
New-Item -ItemType Directory -Force "$stage\launcher" | Out-Null
Copy-Item (Join-Path $here 'aira_launcher.pyw') "$stage\launcher\aira_launcher.pyw"
Copy-Item (Join-Path $here 'THIRD-PARTY.txt') "$stage\launcher\THIRD-PARTY.txt"
Set-Content "$stage\launcher\VERSION" $Version -Encoding ascii
# Иконка: PNG-логотип внутри ICO.
& $py -c @"
import struct, sys
png = open(sys.argv[1], 'rb').read()
w = int.from_bytes(png[16:20], 'big'); h = int.from_bytes(png[20:24], 'big')
hdr = struct.pack('<HHH', 0, 1, 1) + struct.pack('<BBBBHHII', w % 256, h % 256, 0, 0, 1, 32, len(png), 22)
open(sys.argv[2], 'wb').write(hdr + png)
"@ (Join-Path $repo 'app\frontend\static\logo.png') "$stage\launcher\aira.ico"

Write-Host '5/6 Предкомпиляция Python'
& "$stage\python\python.exe" -s -E -m compileall -q -j 0 "$stage\app" "$stage\launcher" | Out-Null

$files = Get-ChildItem -Recurse -File $stage
'{0} файлов, {1:N0} МБ' -f $files.Count, (($files | Measure-Object Length -Sum).Sum / 1MB)
if ($StageOnly) { Write-Host "Готова папка: $stage"; return }

Write-Host '6/6 Установщик (Inno Setup)'
if (-not (Test-Path $Iscc)) { throw "Inno Setup not found: $Iscc" }
& $Iscc /Q "/DSourceDir=$stage" "/DAppVersion=$Version" "/O$Out" (Join-Path $here 'aira.iss')
if ($LASTEXITCODE) { throw 'ISCC failed' }
Get-Item (Join-Path $Out "AIRA-Setup-$Version.exe") | Select-Object FullName, @{n = 'MB'; e = { [math]::Round($_.Length / 1MB) } }
