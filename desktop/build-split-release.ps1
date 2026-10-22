param(
  [string]$Python = (Join-Path (Split-Path -Parent $PSScriptRoot) 'backend/.venv/Scripts/python.exe'),
  [string]$Node = 'node',
  [string]$ReleaseRoot = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$product = (Get-Content -LiteralPath (Join-Path $root 'APP_PRODUCT') -Raw).Trim()
if ($product -ne 'faculty') { throw 'Configure Cathedra Faculty before packaging.' }
$name = 'Cathedra Faculty'
$frontend = Join-Path $root 'frontend'
$seed = Join-Path $PSScriptRoot 'build/seed/cathedra-seed.db'
& $Python (Join-Path $PSScriptRoot 'release_inventory.py')
if ($LASTEXITCODE -ne 0) { throw 'Locked backend dependency verification failed.' }
$sourceHash = & $Python (Join-Path $PSScriptRoot 'release_inventory.py') --source-hash
if ($LASTEXITCODE -ne 0) { throw 'Source identity capture failed.' }
& $Python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency compatibility failed.' }
$oldData = $env:CATHEDRA_DATA_DIR
$runIdentity = [guid]::NewGuid().ToString('N')
$version = (Get-Content -LiteralPath (Join-Path $root 'VERSION') -Raw).Trim()
Set-Content -LiteralPath (Join-Path $root 'BUILD_ID') -Value "$version-$runIdentity" -Encoding utf8 -NoNewline
if (-not $ReleaseRoot) { $ReleaseRoot = Join-Path $PSScriptRoot "release/$version-$runIdentity" }
if (Test-Path -LiteralPath (Join-Path $ReleaseRoot $name)) { throw 'Choose a new release folder; existing packages are immutable.' }
$env:CATHEDRA_DATA_DIR = Join-Path $PSScriptRoot "build/test-data-$runIdentity"
$supportingSources = @((Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.py' -File).FullName)
$privateTools = Join-Path $root 'tools'
if (Test-Path -LiteralPath $privateTools -PathType Container) {
  $supportingSources += @((Get-ChildItem -LiteralPath $privateTools -Filter '*.py' -File).FullName)
}
$privateMaintenance = Join-Path $root 'backend/maintenance_target.py'
if (Test-Path -LiteralPath $privateMaintenance -PathType Leaf) {
  $supportingSources += $privateMaintenance
}
& $Python -m ruff check --config (Join-Path $root 'backend/pyproject.toml') @supportingSources
if ($LASTEXITCODE -ne 0) { throw 'Desktop and recovery-tool static checks failed.' }
& $Python -m ruff format --check --config (Join-Path $root 'backend/pyproject.toml') @supportingSources
if ($LASTEXITCODE -ne 0) { throw 'Desktop and recovery-tool formatting failed.' }
Push-Location (Join-Path $root 'backend')
try {
  & $Python -m pytest -q -p no:cacheprovider --basetemp (Join-Path $PSScriptRoot "build/pytest-temp-$runIdentity")
  if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
  & $Python -m ruff check app tests create_install_seed.py
  if ($LASTEXITCODE -ne 0) { throw 'Backend static checks failed.' }
} finally { Pop-Location; $env:CATHEDRA_DATA_DIR = $oldData }
Push-Location $frontend
try {
  & $Node 'node_modules/eslint/bin/eslint.js' src
  if ($LASTEXITCODE -ne 0) { throw 'Frontend lint failed.' }
  & $Node --no-experimental-webstorage 'node_modules/vitest/vitest.mjs' run --config vitest.config.ts --configLoader runner
  if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }
  & $Node 'node_modules/typescript/bin/tsc' -p tsconfig.tests.json
  if ($LASTEXITCODE -ne 0) { throw 'Test typecheck failed.' }
  & $Node 'node_modules/typescript/bin/tsc' -b
  if ($LASTEXITCODE -ne 0) { throw 'TypeScript failed.' }
  & $Node 'node_modules/vite/bin/vite.js' build --configLoader runner
  if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
& $Python (Join-Path $root 'backend/create_install_seed.py') $seed
if ($LASTEXITCODE -ne 0) { throw 'Clean seed verification failed.' }
& $Python -m PyInstaller --noconfirm --clean --noconsole --onedir --name $name --distpath $ReleaseRoot --workpath (Join-Path $PSScriptRoot 'build/pyinstaller') --specpath $PSScriptRoot --paths (Join-Path $root 'backend') --add-data "$(Join-Path $frontend 'dist');frontend/dist" --add-data "$seed;backend" --add-data "$(Join-Path $root 'VERSION');." --add-data "$(Join-Path $root 'APP_PRODUCT');." --add-data "$(Join-Path $root 'BUILD_ID');." --add-data "$(Join-Path $root 'docs/GOOGLE_SHEETS_SETUP.md');docs" (Join-Path $PSScriptRoot 'run_cathedra.py')
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
$packageDesktop = Join-Path $ReleaseRoot "$name/desktop"
New-Item -ItemType Directory -Path $packageDesktop -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'protect-local-folder.ps1'), (Join-Path $PSScriptRoot 'Prepare-Office-Copy.cmd') -Destination $packageDesktop
& (Join-Path $PSScriptRoot 'verify-release.ps1') -ReleaseFolder (Join-Path $ReleaseRoot $name)
if (-not $?) { throw 'Packaged smoke check failed.' }
& $Python (Join-Path $PSScriptRoot 'write_third_party_notices.py') (Join-Path $ReleaseRoot $name)
if ($LASTEXITCODE -ne 0) { throw 'Third-party notice generation failed.' }
$finalSourceHash = & $Python (Join-Path $PSScriptRoot 'release_inventory.py') --source-hash
if ($LASTEXITCODE -ne 0 -or $sourceHash -ne $finalSourceHash) { throw 'Source changed during verification or packaging. Rebuild in a fresh destination.' }
& $Python (Join-Path $PSScriptRoot 'release_inventory.py') (Join-Path $ReleaseRoot $name)
if ($LASTEXITCODE -ne 0) { throw 'Release inventory failed.' }

