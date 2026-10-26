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
  $script:LastInstallerOutput = $output -join [Environment]::NewLine
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

function Test-TreeSnapshot([string]$Folder) {
  $snapshot = @{}
  foreach ($item in @(Get-ChildItem -LiteralPath $Folder -Recurse -Force)) {
    $relative = $item.FullName.Substring($Folder.Length + 1).Replace('\', '/')
    $snapshot[$relative] = if ($item.PSIsContainer) { 'directory' } else { "$($item.Length):$((Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash)" }
  }
  return $snapshot
}

function Assert-TestTree($Expected, [string]$Folder) {
  $actual = Test-TreeSnapshot $Folder
  if ($actual.Count -ne $Expected.Count) { throw "A synthetic office tree changed: $Folder" }
  foreach ($path in $Expected.Keys) {
    if (-not $actual.ContainsKey($path) -or $actual[$path] -cne $Expected[$path]) { throw "A synthetic office path changed: $path" }
  }
}

function Get-TestBackups {
  return @(Get-ChildItem -LiteralPath $fixture -Directory | Where-Object { $_.Name -like 'test installation with spaces-backup-*' })
}

function Assert-PrivateTestFolder([string]$Folder) {
  $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  $allowed = @($currentUser, 'S-1-5-18', 'S-1-5-32-544')
  $items = @((Get-Item -LiteralPath $Folder)) + @(Get-ChildItem -LiteralPath $Folder -Recurse -Force)
  if (-not (Get-Acl -LiteralPath $Folder).AreAccessRulesProtected) { throw 'The recovery folder permits inherited access.' }
  foreach ($item in $items) {
    foreach ($rule in (Get-Acl -LiteralPath $item.FullName).Access) {
      $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
      if ($sid -notin $allowed -or $rule.AccessControlType -ne 'Allow') { throw "The recovery copy has unexpected Windows access: $($item.FullName)" }
    }
  }
}

function Assert-NewCompleteBackup($Previous, $Expected) {
  $newBackups = @(Get-TestBackups | Where-Object { $_.FullName -notin $Previous })
  if ($newBackups.Count -ne 1) { throw 'A legacy update did not create exactly one complete recovery copy.' }
  Assert-TestTree $Expected $newBackups[0].FullName
  Assert-PrivateTestFolder $newBackups[0].FullName
}

function Assert-RejectedWithoutMutation([string]$Name) {
  $before = Test-TreeSnapshot $install
  $backupCount = @(Get-TestBackups).Count
  Invoke-Installer $false $Name
  Assert-TestTree $before $install
  if (@(Get-TestBackups).Count -ne $backupCount) { throw "$Name created a recovery folder before rejecting the installation." }
}

function Write-TestManifest([string]$Folder, $Manifest) {
  [IO.File]::WriteAllText((Join-Path $Folder 'release-manifest.json'), ($Manifest | ConvertTo-Json -Depth 10))
}

function Set-TestVersion([string]$Folder, $Manifest, [string]$Version) {
  $Manifest.version = $Version
  foreach ($entry in $Manifest.files) {
    if ($entry.path -in @('_internal/VERSION', '_internal/frontend/dist/release-version.txt')) {
      $path = Join-Path $Folder $entry.path
      [IO.File]::WriteAllText($path, $Version)
      $entry.bytes = (Get-Item -LiteralPath $path).Length
      $entry.sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
  }
}

function Convert-ToLegacyTestRelease([string]$Folder, [bool]$IncludeDocument) {
  $manifest = Get-Content -LiteralPath (Join-Path $Folder 'release-manifest.json') -Raw | ConvertFrom-Json
  $manifest.PSObject.Properties.Remove('build_identity')
  $manifest.PSObject.Properties.Remove('source_snapshot_sha256')
  $manifest.files = @($manifest.files | Where-Object { $_.path -cne '_internal/BUILD_ID' })
  Remove-Item -LiteralPath (Join-Path $Folder '_internal/BUILD_ID') -Force
  Set-TestVersion $Folder $manifest '0.3.2'
  if ($IncludeDocument) {
    $relative = 'docs/legacy-release-notes.txt'
    $document = Join-Path $Folder $relative
    [IO.Directory]::CreateDirectory((Split-Path -Parent $document)) | Out-Null
    [IO.File]::WriteAllText($document, 'Synthetic manifest-listed legacy release document. No real office data.')
    $manifest.files += [pscustomobject]@{
      path = $relative
      bytes = (Get-Item -LiteralPath $document).Length
      sha256 = (Get-FileHash -LiteralPath $document -Algorithm SHA256).Hash.ToLowerInvariant()
    }
  }
  Write-TestManifest $Folder $manifest
}

function Write-SyntheticDatabase([string]$Path) {
  # An 8 KiB SQLite database with one synthetic_records row. Keeping the fixture
  # compressed lets this Windows-only installer test run without Python or SQLite tools.
  $encoded = 'H4sIAAAAAAAC/+3YsUpDMRQG4KQKTqKb6w8uCmIHRztY5W5dtN0l5uZqaJpIei54XUTwyXwyUy5FaBfHgv/HCZwk5wX+M72feHFoUl4YwZU6VlqrG0D1BuqXLmd/4/4nh6vhoy9VioiIiIiIiOjfetcHJ8Oh/jwV8xTcsovy4sTbx+xsyvVy62Fw91CNZxVm49tJha1vnPkaPop7dhmv2S9M7jB33QViKlFf3JusOsQ2hPM+m3+rUkRERERERES0s0Z6T31M10sApKbx1qHfBVyXoF9aE9AY2wbpkDKMtamNgtqIufwBfKiVUQAgAAA='
  $compressed = New-Object IO.MemoryStream(,[Convert]::FromBase64String($encoded))
  $gzip = New-Object IO.Compression.GZipStream($compressed, [IO.Compression.CompressionMode]::Decompress)
  $output = [IO.File]::Open($Path, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
  try { $gzip.CopyTo($output) } finally { $output.Dispose(); $gzip.Dispose(); $compressed.Dispose() }
  if ((Get-Item -LiteralPath $Path).Length -ne 8192 -or
      (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -cne '2B7EC8C3E969C94E2133CF173F749B6E5515952568F2E1ED64C1C4BD3D5C97C9') {
    throw 'The synthetic SQLite fixture is invalid.'
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

  # Reproduce the historical installed-only format without copying any real
  # application records: 0.3.2 predates both manifest identities and BUILD_ID.
  Convert-ToLegacyTestRelease $install $true
  Write-SyntheticDatabase (Join-Path $install 'data/cathedra.db')
  [IO.Directory]::CreateDirectory((Join-Path $install 'data/attachments/nested empty folder')) | Out-Null
  [IO.File]::WriteAllBytes((Join-Path $install 'data/attachments/synthetic attachment.bin'), [byte[]](0,255,127,13,10,3,79))
  [IO.File]::WriteAllBytes((Join-Path $install 'data/.cathedra.lock'), [byte[]](0))
  $legacyManifestBytes = [IO.File]::ReadAllBytes($installedManifestPath)
  $legacyVersionBytes = [IO.File]::ReadAllBytes($installedVersionPath)
  $legacyFrontendBytes = [IO.File]::ReadAllBytes($installedFrontendPath)
  $legacySidecars = @(
    'OFFICE-UPDATE-VALIDATION.json',
    'START HERE - OFFICE SETUP.txt',
    'TRANSFER-VALIDATION.json',
    'docs/FACULTY_DESIGN_SYSTEM.md',
    'docs/redesign-dashboard.jpg',
    'docs/redesign-settings.jpg',
    'docs/redesign-sign-in.jpg'
  )
  foreach ($sidecar in $legacySidecars) {
    $sidecarPath = Join-Path $install $sidecar
    [IO.Directory]::CreateDirectory((Split-Path -Parent $sidecarPath)) | Out-Null
    [IO.File]::WriteAllText($sidecarPath, "Synthetic legacy sidecar fixture: $sidecar")
  }
  $legacyTree = Test-TreeSnapshot $install
  $legacyDataTree = Test-TreeSnapshot (Join-Path $install 'data')

  $badLegacy = Get-Content -LiteralPath $installedManifestPath -Raw | ConvertFrom-Json
  $badLegacy.files[0].sha256 = ('0' * 64)
  Write-TestManifest $install $badLegacy
  Assert-RejectedWithoutMutation 'legacy manifest checksum tampering is rejected before backup or replacement'
  [IO.File]::WriteAllBytes($installedManifestPath, $legacyManifestBytes)

  foreach ($unsafe in @('../outside-the-installation', 'data/cathedra.db')) {
    $badLegacy = Get-Content -LiteralPath $installedManifestPath -Raw | ConvertFrom-Json
    $badLegacy.files[0].path = $unsafe
    Write-TestManifest $install $badLegacy
    Assert-RejectedWithoutMutation "unsafe legacy manifest path is rejected ($unsafe)"
    [IO.File]::WriteAllBytes($installedManifestPath, $legacyManifestBytes)
  }

  $badLegacy = Get-Content -LiteralPath $installedManifestPath -Raw | ConvertFrom-Json
  $badLegacy.product = 'fsdp'
  Write-TestManifest $install $badLegacy
  Assert-RejectedWithoutMutation 'legacy manifest for another product is rejected'
  [IO.File]::WriteAllBytes($installedManifestPath, $legacyManifestBytes)

  $badLegacy = Get-Content -LiteralPath $installedManifestPath -Raw | ConvertFrom-Json
  $badLegacy.files = @($badLegacy.files | Where-Object { $_.path -cne 'desktop/protect-local-folder.ps1' })
  Write-TestManifest $install $badLegacy
  Assert-RejectedWithoutMutation 'incomplete legacy manifest is rejected'
  [IO.File]::WriteAllBytes($installedManifestPath, $legacyManifestBytes)

  foreach ($presentIdentity in @('build_identity', 'source_snapshot_sha256')) {
    $badLegacy = Get-Content -LiteralPath $installedManifestPath -Raw | ConvertFrom-Json
    $badLegacy | Add-Member -NotePropertyName $presentIdentity -NotePropertyValue 'synthetic incomplete identity'
    Write-TestManifest $install $badLegacy
    Assert-RejectedWithoutMutation "partially missing legacy identities are rejected ($presentIdentity present)"
    [IO.File]::WriteAllBytes($installedManifestPath, $legacyManifestBytes)
  }

  $badLegacy = Get-Content -LiteralPath $installedManifestPath -Raw | ConvertFrom-Json
  $badLegacy | Add-Member -NotePropertyName build_identity -NotePropertyValue $null
  $badLegacy | Add-Member -NotePropertyName source_snapshot_sha256 -NotePropertyValue $null
  Write-TestManifest $install $badLegacy
  Assert-RejectedWithoutMutation 'explicitly null modern identities are not treated as a historical manifest'
  [IO.File]::WriteAllBytes($installedManifestPath, $legacyManifestBytes)

  foreach ($unsupportedVersion in @('0.3.1', '0.3.3')) {
    $badLegacy = Get-Content -LiteralPath $installedManifestPath -Raw | ConvertFrom-Json
    Set-TestVersion $install $badLegacy $unsupportedVersion
    Write-TestManifest $install $badLegacy
    Assert-RejectedWithoutMutation "missing modern identities are rejected for unsupported installed version $unsupportedVersion"
    [IO.File]::WriteAllBytes($installedManifestPath, $legacyManifestBytes)
    [IO.File]::WriteAllBytes($installedVersionPath, $legacyVersionBytes)
    [IO.File]::WriteAllBytes($installedFrontendPath, $legacyFrontendBytes)
  }

  [IO.File]::WriteAllText((Join-Path $install 'unlisted-legacy-file.txt'), 'Synthetic unexpected historical file.')
  Assert-RejectedWithoutMutation 'unlisted legacy application file is rejected'
  Remove-Item -LiteralPath (Join-Path $install 'unlisted-legacy-file.txt') -Force
  Assert-TestTree $legacyTree $install

  $incomingVersionBytes = [IO.File]::ReadAllBytes((Join-Path $payload '_internal/VERSION'))
  $incomingFrontendBytes = [IO.File]::ReadAllBytes((Join-Path $payload '_internal/frontend/dist/release-version.txt'))
  $incomingBuildBytes = [IO.File]::ReadAllBytes((Join-Path $payload '_internal/BUILD_ID'))
  Convert-ToLegacyTestRelease $payload $false
  Assert-RejectedWithoutMutation 'a downloaded legacy package still requires modern build identities'
  [IO.File]::WriteAllBytes($payloadManifestPath, $payloadManifestBytes)
  [IO.File]::WriteAllBytes((Join-Path $payload '_internal/VERSION'), $incomingVersionBytes)
  [IO.File]::WriteAllBytes((Join-Path $payload '_internal/frontend/dist/release-version.txt'), $incomingFrontendBytes)
  [IO.File]::WriteAllBytes((Join-Path $payload '_internal/BUILD_ID'), $incomingBuildBytes)

  $legacyBackupCount = @(Get-TestBackups).Count
  $guard = [IO.File]::Open($lockPath, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
  $guard.Lock(0, 1)
  Invoke-Installer $false 'active data lock prevents legacy upgrade before backup or replacement'
  $guard.Dispose(); $guard = $null
  if (@(Get-TestBackups).Count -ne $legacyBackupCount) { throw 'A blocked legacy instance caused backup writes.' }
  Assert-TestTree $legacyTree $install

  foreach ($point in @('during-app-retirement', 'after-app-retirement', 'during-promotion', 'after-promotion')) {
    $previousBackups = @(Get-TestBackups | ForEach-Object { $_.FullName })
    Invoke-Installer $false "rollback restores complete legacy application and office bytes ($point)" $point
    if ($script:LastInstallerOutput -notmatch 'Your previous application and records have been restored\.') { throw 'The legacy rollback did not finish successfully.' }
    Assert-TestTree $legacyTree $install
    Assert-NewCompleteBackup $previousBackups $legacyTree
  }

  $previousBackups = @(Get-TestBackups | ForEach-Object { $_.FullName })
  Invoke-Installer $true '0.3.2 upgrade preserves records and backs up known legacy sidecars without mixing them into the new release'
  Assert-TestTree $legacyDataTree (Join-Path $install 'data')
  Assert-NewCompleteBackup $previousBackups $legacyTree
  $newBackups = @(Get-TestBackups | Where-Object { $_.FullName -notin $previousBackups })
  if ($newBackups.Count -ne 1) { throw 'The sidecar migration did not create exactly one verified recovery copy.' }
  foreach ($sidecar in $legacySidecars) {
    if (-not (Test-Path -LiteralPath (Join-Path $newBackups[0].FullName $sidecar) -PathType Leaf)) { throw "Legacy sidecar was not preserved in the recovery copy: $sidecar" }
    if (Test-Path -LiteralPath (Join-Path $install $sidecar)) { throw "Legacy sidecar was incorrectly promoted into the new application: $sidecar" }
  }
  if ((Get-FileHash -LiteralPath $installedManifestPath -Algorithm SHA256).Hash -cne
      (Get-FileHash -LiteralPath $payloadManifestPath -Algorithm SHA256).Hash) { throw 'The legacy upgrade did not promote the new release manifest.' }
  if (Test-Path -LiteralPath (Join-Path $install 'docs/legacy-release-notes.txt')) { throw 'The old application document was left mixed into the new release.' }

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
