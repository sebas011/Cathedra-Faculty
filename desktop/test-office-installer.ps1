# Reusable Windows smoke tests. These never target the installed office app.
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$PackageFolder,
  [string]$TestRoot = (Join-Path $env:LOCALAPPDATA 'Temp')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$PackageFolder = (Resolve-Path -LiteralPath $PackageFolder).ProviderPath.TrimEnd('\')
$installer = Join-Path $PSScriptRoot 'Install-Office.ps1'
$powershell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
$temporaryRoot = [IO.Path]::GetFullPath($TestRoot).TrimEnd('\')
$profileRoot = [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\')
if (-not $temporaryRoot.StartsWith($profileRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Installer tests require a temporary folder inside the current Windows profile.' }
$fixture = Join-Path $temporaryRoot ('cathedra-installer-test-' + [guid]::NewGuid().ToString('N'))
$install = Join-Path $fixture 'test installation with spaces'
$package = Join-Path $fixture 'download package with spaces'
$results = New-Object 'System.Collections.Generic.List[string]'
$previousFailurePoint = $env:CATHEDRA_INSTALL_TEST_FAILPOINT
$guard = $null

function Invoke-Installer([bool]$ShouldSucceed, [string]$Name, [string]$FailurePoint = '') {
  $env:CATHEDRA_INSTALL_TEST_FAILPOINT = $FailurePoint
  $output = @(& $powershell -NoProfile -ExecutionPolicy Bypass -File $installer -PackageFolder $package -InstallFolder $install -NoLaunch -TestMode 2>&1)
  $code = $LASTEXITCODE
  $global:LASTEXITCODE = 0
  $env:CATHEDRA_INSTALL_TEST_FAILPOINT = $null
  if (($code -eq 0) -ne $ShouldSucceed) { throw "$Name returned exit $code. $($output -join [Environment]::NewLine)" }
  if (-not $ShouldSucceed -and ($output -join '') -notmatch 'Installation stopped:') { throw "$Name did not report a clear installation error." }
  Write-Host "PASS: $Name"
  $results.Add($Name)
}

function Assert-Marker {
  foreach ($path in $script:Markers.Keys) {
    if ((Get-FileHash -LiteralPath (Join-Path $install $path) -Algorithm SHA256).Hash -ne $script:Markers[$path]) { throw "Existing office bytes changed: $path" }
  }
  if (Test-Path -LiteralPath (Join-Path $install 'data/.cathedra.lock')) { throw 'The installer did not remove the temporary lock it created.' }
}

function Save-Markers {
  $script:Markers = @{}
  foreach ($path in @('data/cathedra.db', 'data/password marker.bin', 'data/backups/old office backup.db')) {
    $script:Markers[$path] = (Get-FileHash -LiteralPath (Join-Path $install $path) -Algorithm SHA256).Hash
  }
}

try {
  [IO.Directory]::CreateDirectory($fixture) | Out-Null
  $sourceApp = if (Test-Path -LiteralPath (Join-Path $PackageFolder 'release-manifest.json')) { $PackageFolder } else { Join-Path $PackageFolder 'Cathedra Faculty' }
  & (Join-Path $sourceApp 'desktop/protect-local-folder.ps1') -Folder $fixture | Out-Null
  [IO.Directory]::CreateDirectory($package) | Out-Null
  foreach ($item in Get-ChildItem -LiteralPath $PackageFolder -Force) { Copy-Item -LiteralPath $item.FullName -Destination $package -Recurse -Force }
  $payload = if (Test-Path -LiteralPath (Join-Path $package 'release-manifest.json')) { $package } else { Join-Path $package 'Cathedra Faculty' }

  Invoke-Installer $true 'fresh install and paths containing spaces'
  if (Test-Path -LiteralPath (Join-Path $install 'data')) { throw 'A fresh install unexpectedly created or copied office data.' }
  [IO.Directory]::CreateDirectory((Join-Path $install 'data/backups')) | Out-Null
  [IO.File]::WriteAllBytes((Join-Path $install 'data/cathedra.db'), [byte[]](83,81,76,105,116,101,0,255,1,2,3,4))
  [IO.File]::WriteAllBytes((Join-Path $install 'data/password marker.bin'), [byte[]](0,128,255,2,7,19,44))
  [IO.File]::WriteAllText((Join-Path $install 'data/backups/old office backup.db'), 'Synthetic retained office backup. No real records.')
  Save-Markers

  Invoke-Installer $true 'update preserves existing database, password and backup bytes without a preexisting lock'
  Assert-Marker
  $backups = @(Get-ChildItem -LiteralPath $fixture -Directory | Where-Object { $_.Name -like 'test installation with spaces-backup-*' })
  if ($backups.Count -ne 1) { throw 'Update did not save exactly one private recovery copy.' }
  foreach ($path in $script:Markers.Keys) {
    if ((Get-FileHash -LiteralPath (Join-Path $backups[0].FullName $path) -Algorithm SHA256).Hash -ne $script:Markers[$path]) { throw "Backup differs from the original: $path" }
  }
  $manifestHash = (Get-FileHash -LiteralPath (Join-Path $install 'release-manifest.json')).Hash

  foreach ($point in @('during-app-retirement', 'after-app-retirement', 'during-promotion', 'after-promotion')) {
    Invoke-Installer $false "rollback restores application and office bytes ($point)" $point
    Assert-Marker
    if ((Get-FileHash -LiteralPath (Join-Path $install 'release-manifest.json')).Hash -ne $manifestHash) { throw 'Rollback changed the installed release manifest.' }
  }

  $lockPath = Join-Path $install 'data/.cathedra.lock'
  [IO.File]::WriteAllBytes($lockPath, [byte[]](0))
  $guard = [IO.File]::Open($lockPath, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
  $guard.Lock(0, 1)
  $backupCount = @(Get-ChildItem -LiteralPath $fixture -Directory | Where-Object { $_.Name -like '*-backup-*' }).Count
  Invoke-Installer $false 'active shared data lock prevents update before backup or replacement'
  if (@(Get-ChildItem -LiteralPath $fixture -Directory | Where-Object { $_.Name -like '*-backup-*' }).Count -ne $backupCount) { throw 'A blocked running instance caused backup writes.' }
  $guard.Dispose(); $guard = $null
  Remove-Item -LiteralPath $lockPath -Force
  Assert-Marker

  $tamper = Join-Path $payload '_internal/VERSION'
  $savedBytes = [IO.File]::ReadAllBytes($tamper)
  [IO.File]::WriteAllText($tamper, 'tampered')
  Invoke-Installer $false 'corrupt package checksum is rejected before installed files change'
  [IO.File]::WriteAllBytes($tamper, $savedBytes)
  Assert-Marker

  $payloadManifestPath = Join-Path $payload 'release-manifest.json'
  $payloadManifestBytes = [IO.File]::ReadAllBytes($payloadManifestPath)
  $unsafeManifest = Get-Content -LiteralPath $payloadManifestPath -Raw | ConvertFrom-Json
  $unsafeManifest.files[0].path = '../outside-the-package'
  [IO.File]::WriteAllText($payloadManifestPath, ($unsafeManifest | ConvertTo-Json -Depth 10))
  Invoke-Installer $false 'manifest path traversal is rejected'
  [IO.File]::WriteAllBytes($payloadManifestPath, $payloadManifestBytes)
  Assert-Marker

  [IO.File]::WriteAllText((Join-Path $payload 'unexpected-file.txt'), 'Synthetic unexpected package file.')
  Invoke-Installer $false 'unlisted payload file is rejected'
  Remove-Item -LiteralPath (Join-Path $payload 'unexpected-file.txt') -Force
  [IO.Directory]::CreateDirectory((Join-Path $payload 'data')) | Out-Null
  Invoke-Installer $false 'even an empty public runtime data folder is rejected'
  Remove-Item -LiteralPath (Join-Path $payload 'data') -Force
  Assert-Marker

  if ($payload -ne $package) {
    $readmePath = Join-Path $package 'OFFICE-READ-ME.txt'
    $readmeBytes = [IO.File]::ReadAllBytes($readmePath)
    [IO.File]::AppendAllText($readmePath, 'Synthetic wrapper corruption.')
    Invoke-Installer $false 'office wrapper checksum rejects a changed installer companion file'
    [IO.File]::WriteAllBytes($readmePath, $readmeBytes)
    Assert-Marker
  }

  $installedManifestPath = Join-Path $install 'release-manifest.json'
  $savedManifest = [IO.File]::ReadAllBytes($installedManifestPath)
  $installedVersionPath = Join-Path $install '_internal/VERSION'
  $savedVersion = [IO.File]::ReadAllBytes($installedVersionPath)
  $installedFrontendPath = Join-Path $install '_internal/frontend/dist/release-version.txt'
  $savedFrontend = [IO.File]::ReadAllBytes($installedFrontendPath)
  [IO.File]::WriteAllText($installedVersionPath, '99.0.0')
  [IO.File]::WriteAllText($installedFrontendPath, '99.0.0')
  $newer = Get-Content -LiteralPath $installedManifestPath -Raw | ConvertFrom-Json
  $newer.version = '99.0.0'
  foreach ($entry in $newer.files) {
    if ($entry.path -in @('_internal/VERSION', '_internal/frontend/dist/release-version.txt')) {
      $file = Join-Path $install $entry.path
      $entry.bytes = (Get-Item -LiteralPath $file).Length
      $entry.sha256 = (Get-FileHash -LiteralPath $file).Hash.ToLowerInvariant()
    }
  }
  [IO.File]::WriteAllText($installedManifestPath, ($newer | ConvertTo-Json -Depth 10))
  Invoke-Installer $false 'newer installed release is protected from downgrade'
  [IO.File]::WriteAllBytes($installedManifestPath, $savedManifest)
  [IO.File]::WriteAllBytes($installedVersionPath, $savedVersion)
  [IO.File]::WriteAllBytes($installedFrontendPath, $savedFrontend)
  Assert-Marker

  [IO.File]::WriteAllText($installedManifestPath, '{}')
  Invoke-Installer $false 'invalid existing manifest preserves office data'
  [IO.File]::WriteAllBytes($installedManifestPath, $savedManifest)
  Assert-Marker

  if (@(Get-ChildItem -LiteralPath $fixture -Directory | Where-Object { $_.Name -like '.*-install-*' }).Count) { throw 'A completed rollback left an application staging folder.' }
  Write-Host "Installer smoke tests passed: $($results.Count). All office fixtures were synthetic."
} finally {
  if ($guard) { $guard.Dispose() }
  $env:CATHEDRA_INSTALL_TEST_FAILPOINT = $previousFailurePoint
  $resolved = [IO.Path]::GetFullPath($fixture).TrimEnd('\')
  if ($resolved.StartsWith($temporaryRoot + '\', [StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $resolved) -match '^cathedra-installer-test-[a-f0-9]{32}$') {
    try { Remove-Item -LiteralPath $resolved -Recurse -Force }
    catch { Write-Warning "Could not remove synthetic test fixture: $resolved. $($_.Exception.Message)" }
  }
}
$global:LASTEXITCODE = 0
