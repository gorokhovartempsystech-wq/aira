#Requires -Version 5.1
# Native Windows build only. Does not install old releases or read signing secrets.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$Python,
  [Parameter(Mandatory=$true)][string]$PgDir,
  [Parameter(Mandatory=$true)][string]$Iscc,
  [string]$Work = (Join-Path $env:SystemDrive ('AIRA-manual-0.2.9-' + [guid]::NewGuid().ToString('N').Substring(0,8))),
  [ValidatePattern('^0\.2\.[0-9]+$')][string]$Version = '0.2.9'
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run on native Windows x64.' }
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$py = Join-Path $Python 'python.exe'
$postgres = Join-Path $PgDir 'bin\postgres.exe'
foreach ($path in @($py, $postgres, $Iscc)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required tool missing: $path" }
}
$Work = [IO.Path]::GetFullPath($Work)
if ($Work -match '[^\x20-\x7E]') { throw 'Choose an ASCII build path, for example C:\AIRA-build-029.' }
if (Test-Path -LiteralPath $Work) { throw 'Choose a new build directory; existing directories are never removed.' }
Push-Location $repo
try {
  $sourceSha = (& git rev-parse HEAD).Trim()
  if ($LASTEXITCODE -or $sourceSha -notmatch '^[0-9a-f]{40}$') { throw 'A Git checkout is required.' }
  & git diff --quiet HEAD -- app/backend/src app/backend/migrations app/frontend engine/aira_ml tools
  if ($LASTEXITCODE) { throw 'Release source has uncommitted changes.' }
  $extra = @(& git ls-files --others --exclude-standard -- app/backend/src app/frontend/static engine/aira_ml tools)
  if ($extra.Count) { throw 'Untracked release source must be reviewed before building.' }
  & $py -c "import struct,sys,tkinter; assert sys.version_info[:2] == (3,12); assert struct.calcsize('P') == 8"
  if ($LASTEXITCODE) { throw 'Python 3.12 x64 with tkinter is required.' }
  $pgVersion = & $postgres --version
  if ($LASTEXITCODE -or $pgVersion -notmatch 'PostgreSQL\) 18\.') { throw 'A Windows PostgreSQL 18 runtime is required.' }
  New-Item -ItemType Directory -Path $Work | Out-Null
  & $py -m venv (Join-Path $Work 'checks')
  if ($LASTEXITCODE) { throw 'Cannot create isolated test environment.' }
  $checkPy = Join-Path $Work 'checks\Scripts\python.exe'
  & $checkPy -m pip --isolated install --disable-pip-version-check --index-url https://pypi.org/simple -r app/backend/requirements.lock -r engine/requirements-engine.txt
  if ($LASTEXITCODE) { throw 'Test dependency installation failed.' }
  & $checkPy -m pytest --noconftest -q app/frontend/packaging/windows/test_licensing.py app/frontend/tests
  if ($LASTEXITCODE) { throw 'Licensing/profile/update tests failed.' }
  Push-Location (Join-Path $repo 'engine')
  try {
    & $checkPy -m pytest -q tests/test_exchange_duplicates.py
    if ($LASTEXITCODE) { throw 'Exchange-direction duplicate regressions failed.' }
  }
  finally {
    Pop-Location
  }
  $jsTestsRun = $false
  if (Get-Command node -ErrorAction SilentlyContinue) {
    $jsFiles = @(Get-ChildItem app/frontend/tests -Filter '*.test.mjs' | ForEach-Object FullName)
    & node --test @jsFiles
    if ($LASTEXITCODE) { throw 'Frontend JavaScript tests failed.' }
    $jsTestsRun = $true
  }
  $modelsZip = Join-Path $Work 'aira-models-0.2m-protected-1.zip'
  Invoke-WebRequest -UseBasicParsing -Uri 'https://51.250.81.70/downloads/aira-models-0.2m-protected-1.zip' -OutFile $modelsZip
  if ((Get-FileHash -Algorithm SHA256 $modelsZip).Hash.ToLowerInvariant() -ne '7d4f227bd8f9edab1bbcbbddc199be8abeb5abd5b3b4329f717e5d041606ba4e') { throw 'Model archive checksum mismatch.' }
  $modelsRoot = Join-Path $Work 'models'
  Expand-Archive -LiteralPath $modelsZip -DestinationPath $modelsRoot
  $models = Join-Path $modelsRoot 'models-protected'
  & $checkPy -c "import sys;sys.path.insert(0,sys.argv[1]);from ara.model_protection.bundle import configuration;assert configuration(sys.argv[2]) is not None" (Join-Path $repo 'app\backend\src') $models
  if ($LASTEXITCODE) { throw 'Protected model validation failed.' }
  $sdk = Join-Path $Work 'winsparkle'
  & $checkPy app/frontend/packaging/updates/fetch_sdk.py windows $sdk
  if ($LASTEXITCODE) { throw 'Pinned WinSparkle SDK validation failed.' }
  $dll = Get-ChildItem $sdk -Filter WinSparkle.dll -Recurse | Where-Object { $_.FullName -match 'x64\\Release' } | Select-Object -First 1
  if (-not $dll) { throw 'Verified x64 WinSparkle DLL missing.' }
  $sdkRoot = $dll.Directory.Parent.Parent.FullName
  $out = Join-Path $Work 'release'
  & app/frontend/packaging/windows/build.ps1 -ModelDir $models -PgDir $PgDir -Python $Python -Out $out -Version $Version -WinSparkleDir $sdkRoot -Iscc $Iscc -StageOnly
  if ($LASTEXITCODE) { throw 'Runtime staging failed.' }
  $stage = Join-Path $out 'stage'
  $stagePy = Join-Path $stage 'python\python.exe'
  & $stagePy -s -E tools/test_windows_launcher.py
  if ($LASTEXITCODE) { throw 'Launcher regression failed.' }
  & $stagePy -s -E tools/test_windows_startup.py
  if ($LASTEXITCODE) { throw 'Startup/shutdown regression failed.' }
  & $checkPy tools/smoke_windows_desktop.py $stage --runs 2
  if ($LASTEXITCODE) { throw 'Staged native activation-screen smoke failed.' }
  if (@(Get-ChildItem $stage -Recurse -File -Filter 'secrets.env').Count) { throw 'Operator settings must not enter the installer.' }
  if (@(Get-ChildItem (Join-Path $stage 'app\backend\ml_bundle\models') -Recurse -File -Filter '*.onnx').Count) { throw 'Plaintext models must not enter the installer.' }
  & $Iscc /Q "/DSourceDir=$stage" "/DAppVersion=$Version" "/O$out" app/frontend/packaging/windows/aira.iss
  if ($LASTEXITCODE) { throw 'Installer compilation failed.' }
  $installer = Get-Item (Join-Path $out "AIRA-Setup-$Version.exe")
  $receipt = [ordered]@{
    version = $Version; platform = 'windows-x64'; source_sha = $sourceSha
    filename = $installer.Name; bytes = $installer.Length
    sha256 = (Get-FileHash -Algorithm SHA256 $installer.FullName).Hash.ToLowerInvariant()
    python_sha256 = (Get-FileHash -Algorithm SHA256 $py).Hash.ToLowerInvariant()
    postgres_sha256 = (Get-FileHash -Algorithm SHA256 $postgres).Hash.ToLowerInvariant()
    staged_native_launches_passed = 2; frontend_javascript_tests_run = $jsTestsRun
    exchange_duplicate_regressions_passed = 6
    installed_exe_tested = $false; signed_for_updates = $false; published = $false
  }
  $receipt | ConvertTo-Json | Set-Content (Join-Path $out 'windows-manual-receipt.json') -Encoding UTF8
  Write-Host "Candidate installer: $($installer.FullName)"
  Write-Host 'Install this EXE on the test PC, verify activation, analysis, DOCX export and restart before publication.'
  Write-Host 'The update signing key is not needed on this Windows PC.'
}
finally {
  Pop-Location
}
