param(
  [Parameter(Mandatory = $true)]
  [string]$ReleaseFolder,
  [int]$Port = 0
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$product = (Get-Content -LiteralPath (Join-Path $root 'APP_PRODUCT') -Raw).Trim()
$applicationName = 'Cathedra Faculty'
$application = Join-Path $ReleaseFolder "$applicationName.exe"
$versionFile = Join-Path (Split-Path -Parent $PSScriptRoot) 'VERSION'

if (-not (Test-Path -LiteralPath $application)) {
  throw "Cathedra.exe was not found in $ReleaseFolder."
}
if (-not (Test-Path -LiteralPath $versionFile)) {
  throw 'The Cathedra VERSION file is missing.'
}

$expectedVersion = (Get-Content -LiteralPath $versionFile -Raw).Trim()
$frontendVersionFile = Join-Path $ReleaseFolder '_internal\frontend\dist\release-version.txt'
if (-not (Test-Path -LiteralPath $frontendVersionFile) -or (Get-Content -LiteralPath $frontendVersionFile -Raw).Trim() -ne $expectedVersion) {
  throw "Packaged frontend assets do not match Cathedra $expectedVersion."
}
$listener = $null
if ($Port -eq 0) {
  $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
  $listener.Start()
  $Port = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
  $listener.Stop()
}
$verificationDataDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("cathedra-release-" + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $verificationDataDirectory | Out-Null
$process = Start-Process -FilePath $application -ArgumentList '--no-browser', '--port', $Port, '--data-dir', $verificationDataDirectory -WindowStyle Hidden -PassThru

try {
  $deadline = (Get-Date).AddSeconds(120)
  $health = $null
  while ((Get-Date) -lt $deadline) {
    try {
      $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 2
      break
    } catch {
      Start-Sleep -Milliseconds 250
    }
  }

  if ($null -eq $health -or $health.status -ne 'ok' -or $health.release_version -ne $expectedVersion -or $health.product -ne $product) {
    $reportedVersion = if ($null -eq $health) { 'no response' } else { $health.release_version }
    throw "The packaged Cathedra application did not return the expected release health check. Expected $expectedVersion; received $reportedVersion."
  }
  $accountStatus = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/auth/status" -TimeoutSec 5
  if ($accountStatus.setup_required -ne $true) {
    throw 'The packaged Cathedra application did not start with a clean administrator setup.'
  }
  $databasePath = Join-Path $verificationDataDirectory 'cathedra.db'
  if (-not (Test-Path -LiteralPath $databasePath)) {
    throw 'The packaged Cathedra application did not create its isolated database.'
  }
  $frontend = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -TimeoutSec 5
  if ($frontend.StatusCode -ne 200 -or $frontend.Content -notmatch '<title>Cathedra</title>') {
    throw 'The packaged Cathedra application did not serve its frontend.'
  }
  $api = "http://127.0.0.1:$Port/api/v1"
  $password = [guid]::NewGuid().ToString('N') + '-test'
  $credentials = @{ username = 'release-check'; password = $password } | ConvertTo-Json
  $setupEntry = Get-ChildItem -LiteralPath $verificationDataDirectory -Directory -Filter '.setup-*' | ForEach-Object { Join-Path $_.FullName 'start.html' } | Where-Object { Test-Path -LiteralPath $_ } | Sort-Object { (Get-Item -LiteralPath $_).LastWriteTimeUtc } -Descending | Select-Object -First 1
  if (-not $setupEntry -or (Get-Content -LiteralPath $setupEntry -Raw) -notmatch '#setup-key=([A-Za-z0-9_-]{43})') { throw 'Private first-time setup entry is missing.' }
  $setupHeaders = @{ 'X-Cathedra-Setup-Key' = $Matches[1] }
  $session = Invoke-RestMethod -Method Post -Uri "$api/auth/setup" -Headers $setupHeaders -ContentType 'application/json' -Body $credentials
  $setupHeaders.Clear()
  $headers = @{ Authorization = "Bearer $($session.token)" }
  $facultyInput = @{
    name = 'Release Check Faculty'; rank = 'Instructor I'; employment_status = 'Full-time'
    college = 'CAS'; department = 'BSAM'
  } | ConvertTo-Json
  $faculty = Invoke-RestMethod -Method Post -Uri "$api/faculty-profiles" -Headers $headers -ContentType 'application/json' -Body $facultyInput
  $workloadInput = @{
    faculty_profile_id = $faculty.id; academic_year = '2026-2027'; term = 'First Semester'
    assignments = @(@{course_code='CHECK101'; course_title='Verification'; year_section='A'; lecture_hours=24; laboratory_hours=0})
  } | ConvertTo-Json -Depth 5
  $workload = Invoke-RestMethod -Method Post -Uri "$api/workloads" -Headers $headers -ContentType 'application/json' -Body $workloadInput
  if ($workload.overload_weekly_hours -ne 3) { throw 'Packaged workload calculation changed.' }
  $projection = Invoke-RestMethod -Uri "$api/expenses/monthly-projection?academic_year=2026-2027&term=First%20Semester&period=semester" -Headers $headers
  if ($projection.included_count -ne 1 -or $projection.teaching_details.Count -ne 1) {
    throw 'Packaged projection omitted the test faculty or workload.'
  }
  foreach ($kind in @('faculty-profiles', 'workloads')) {
    $export = Invoke-WebRequest -Uri "$api/maintenance/exports/$kind.csv" -Headers $headers
    if ($export.StatusCode -ne 200) { throw "Packaged $kind export failed." }
  }
  $removedResponse = Invoke-WebRequest -Uri "$api/fsdp" -Headers $headers -SkipHttpErrorCheck
  if ($removedResponse.StatusCode -ne 404) { throw 'Retired feature endpoint is still available.' }
  $backup = Invoke-RestMethod -Method Post -Uri "$api/maintenance/backups" -Headers $headers
  $restore = Invoke-RestMethod -Method Post -Uri "$api/maintenance/restore" -Headers $headers -ContentType 'application/json' -Body (@{filename=$backup.filename} | ConvertTo-Json)
  if (-not $restore.safety_backup) { throw 'Packaged restore did not retain a safety backup.' }
  $session = Invoke-RestMethod -Method Post -Uri "$api/auth/login" -ContentType 'application/json' -Body $credentials
  $headers.Authorization = "Bearer $($session.token)"
  $retained = Invoke-RestMethod -Uri "$api/workloads/$($workload.id)" -Headers $headers
  if ($retained.overload_weekly_hours -ne 3) { throw 'Packaged restore changed the saved workload.' }
  Invoke-RestMethod -Method Post -Uri "$api/desktop/exit" -Headers $headers | Out-Null
  $process.WaitForExit(10000) | Out-Null
} finally {
  if (-not $process.HasExited) {
    Stop-Process -Id $process.Id -Force
  }
  $resolvedVerification = [System.IO.Path]::GetFullPath($verificationDataDirectory)
  $temporaryRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
  if ($resolvedVerification.StartsWith($temporaryRoot, [System.StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $resolvedVerification).StartsWith('cathedra-release-')) {
    Remove-Item -LiteralPath $resolvedVerification -Recurse -Force -ErrorAction SilentlyContinue
  }
}

Write-Host "Release verification passed for Cathedra $expectedVersion."
