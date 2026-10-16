param([Parameter(Mandatory = $true)][string]$Folder)
$ErrorActionPreference = 'Stop'
$resolved = (Resolve-Path -LiteralPath $Folder).ProviderPath
if (-not (Test-Path -LiteralPath $resolved -PathType Container)) { throw 'Choose an application or backup folder.' }
if ($resolved.TrimEnd('\') -eq [IO.Path]::GetPathRoot($resolved).TrimEnd('\')) { throw 'A drive root cannot be protected by this script.' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
$allowed = @($identity.Value, 'S-1-5-18', 'S-1-5-32-544')
$items = @((Get-Item -LiteralPath $resolved)) + @(Get-ChildItem -LiteralPath $resolved -Recurse -Force -ErrorAction Stop)
foreach ($item in $items) {
  if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Do not use linked folders in a portable release.' }
}
& icacls.exe $resolved /grant:r "*$($identity.Value):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /Q | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not grant authorized Windows access.' }
& icacls.exe $resolved /inheritance:r /Q | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not remove broad inherited Windows access.' }
foreach ($rule in (Get-Acl -LiteralPath $resolved).Access) {
  $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
  if ($sid -notin $allowed) {
    & icacls.exe $resolved /remove:g "*$sid" /remove:d "*$sid" /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not remove an unauthorized Windows access rule.' }
  }
}
foreach ($child in Get-ChildItem -LiteralPath $resolved -Force) {
  & icacls.exe $child.FullName /reset /T /Q | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Could not protect $($child.FullName)." }
}
foreach ($item in $items) {
  foreach ($rule in (Get-Acl -LiteralPath $item.FullName).Access) {
    $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    if ($sid -notin $allowed -or $rule.AccessControlType -ne 'Allow') { throw "Unexpected access rule on $($item.FullName)" }
  }
}
Write-Output 'Private Windows permissions verified for the current Windows user, SYSTEM, and Administrators.'
