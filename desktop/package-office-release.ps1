param(
  [Parameter(Mandatory = $true)]
  [string]$VerifiedReleaseFolder,
  [Parameter(Mandatory = $true)]
  [string]$OutputFolder,
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^[0-9a-fA-F]{40}$')]
  [string]$SourceCommit,
  [string]$ReleaseTag = '',
  [string]$Python = (Join-Path (Split-Path -Parent $PSScriptRoot) 'backend/.venv/Scripts/python.exe')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
$applicationName = 'Cathedra Faculty'
$version = (Get-Content -LiteralPath (Join-Path $root 'VERSION') -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'VERSION must contain a numeric application version.' }
if ($ReleaseTag -and $ReleaseTag -notmatch ('^v' + [regex]::Escape($version) + '-office\.[1-9]\d*$')) {
  throw 'The release tag must match VERSION, for example v0.3.3-office.1.'
}
if ((Get-Content -LiteralPath (Join-Path $root 'APP_PRODUCT') -Raw).Trim() -ne 'faculty') {
  throw 'Only Cathedra Faculty can be packaged here.'
}
$actualCommit = & git -C $root rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or "$actualCommit".Trim() -ne $SourceCommit) {
  throw 'SourceCommit must identify the current source checkout.'
}
function Assert-CleanSource {
  $changes = & git -C $root status --porcelain --untracked-files=normal -- backend frontend desktop VERSION APP_PRODUCT
  if ($LASTEXITCODE -ne 0 -or $changes) {
    throw 'Commit the release sources before packaging so SourceCommit identifies the verified source.'
  }
}
Assert-CleanSource

function Assert-PlainDirectory([string]$Path) {
  $directory = Get-Item -LiteralPath $Path -Force
  if (-not $directory.PSIsContainer -or ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw "A plain directory is required: $Path"
  }
}

function Get-PlainFiles([string]$Folder) {
  Assert-PlainDirectory $Folder
  $pending = [Collections.Generic.Stack[string]]::new()
  $pending.Push($Folder)
  while ($pending.Count) {
    foreach ($entry in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
      if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Release files must not contain links or junctions: $($entry.FullName)"
      }
      $relative = $entry.FullName.Substring($Folder.Length + 1).Replace('\', '/')
      if ($relative -match '(^|/)(data|backups?|exports?|restore-staging|tests?|node_modules|\.git|__pycache__|\.setup-[^/]*|test-data[^/]*|pytest[^/]*)(/|$)') {
        throw "Office data or test artifacts must not enter a release: $relative"
      }
      if ($entry.PSIsContainer) { $pending.Push($entry.FullName); continue }
      if ($relative -match '(?i)\.(db|sqlite|sqlite3|csv|xlsx?|bak|backup|log|pem|key|pfx)(-|$)' -and $relative -notin @('_internal/backend/cathedra-seed.db', '_internal/certifi/cacert.pem')) {
        throw "Office data or private files must not enter a release: $relative"
      }
      $entry
    }
  }
}

