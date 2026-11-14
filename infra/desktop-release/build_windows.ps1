$ErrorActionPreference = 'Stop'
$work = Join-Path $env:RUNNER_TEMP 'aira-release'
python infra/desktop-release/prepare.py windows-x64 $work
if ($LASTEXITCODE) { throw 'Release input validation failed' }
$release = Get-Content (Join-Path $work 'release.json') | ConvertFrom-Json
$legacy = Join-Path $work 'legacy'
$installer = Start-Process (Join-Path $work 'AIRA-Setup-0.2.0.exe') -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/SP-','/NORESTART',"/DIR=$legacy") -PassThru
if (-not $installer.WaitForExit(300000)) { throw 'Pinned runtime extraction timed out' }
$installer.Refresh()
if ($installer.ExitCode -ne 0) { throw 'Pinned runtime extraction failed' }
$pgVersion = & "$legacy\pgsql\bin\postgres.exe" --version
if ($pgVersion -notmatch 'PostgreSQL\) 18\.') { throw 'PostgreSQL 18 required' }
python app/frontend/packaging/updates/fetch_sdk.py windows "$work\winsparkle"
if ($LASTEXITCODE) { throw 'Updater SDK download failed' }
$sdk = (Get-ChildItem "$work\winsparkle" -Filter WinSparkle.dll -Recurse | Where-Object { $_.FullName -match 'x64\\Release' } | Select-Object -First 1).Directory.Parent.Parent.FullName
$iscc = (Get-ChildItem 'C:\Program Files (x86)\Inno Setup*\ISCC.exe' | Select-Object -First 1).FullName
& app/frontend/packaging/windows/build.ps1 -ModelDir "$work\model\models-protected" -PgDir "$legacy\pgsql" -Python $env:pythonLocation -Out "$work\release" -Version $release.version -WinSparkleDir $sdk -Iscc $iscc -StageOnly
if ($LASTEXITCODE) { throw 'Runtime staging failed' }
& "$work\release\stage\python\python.exe" -s -E tools/test_windows_launcher.py
if ($LASTEXITCODE) { throw 'Static launcher regression failed' }
& "$work\release\stage\python\python.exe" -s -E tools/test_windows_startup.py
if ($LASTEXITCODE) { throw 'Startup/close regression failed' }
python tools/smoke_windows_desktop.py "$work\release\stage" --runs 2
if ($LASTEXITCODE) { throw 'Staged native launch failed' }
& $iscc /Q "/DSourceDir=$work\release\stage" "/DAppVersion=$($release.version)" "/O$work\release" app/frontend/packaging/windows/aira.iss
if ($LASTEXITCODE) { throw 'Installer compilation failed' }
$exe = Join-Path $work "release\AIRA-Setup-$($release.version).exe"
$installation = Start-Process $exe -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/SP-','/NORESTART',"/DIR=$work\installed") -Wait -PassThru
if ($installation.ExitCode -ne 0) { throw 'New installer failed' }
python tools/smoke_windows_desktop.py "$work\installed" --runs 2
if ($LASTEXITCODE) { throw 'Installed native launch failed' }
python infra/desktop-release/receipt.py windows-x64 $exe "$work\release\windows-x64.json"
if ($LASTEXITCODE) { throw 'Build receipt failed' }
