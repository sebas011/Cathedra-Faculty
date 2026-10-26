# Windows PowerShell 5.1; the downloaded package needs no development tools.
[CmdletBinding()]
param(
  [string]$PackageFolder = $PSScriptRoot,
  [string]$InstallFolder = (Join-Path $env:USERPROFILE 'Cathedra-Faculty'),
  [switch]$NoLaunch,
  [switch]$TestMode
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$script:DataGuard = $null
$script:GuardPath = $null
$script:CreatedGuard = $false
$transaction = $null
$backup = $null
$mutex = $null
$ownsMutex = $false
$oldApp = $null
$newApp = $null
$changedInstall = $false
$succeeded = $false
$originalData = $null
$hadData = $false
$oldMoved = New-Object 'System.Collections.Generic.List[string]'
$newPromoted = New-Object 'System.Collections.Generic.List[string]'

function Full-Path([string]$Path) {
  return [IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Is-Within([string]$Child, [string]$Parent) {
  return $Child.StartsWith($Parent.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NoLinkedAncestors([string]$Path) {
  $cursor = $Path
  while ($cursor) {
    if (Test-Path -LiteralPath $cursor) {
      $item = Get-Item -LiteralPath $cursor -Force
      if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Linked folders or files are not supported: $cursor"
      }
    }
    $parent = Split-Path -Parent $cursor
    if ($parent -eq $cursor) { break }
    $cursor = $parent
  }
}

function Get-SafeItems([string]$Folder) {
  $pending = New-Object 'System.Collections.Generic.Stack[string]'
  $pending.Push($Folder)
  while ($pending.Count) {
    foreach ($item in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
      if (-not (Is-Within $item.FullName $Folder) -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "A linked or out-of-folder item was found: $($item.FullName)"
      }
      $item
      if ($item.PSIsContainer) { $pending.Push($item.FullName) }
    }
  }
}

function Relative-Path([string]$Path, [string]$Folder) {
  return $Path.Substring($Folder.Length + 1).Replace('\', '/')
}

function File-Digest([string]$Path) {
  if ($script:DataGuard -and $Path -eq $script:GuardPath) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
      $script:DataGuard.Position = 0
      return ([BitConverter]::ToString($algorithm.ComputeHash($script:DataGuard))).Replace('-', '').ToLowerInvariant()
    } finally { $algorithm.Dispose(); $script:DataGuard.Position = 0 }
  }
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-RelativeFile([string]$Path, [bool]$OfficeWrapper = $false) {
  if (-not $Path -or $Path.Contains('\') -or [IO.Path]::IsPathRooted($Path)) { throw "Invalid manifest path: $Path" }
  foreach ($part in $Path.Split('/')) {
    if (-not $part -or $part -eq '.' -or $part -eq '..' -or $part -match '[<>:"|?*\x00-\x1f]' -or
        $part -match '[. ]$' -or $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') {
      throw "Invalid manifest path: $Path"
    }
  }
  $payloadPath = if ($OfficeWrapper -and $Path.StartsWith('Cathedra Faculty/', [StringComparison]::Ordinal)) { $Path.Substring('Cathedra Faculty/'.Length) } else { $Path }
  if ($payloadPath -match '^(?i:data)(/|$)' -or (-not $OfficeWrapper -and $Path -eq 'release-manifest.json')) { throw 'Runtime data must not be part of the application manifest.' }
  if ($payloadPath -match '(?i)(\.db($|-)|\.sqlite[0-9]*($|-))' -and $payloadPath -cne '_internal/backend/cathedra-seed.db') {
    throw "Unexpected database in the application payload: $Path"
  }
}

function Read-Manifest([string]$Path, [string[]]$Required, [bool]$Installed = $false) {
  try {
    $manifest = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    foreach ($name in $Required) {
      if ($null -eq $manifest -or $null -eq $manifest.PSObject.Properties[$name]) { throw 'Missing manifest field.' }
    }
    return $manifest
  } catch {
    if ($Installed) {
      throw "The existing installation manifest cannot be verified: $Path. Keep the complete installed folder and data unchanged. Use an official migration package for this installed version; do not edit the manifest."
    }
    throw "The release manifest is invalid: $Path. Download and extract the complete office ZIP again; keep all existing office files."
  }
}

function Assert-EntryFields($Entry) {
  foreach ($name in @('path', 'sha256', 'bytes')) {
    if ($null -eq $Entry -or $null -eq $Entry.PSObject.Properties[$name]) { throw 'A release manifest file entry is invalid. No existing records were replaced.' }
  }
}

function Verify-Payload([string]$Folder, [bool]$AllowData, [bool]$AllowLegacyInstalled = $false) {
  Assert-NoLinkedAncestors $Folder
  if (-not (Test-Path -LiteralPath $Folder -PathType Container)) { throw "Application folder is missing: $Folder" }
  $manifestPath = Join-Path $Folder 'release-manifest.json'
  Assert-NoLinkedAncestors $manifestPath
  if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "A valid release-manifest.json is required in $Folder. No existing files were replaced." }
  $manifest = Read-Manifest $manifestPath @('product', 'version', 'files') $AllowData
  $hasBuildIdentity = $null -ne $manifest.PSObject.Properties['build_identity']
  $hasSourceIdentity = $null -ne $manifest.PSObject.Properties['source_snapshot_sha256']
  # The authentic 0.3.2 format predates both fields and the BUILD_ID file.
  # This exception applies only to an existing installation, including rollback.
  # Never synthesize identities or accept this format as an incoming package.
  $legacy = $AllowData -and $AllowLegacyInstalled -and $manifest.version -ceq '0.3.2' -and
    -not $hasBuildIdentity -and -not $hasSourceIdentity
  if (-not $legacy) {
    $manifest = Read-Manifest $manifestPath @('product', 'version', 'build_identity', 'source_snapshot_sha256', 'files') $AllowData
    if (-not $manifest.build_identity -or $manifest.source_snapshot_sha256 -notmatch '^[a-fA-F0-9]{64}$') {
      throw 'Invalid Cathedra Faculty build identity. Keep the installed application and records; obtain a complete official release.'
    }
  }
  if ($manifest.product -cne 'faculty' -or $manifest.version -notmatch '^\d+\.\d+\.\d+$' -or
      -not @($manifest.files).Count) { throw 'Invalid Cathedra Faculty release manifest.' }
  $expected = @{}
  foreach ($entry in $manifest.files) {
    Assert-EntryFields $entry
    Assert-RelativeFile $entry.path
    if ($expected.ContainsKey($entry.path) -or $entry.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or
        ($entry.bytes -isnot [int] -and $entry.bytes -isnot [long]) -or $entry.bytes -lt 0) {
      throw "Invalid or duplicate manifest entry: $($entry.path)"
    }
    $full = Full-Path (Join-Path $Folder $entry.path)
    if (-not (Is-Within $full $Folder)) { throw 'The manifest contains a path outside the application folder.' }
    $expected[$entry.path] = $entry
  }
  $essentials = @('Cathedra Faculty.exe', '_internal/VERSION', '_internal/APP_PRODUCT',
      '_internal/frontend/dist/release-version.txt', '_internal/backend/cathedra-seed.db', 'desktop/protect-local-folder.ps1')
  if (-not $legacy) { $essentials += '_internal/BUILD_ID' }
  foreach ($essential in $essentials) {
    if (-not $expected.ContainsKey($essential)) { throw "The application manifest is incomplete: $essential" }
  }
  $found = @{}
  # These seven files were added outside the signed application payload in some
  # real 0.3.2 office installations. Permit them only on the recognized legacy
  # installed tree; incoming packages and modern installations remain strict.
  $legacySidecars = @(
    'OFFICE-UPDATE-VALIDATION.json',
    'START HERE - OFFICE SETUP.txt',
    'TRANSFER-VALIDATION.json',
    'docs/FACULTY_DESIGN_SYSTEM.md',
    'docs/redesign-dashboard.jpg',
    'docs/redesign-settings.jpg',
    'docs/redesign-sign-in.jpg'
  )
  foreach ($item in @(Get-SafeItems $Folder)) {
    $relative = Relative-Path $item.FullName $Folder
    if ($relative -match '^(?i:data)(/|$)') {
      if (-not $AllowData -or ($relative -eq 'data' -and -not $item.PSIsContainer)) { throw 'The public application package must not contain a runtime data folder.' }
      continue
    }
    if ($item.PSIsContainer) { continue }
    if ($relative -eq 'release-manifest.json') { continue }
    if (-not $expected.ContainsKey($relative) -or $found.ContainsKey($relative)) {
      if ($legacy -and -not $expected.ContainsKey($relative) -and $relative -cin $legacySidecars) { continue }
      throw "Unexpected application file: $relative"
    }
    $entry = $expected[$relative]
    if ($item.Length -ne $entry.bytes -or (File-Digest $item.FullName) -ne $entry.sha256) { throw "Application checksum failed: $relative" }
    $found[$relative] = $true
  }
  if ($found.Count -ne $expected.Count) { throw 'Application files are missing. Download and extract the complete ZIP again.' }
  if ((Get-Content -LiteralPath (Join-Path $Folder '_internal/VERSION') -Raw).Trim() -cne $manifest.version -or
      (Get-Content -LiteralPath (Join-Path $Folder '_internal/APP_PRODUCT') -Raw).Trim() -cne 'faculty' -or
      (Get-Content -LiteralPath (Join-Path $Folder '_internal/frontend/dist/release-version.txt') -Raw).Trim() -cne $manifest.version) {
    throw 'The application, frontend, and release manifest identities do not match.'
  }
  if (-not $legacy -and (Get-Content -LiteralPath (Join-Path $Folder '_internal/BUILD_ID') -Raw).Trim() -cne $manifest.build_identity) {
    throw 'The application build identity does not match its release manifest.'
  }
  return $manifest
}

function Verify-OfficePackage([string]$Folder, $Release) {
  $manifestPath = Join-Path $Folder 'office-release-manifest.json'
  Assert-NoLinkedAncestors $manifestPath
  if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'The office package manifest is missing. Extract the complete office ZIP again.' }
  $manifest = Read-Manifest $manifestPath @('product', 'version', 'build_identity', 'source_snapshot_sha256', 'source_commit', 'files')
  if ($manifest.product -cne 'faculty' -or $manifest.version -cne $Release.version -or
      $manifest.build_identity -cne $Release.build_identity -or $manifest.source_snapshot_sha256 -cne $Release.source_snapshot_sha256 -or
      $manifest.source_commit -notmatch '^[a-fA-F0-9]{40}$' -or -not @($manifest.files).Count) {
    throw 'The office package and application release identities do not match.'
  }
  $expected = @{}
  $rootFiles = @('Install-Office.ps1', 'Install-or-Update.cmd', 'OFFICE-READ-ME.txt')
  foreach ($entry in $manifest.files) {
    Assert-EntryFields $entry
    Assert-RelativeFile $entry.path $true
    if (($entry.path -cnotin $rootFiles -and -not $entry.path.StartsWith('Cathedra Faculty/', [StringComparison]::Ordinal)) -or
        $expected.ContainsKey($entry.path) -or $entry.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or
        ($entry.bytes -isnot [int] -and $entry.bytes -isnot [long]) -or $entry.bytes -lt 0) {
      throw "Invalid office package manifest entry: $($entry.path)"
    }
    $expected[$entry.path] = $entry
  }
  foreach ($essential in $rootFiles) {
    if (-not $expected.ContainsKey($essential)) { throw "The office package is incomplete: $essential" }
  }
  $found = @{}
  foreach ($item in @(Get-SafeItems $Folder)) {
    $relative = Relative-Path $item.FullName $Folder
    if ($item.PSIsContainer) {
      if ($relative -cne 'Cathedra Faculty' -and -not $relative.StartsWith('Cathedra Faculty/', [StringComparison]::Ordinal)) { throw "Unexpected office package folder: $relative" }
      continue
    }
    if ($relative -eq 'office-release-manifest.json') { continue }
    if (-not $expected.ContainsKey($relative) -or $found.ContainsKey($relative)) { throw "Unexpected office package file: $relative" }
    $entry = $expected[$relative]
    if ($item.Length -ne $entry.bytes -or (File-Digest $item.FullName) -ne $entry.sha256) { throw "Office package checksum failed: $relative" }
    $found[$relative] = $true
  }
  if ($found.Count -ne $expected.Count) { throw 'The office package is incomplete. Extract the complete office ZIP again.' }
}

function Tree-Snapshot([string]$Folder) {
  $snapshot = @{}
  foreach ($item in @(Get-SafeItems $Folder)) {
    $relative = Relative-Path $item.FullName $Folder
    $snapshot[$relative] = if ($item.PSIsContainer) { 'directory' } else { "$($item.Length):$(File-Digest $item.FullName)" }
  }
  return $snapshot
}

function Assert-SameTree($Expected, [string]$Folder) {
  $actual = Tree-Snapshot $Folder
  if ($actual.Count -ne $Expected.Count) { throw "Backup or data verification failed: $Folder" }
  foreach ($path in $Expected.Keys) {
    if (-not $actual.ContainsKey($path) -or $actual[$path] -ne $Expected[$path]) { throw "Backup or data verification failed: $path" }
  }
}

function Copy-Tree([string]$Source, [string]$Destination) {
  foreach ($item in @(Get-SafeItems $Source)) {
    $target = Join-Path $Destination (Relative-Path $item.FullName $Source)
    if ($item.PSIsContainer) { [IO.Directory]::CreateDirectory($target) | Out-Null; continue }
    [IO.Directory]::CreateDirectory((Split-Path -Parent $target)) | Out-Null
    if ($script:DataGuard -and $item.FullName -eq $script:GuardPath) {
      $output = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
      try { $script:DataGuard.Position = 0; $script:DataGuard.CopyTo($output) } finally { $output.Dispose(); $script:DataGuard.Position = 0 }
    } else { [IO.File]::Copy($item.FullName, $target, $false) }
  }
}

function Assert-AppClosed([string]$Folder) {
  foreach ($process in @(Get-Process -Name 'Cathedra Faculty' -ErrorAction SilentlyContinue)) {
    try { $executable = $process.Path } catch { throw 'Close all Cathedra Faculty windows before installing or updating.' }
    if (-not $executable -or (Is-Within (Full-Path $executable) $Folder)) {
      throw 'Cathedra Faculty is running. Use Exit Cathedra in the app, then run this installer again. No application or records were replaced.'
    }
  }
}

function Protect-Folder([string]$Folder) {
  & $script:Protector -Folder $Folder | Out-Null
}

function Test-Failure([string]$Point) {
  if ($TestMode -and $env:CATHEDRA_INSTALL_TEST_FAILPOINT -eq $Point) { throw "Installer test failure: $Point" }
}

function Move-RootItem([string]$Source, [string]$Destination) {
  if (Test-Path -LiteralPath $Source -PathType Container) { [IO.Directory]::Move($Source, $Destination) }
  else { [IO.File]::Move($Source, $Destination) }
}

try {
  $profileRoot = Full-Path $env:USERPROFILE
  $InstallFolder = Full-Path $InstallFolder
  $PackageFolder = Full-Path $PackageFolder
  if (-not (Is-Within $InstallFolder $profileRoot)) { throw 'Choose an installation folder inside your own Windows user profile.' }
  $testFixture = Split-Path -Parent $InstallFolder
  $testTemporaryRoot = Full-Path (Join-Path $env:LOCALAPPDATA 'Temp')
  $testBuildRoot = Full-Path (Join-Path $PSScriptRoot 'build')
  if ($TestMode -and (-not $NoLaunch -or (Split-Path -Leaf $testFixture) -notmatch '^cathedra-installer-test-[a-f0-9]{32}$' -or
      ((Full-Path (Split-Path -Parent $testFixture)) -ne $testTemporaryRoot -and (Full-Path (Split-Path -Parent $testFixture)) -ne $testBuildRoot))) {
    throw 'TestMode requires NoLaunch and a GUID-named cathedra-installer-test fixture inside your temporary folder.'
  }
  Assert-NoLinkedAncestors $InstallFolder
  Assert-NoLinkedAncestors $PackageFolder
  $source = if (Test-Path -LiteralPath (Join-Path $PackageFolder 'release-manifest.json') -PathType Leaf) { $PackageFolder } else { Full-Path (Join-Path $PackageFolder 'Cathedra Faculty') }
  if ($source -eq $InstallFolder -or (Is-Within $source $InstallFolder) -or (Is-Within $InstallFolder $source)) { throw 'The downloaded package and installed application must be separate folders.' }
  Write-Host 'Checking the complete Cathedra Faculty package...'
  $release = Verify-Payload $source $false
  if ($source -ne $PackageFolder) { Verify-OfficePackage $PackageFolder $release }
  $script:Protector = Join-Path $source 'desktop/protect-local-folder.ps1'
  $hash = [Security.Cryptography.SHA256]::Create()
  try { $key = ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($InstallFolder.ToLowerInvariant())))).Replace('-', '') } finally { $hash.Dispose() }
  $mutex = New-Object Threading.Mutex($false, "Local\CathedraFacultyInstaller-$key")
  try { $ownsMutex = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
  if (-not $ownsMutex) { throw 'Another Cathedra installer is already using this installation folder.' }
  $existing = Test-Path -LiteralPath $InstallFolder
  if ($existing) {
    Assert-AppClosed $InstallFolder
    $installed = Verify-Payload $InstallFolder $true $true
    if ($null -eq $installed.PSObject.Properties['build_identity']) {
      Write-Host 'Recognized the original Cathedra Faculty 0.3.2 format. All recorded application checksums passed.'
      Write-Host 'The complete old application and data will be backed up before updating. The old manifest will be kept unchanged.'
    }
    if ([version]$installed.version -gt [version]$release.version) { throw "A newer Cathedra $($installed.version) is installed. Installing an older version is blocked to protect your records." }
    $data = Join-Path $InstallFolder 'data'
    $hadData = Test-Path -LiteralPath $data -PathType Container
    if ($hadData) {
      $script:GuardPath = Join-Path $data '.cathedra.lock'
      $script:CreatedGuard = -not (Test-Path -LiteralPath $script:GuardPath)
      try {
        $script:DataGuard = [IO.File]::Open($script:GuardPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
        $script:DataGuard.Lock(0, 1)
      } catch {
        if ($script:DataGuard) { $script:DataGuard.Dispose(); $script:DataGuard = $null }
        throw 'The Cathedra data folder is in use. Close Cathedra on every window or account using these records and try again. No application or records were replaced.'
      }
      $originalData = Tree-Snapshot $data
    }
    Assert-AppClosed $InstallFolder
  }
  $parent = Split-Path -Parent $InstallFolder
  [IO.Directory]::CreateDirectory($parent) | Out-Null
  $leaf = Split-Path -Leaf $InstallFolder
  $identity = [guid]::NewGuid().ToString('N')
  $transaction = Join-Path $parent ('.' + $leaf + '-install-' + $identity)
  [IO.Directory]::CreateDirectory($transaction) | Out-Null
  Protect-Folder $transaction
  $newApp = Join-Path $transaction 'new-app'
  [IO.Directory]::CreateDirectory($newApp) | Out-Null
  Write-Host 'Preparing the new application...'
  Copy-Tree $source $newApp
  Verify-Payload $newApp $false | Out-Null
  Protect-Folder $newApp
  if ($existing) {
    $backup = Join-Path $parent ($leaf + '-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $identity.Substring(0, 8))
    [IO.Directory]::CreateDirectory($backup) | Out-Null
    Protect-Folder $backup
    Write-Host 'Saving a private recovery copy of your current application and records...'
    $before = Tree-Snapshot $InstallFolder
    Copy-Tree $InstallFolder $backup
    Assert-SameTree $before $backup
    Assert-SameTree $before $InstallFolder
    Protect-Folder $backup
    Assert-AppClosed $InstallFolder
    $oldApp = Join-Path $transaction 'old-app'
    [IO.Directory]::CreateDirectory($oldApp) | Out-Null
    $changedInstall = $true
    # Windows cannot rename an ancestor of an open lock file. Keep data rooted
    # and locked throughout replacement; retire only the verified app items.
    foreach ($item in @(Get-ChildItem -LiteralPath $InstallFolder -Force)) {
      if ($item.Name -eq 'data') { continue }
      Move-RootItem $item.FullName (Join-Path $oldApp $item.Name)
      $oldMoved.Add($item.Name)
      if ($oldMoved.Count -eq 1) { Test-Failure 'during-app-retirement' }
    }
    Test-Failure 'after-app-retirement'
    foreach ($item in @(Get-ChildItem -LiteralPath $newApp -Force)) {
      Move-RootItem $item.FullName (Join-Path $InstallFolder $item.Name)
      $newPromoted.Add($item.Name)
      if ($newPromoted.Count -eq 1) { Test-Failure 'during-promotion' }
    }
  } else {
    [IO.Directory]::Move($newApp, $InstallFolder)
    $changedInstall = $true
  }
  Test-Failure 'after-promotion'
  Verify-Payload $InstallFolder $true | Out-Null
  if ($hadData) { Assert-SameTree $originalData (Join-Path $InstallFolder 'data') }
  Protect-Folder $InstallFolder
  $succeeded = $true
  Write-Host "Cathedra Faculty $($release.version) is ready."
  Write-Host "Application: $InstallFolder\Cathedra Faculty.exe"
  if ($backup) { Write-Host "Recovery copy (keep this private): $backup" }
} catch {
  $failure = $_.Exception.Message
  if ($changedInstall) {
    try {
      if ($oldApp -and (Test-Path -LiteralPath $oldApp -PathType Container)) {
        $failedApp = Join-Path $transaction 'failed-app'
        [IO.Directory]::CreateDirectory($failedApp) | Out-Null
        foreach ($name in $newPromoted) { Move-RootItem (Join-Path $InstallFolder $name) (Join-Path $failedApp $name) }
        foreach ($name in $oldMoved) { Move-RootItem (Join-Path $oldApp $name) (Join-Path $InstallFolder $name) }
        Verify-Payload $InstallFolder $true $true | Out-Null
        Assert-SameTree $before $InstallFolder
        if ($hadData) { Assert-SameTree $originalData (Join-Path $InstallFolder 'data') }
        Write-Host 'Your previous application and records have been restored.'
      } elseif (-not $existing -and (Test-Path -LiteralPath $InstallFolder)) {
        [IO.Directory]::Move($InstallFolder, (Join-Path $transaction 'failed-app'))
      }
    } catch {
      $failure += " Rollback needs attention: $($_.Exception.Message). Keep both $transaction and $backup. Do not open Cathedra until recovery is complete."
      $transaction = $null # Never remove recovery evidence after a rollback failure.
    }
  }
  Write-Host "Installation stopped: $failure" -ForegroundColor Red
} finally {
  if ($script:DataGuard) { $script:DataGuard.Dispose() }
  if ($script:CreatedGuard -and $script:GuardPath -and (Test-Path -LiteralPath $script:GuardPath)) { Remove-Item -LiteralPath $script:GuardPath -Force }
  if ($transaction -and (Test-Path -LiteralPath $transaction)) {
    $resolvedTransaction = Full-Path $transaction
    if ((Is-Within $resolvedTransaction (Split-Path -Parent $InstallFolder)) -and (Split-Path -Leaf $resolvedTransaction).StartsWith('.' + (Split-Path -Leaf $InstallFolder) + '-install-')) {
      try { Remove-Item -LiteralPath $resolvedTransaction -Recurse -Force } catch { Write-Host "A temporary private folder remains: $resolvedTransaction" }
    }
  }
  if ($ownsMutex) { $mutex.ReleaseMutex() }
  if ($mutex) { $mutex.Dispose() }
}

if (-not $succeeded) { exit 1 }
if (-not $TestMode -and -not $NoLaunch) {
  try {
    $desktop = Full-Path ([Environment]::GetFolderPath('Desktop'))
    if (Is-Within $desktop $profileRoot) {
      $shell = New-Object -ComObject WScript.Shell
      $shortcut = $shell.CreateShortcut((Join-Path $desktop 'Cathedra Faculty.lnk'))
      $shortcut.TargetPath = Join-Path $InstallFolder 'Cathedra Faculty.exe'
      $shortcut.WorkingDirectory = $InstallFolder
      $shortcut.Save()
    }
  } catch { Write-Host 'The desktop shortcut could not be created. Open the application from the folder shown above.' }
}
if (-not $NoLaunch) {
  try { Start-Process -FilePath (Join-Path $InstallFolder 'Cathedra Faculty.exe') -WorkingDirectory $InstallFolder -WindowStyle Normal | Out-Null }
  catch { Write-Host 'Installation succeeded. Open Cathedra Faculty.exe from the application folder.' }
}
exit 0