function Assert-RelativeFile([string]$Path) {
  if (-not $Path -or $Path.Contains('\') -or $Path.Contains(':') -or $Path -match '(^/|//|(^|/)\.{1,2}(/|$)|[\x00-\x1f])') {
    throw "Unsafe manifest path: $Path"
  }
  foreach ($component in $Path.Split('/')) {
    if ($component -match '[<>"|?*]' -or $component.EndsWith('.') -or $component.EndsWith(' ') -or $component -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') {
      throw "Unsafe Windows filename in manifest: $Path"
    }
  }
}

$release = (Get-Item -LiteralPath $VerifiedReleaseFolder -Force).FullName.TrimEnd('\', '/')
Assert-PlainDirectory $release
$manifestPath = Join-Path $release 'release-manifest.json'
$releaseFiles = @(Get-PlainFiles $release)
$buildManifestRecord = @{ sha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash; bytes = (Get-Item -LiteralPath $manifestPath).Length }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.product -ne 'faculty' -or $manifest.version -ne $version -or -not $manifest.build_identity.StartsWith("$version-")) {
  throw 'The verified build manifest does not match this product and version.'
}
$sourceHash = & $Python (Join-Path $PSScriptRoot 'release_inventory.py') --source-hash
if ($LASTEXITCODE -ne 0 -or $manifest.source_snapshot_sha256 -ne "$sourceHash".Trim()) {
  throw 'The source changed since the verified build. Create a fresh build before packaging.'
}
$expected = [Collections.Generic.Dictionary[string, object]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($file in $manifest.files) {
  Assert-RelativeFile $file.path
  if ($file.path -eq 'release-manifest.json' -or $expected.ContainsKey($file.path) -or $file.sha256 -notmatch '^[0-9a-fA-F]{64}$' -or [long]$file.bytes -lt 0) {
    throw "Invalid or duplicate build manifest entry: $($file.path)"
  }
  $expected.Add($file.path, $file)
}
foreach ($required in @('Cathedra Faculty.exe', '_internal/backend/cathedra-seed.db', '_internal/VERSION', '_internal/APP_PRODUCT', '_internal/BUILD_ID', '_internal/frontend/dist/release-version.txt', '_internal/frontend/dist/build-id.txt', 'desktop/protect-local-folder.ps1', 'THIRD_PARTY_NOTICES.txt')) {
  if (-not $expected.ContainsKey($required)) { throw "The verified release is missing $required." }
}
if ($releaseFiles.Count -ne $expected.Count + 1) { throw 'Release files differ from the verified build manifest.' }
foreach ($file in $releaseFiles) {
  $relative = $file.FullName.Substring($release.Length + 1).Replace('\', '/')
  Assert-RelativeFile $relative
  if ($relative -eq 'release-manifest.json') { continue }
  if (-not $expected.ContainsKey($relative)) { throw "Unlisted release file: $relative" }
  $record = $expected[$relative]
  if ($file.Length -ne [long]$record.bytes -or (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -ne $record.sha256) {
    throw "The verified release file changed: $relative"
  }
}
if ((Get-Content -LiteralPath (Join-Path $release '_internal/VERSION') -Raw).Trim() -ne $version -or
    (Get-Content -LiteralPath (Join-Path $release '_internal/APP_PRODUCT') -Raw).Trim() -ne 'faculty' -or
    (Get-Content -LiteralPath (Join-Path $release '_internal/BUILD_ID') -Raw).Trim() -ne $manifest.build_identity -or
    (Get-Content -LiteralPath (Join-Path $release '_internal/frontend/dist/build-id.txt') -Raw).Trim() -ne $manifest.build_identity -or
    (Get-Content -LiteralPath (Join-Path $release '_internal/frontend/dist/release-version.txt') -Raw).Trim() -ne $version) {
  throw 'Packaged application identity differs from its build manifest.'
}

# Python is a build-machine check only; the office installer needs no Python.
$seedCheck = @'
import sqlite3
import sys
from pathlib import Path

seed = Path(sys.argv[1]).resolve()
with sqlite3.connect(seed.as_uri() + "?mode=ro", uri=True) as database:
    if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("The installation seed failed its integrity check.")
    if database.execute("SELECT id, product FROM cathedra_product").fetchall() != [(1, "faculty")]:
        raise SystemExit("The installation seed has an unexpected product identity.")
    tables = database.execute("SELECT name FROM sqlite_schema WHERE type='table'").fetchall()
    allowed = {"schema_migrations", "cathedra_product", "sqlite_sequence"}
    for (table,) in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        if table not in allowed and database.execute("SELECT COUNT(*) FROM " + quoted).fetchone()[0]:
            raise SystemExit("The installation seed contains office or account records.")
'@
$seedCheck | & $Python - (Join-Path $release '_internal/backend/cathedra-seed.db')
if ($LASTEXITCODE -ne 0) { throw 'The installation database is not a verified empty seed.' }

$output = [IO.Path]::GetFullPath($OutputFolder).TrimEnd('\', '/')
if ($output -eq $release -or $output.StartsWith($release + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
  throw 'The output folder must be outside the verified release.'
}
if (Test-Path -LiteralPath $output) {
  Assert-PlainDirectory $output
  if (@(Get-ChildItem -LiteralPath $output -Force).Count) { throw 'Choose a new or empty output folder; existing downloads are immutable.' }
} else { New-Item -ItemType Directory -Path $output | Out-Null }
$stage = Join-Path $output ('.package-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
$assetName = "Cathedra-Faculty-$version-Windows-x64.zip"
$archive = Join-Path $output $assetName
try {
  $appStage = Join-Path $stage $applicationName
  New-Item -ItemType Directory -Path $appStage | Out-Null
  foreach ($file in $releaseFiles) {
    $relative = $file.FullName.Substring($release.Length + 1)
    $destination = Join-Path $appStage $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $destination
  }
  foreach ($name in @('Install-Office.ps1', 'Install-or-Update.cmd', 'OFFICE-READ-ME.txt')) {
    $file = Get-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Force
    if ($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "A plain installer file is required: $name" }
    Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $stage $name)
  }
  $downloadFiles = @(
    Get-ChildItem -LiteralPath $stage -Recurse -Force -File | Sort-Object FullName | ForEach-Object {
      [ordered]@{ path = $_.FullName.Substring($stage.Length + 1).Replace('\', '/'); sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); bytes = $_.Length }
    }
  )
  foreach ($file in $downloadFiles) {
    if (-not $file.path.StartsWith("$applicationName/")) { continue }
    $relative = $file.path.Substring($applicationName.Length + 1)
    $record = if ($relative -eq 'release-manifest.json') {
      $buildManifestRecord
    } else { $expected[$relative] }
    if ($file.sha256 -ne $record.sha256 -or $file.bytes -ne $record.bytes) {
      throw "A release file changed while being copied: $relative"
    }
  }
  $finalSourceHash = & $Python (Join-Path $PSScriptRoot 'release_inventory.py') --source-hash
  if ($LASTEXITCODE -ne 0 -or "$finalSourceHash".Trim() -ne "$sourceHash".Trim()) { throw 'Source changed while packaging. Try again from a fresh verified build.' }
  Assert-CleanSource
  $downloadManifest = [ordered]@{
    product = 'faculty'; version = $version; platform = 'Windows-x64'
    source_commit = $SourceCommit.ToLowerInvariant(); release_tag = $ReleaseTag
    build_identity = $manifest.build_identity; source_snapshot_sha256 = $manifest.source_snapshot_sha256
    asset = $assetName; files = $downloadFiles
  }
  $downloadManifestPath = Join-Path $stage 'office-release-manifest.json'
  $downloadManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $downloadManifestPath -Encoding utf8
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  [IO.Compression.ZipFile]::CreateFromDirectory($stage, $archive, [IO.Compression.CompressionLevel]::Optimal, $false)
  $checksum = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
  "$checksum  $assetName" | Set-Content -LiteralPath (Join-Path $output "$assetName.sha256") -Encoding ascii
  Copy-Item -LiteralPath $downloadManifestPath -Destination (Join-Path $output 'office-release-manifest.json')
  Copy-Item -LiteralPath (Join-Path $stage 'OFFICE-READ-ME.txt') -Destination (Join-Path $output 'OFFICE-READ-ME.txt')
} finally {
  $resolvedStage = [IO.Path]::GetFullPath($stage)
  if ($resolvedStage.StartsWith($output + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $resolvedStage) -match '^\.package-[0-9a-f]{32}$') {
    Remove-Item -LiteralPath $resolvedStage -Recurse -Force
  }
}
Write-Host "Office download created: $archive"
