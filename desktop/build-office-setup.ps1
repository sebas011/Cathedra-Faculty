param(
  [Parameter(Mandatory = $true)][string]$OfficeDownloadFolder,
  [string]$Python = (Join-Path (Split-Path -Parent $PSScriptRoot) 'backend/.venv/Scripts/python.exe')
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
$version = (Get-Content -LiteralPath (Join-Path $root 'VERSION') -Raw).Trim()
$output = (Get-Item -LiteralPath $OfficeDownloadFolder -Force).FullName
if ((Get-Item -LiteralPath $output).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Choose a plain download folder.' }
$wrapper = Get-Content -LiteralPath (Join-Path $output 'office-release-manifest.json') -Raw | ConvertFrom-Json
$commit = (& git -C $root rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Source commit could not be resolved.' }
$changes = & git -C $root status --porcelain --untracked-files=normal -- backend frontend desktop VERSION APP_PRODUCT
if ($LASTEXITCODE -ne 0 -or $changes) { throw 'Commit the release sources before building setup.' }
$assetName = "Cathedra-Faculty-$version-Windows-x64.zip"
$archive = Join-Path $output $assetName
if ($wrapper.product -ne 'faculty' -or $wrapper.version -ne $version -or $wrapper.source_commit -ne $commit -or
    $wrapper.asset -ne $assetName -or $wrapper.release_tag -notmatch ('^v' + [regex]::Escape($version) + '-office\.[1-9]\d*$')) {
  throw 'The office ZIP does not match the current release source.'
}
$zipHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ((Get-Content -LiteralPath "$archive.sha256" -Raw).Trim() -cne "$zipHash  $assetName") { throw 'The office ZIP checksum failed.' }
$sourceHash = & $Python (Join-Path $PSScriptRoot 'release_inventory.py') --source-hash
if ($LASTEXITCODE -ne 0 -or "$sourceHash".Trim() -ne $wrapper.source_snapshot_sha256) { throw 'Source changed after the verified application build.' }
$setupName = 'Cathedra-Faculty-Setup.exe'
$setupPath = Join-Path $output $setupName
if ((Test-Path -LiteralPath $setupPath) -or (Test-Path -LiteralPath "$setupPath.sha256")) { throw 'Existing setup downloads are immutable; choose a fresh download folder.' }
$buildParent = Join-Path $PSScriptRoot 'build/office-setup'
[IO.Directory]::CreateDirectory($buildParent) | Out-Null
$stage = Join-Path $buildParent ([guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($stage) | Out-Null
try {
  $bundledArchive = Join-Path $stage 'office-package.zip'
  Copy-Item -LiteralPath $archive -Destination $bundledArchive
  if ((Get-FileHash -LiteralPath $bundledArchive -Algorithm SHA256).Hash.ToLowerInvariant() -cne $zipHash) { throw 'The bundled office ZIP changed.' }
  $metadataPath = Join-Path $stage 'setup-metadata.json'
  [ordered]@{
    product = 'faculty'; version = $version; source_commit = $commit; release_tag = $wrapper.release_tag
    build_identity = $wrapper.build_identity; source_snapshot_sha256 = $wrapper.source_snapshot_sha256
    zip_sha256 = $zipHash
  } | ConvertTo-Json | Set-Content -LiteralPath $metadataPath -Encoding utf8
  & $Python -m PyInstaller --noconfirm --clean --onefile --noconsole --name 'Cathedra-Faculty-Setup' --distpath $output --workpath (Join-Path $stage 'pyinstaller') --specpath $stage --add-data "$bundledArchive;." --add-data "$metadataPath;." (Join-Path $PSScriptRoot 'office_setup.py')
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $setupPath -PathType Leaf)) { throw 'Single-file setup packaging failed.' }
  $after = & $Python (Join-Path $PSScriptRoot 'release_inventory.py') --source-hash
  if ($LASTEXITCODE -ne 0 -or "$after".Trim() -ne "$sourceHash".Trim()) { throw 'Source changed during setup packaging.' }
  $setupHash = (Get-FileHash -LiteralPath $setupPath -Algorithm SHA256).Hash.ToLowerInvariant()
  "$setupHash  $setupName" | Set-Content -LiteralPath "$setupPath.sha256" -Encoding ascii
  Write-Host "Single-file setup ready: $setupPath"
} finally {
  $resolvedStage = [IO.Path]::GetFullPath($stage)
  $resolvedParent = [IO.Path]::GetFullPath($buildParent).TrimEnd('\')
  if ($resolvedStage.StartsWith($resolvedParent + '\', [StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $resolvedStage) -match '^[0-9a-f]{32}$') {
    Remove-Item -LiteralPath $resolvedStage -Recurse -Force
  }
}
