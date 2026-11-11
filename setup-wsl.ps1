<#
.SYNOPSIS
    Audits or configures the default user for an existing WSL distribution.
.DESCRIPTION
    This optional helper is separate from setup.ps1 because it changes the
    selected Linux distribution. It never installs WSL or a distribution.
#>
param(
    [string]$Distribution,
    [ValidatePattern("^[a-z_][a-z0-9_-]*$")]
    [string]$UserName,
    [switch]$Audit,
    [switch]$Configure,
    [switch]$EnablePasswordlessSudo,
    [switch]$RestartDistribution
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "src\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:($Audit -or -not $Configure)

if (($EnablePasswordlessSudo -or $RestartDistribution) -and -not $Configure) {
    throw "-EnablePasswordlessSudo and -RestartDistribution require -Configure and apply only to this run."
}
if ($UserName -eq "root") {
    throw "-UserName must be a non-root user."
}

function Invoke-Wsl {
    param([string[]]$Arguments)

    $output = & wsl.exe @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "wsl.exe $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return $output
}

function Invoke-WslRootScript {
    param([string]$Script, [string]$TargetUser)

  $output = $Script | & wsl.exe -d $Distribution -u root -- bash -s -- $TargetUser 2>&1
    if ($LASTEXITCODE -ne 0) {
    throw "WSL configuration failed: $($output -join [Environment]::NewLine)"
    }
}

function Test-WslCommand {
  param([string[]]$Arguments)

  & wsl.exe @Arguments 2>$null | Out-Null
  return $LASTEXITCODE -eq 0
}

function Get-WslUserState {
  param([string[]]$BaseArguments, [string]$Name)

  $problems = @()
  $userId = (Invoke-Wsl ($BaseArguments + @("--exec", "id", "-u")) | Select-Object -Last 1).Trim()
  $entry = (Invoke-Wsl ($BaseArguments + @("--exec", "getent", "passwd", $Name)) | Select-Object -Last 1).Trim()
  $fields = $entry -split ":", 7
  $homeDirectory = if ($fields.Count -eq 7) { $fields[5] } else { "" }
  $shell = if ($fields.Count -eq 7) { $fields[6] } else { "" }

  if ($Name -eq "root" -or $userId -eq "0") { $problems += "default user is root" }
  if ($fields.Count -ne 7 -or $fields[0] -ne $Name) { $problems += "passwd entry is missing" }
  if (-not $homeDirectory -or -not (Test-WslCommand ($BaseArguments + @("--exec", "test", "-d", $homeDirectory)))) { $problems += "home directory is missing" }
  elseif (-not (Test-WslCommand ($BaseArguments + @("--exec", "test", "-w", $homeDirectory)))) { $problems += "home directory is not writable" }
  if (-not $shell -or -not (Test-WslCommand ($BaseArguments + @("--exec", "test", "-x", $shell)))) { $problems += "login shell is unavailable" }
  if ($EnablePasswordlessSudo -and -not (Test-WslCommand ($BaseArguments + @("--exec", "sudo", "-n", "true")))) { $problems += "passwordless sudo is unavailable" }

  return [pscustomobject]@{
    Name = $Name
    UserId = $userId
    HomeDirectory = $homeDirectory
    Shell = $shell
    Problems = $problems
    MeetsCriteria = $problems.Count -eq 0
  }
}

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    Write-DevSetupStatus skip "WSL" "wsl.exe is not installed"
    exit 0
}

$distributions = @(Invoke-Wsl @("--list", "--quiet") | Where-Object { $_.Trim() })
if ($distributions.Count -eq 0) {
    Write-DevSetupStatus skip "WSL" "no distributions are installed"
    exit 0
}

if ($Distribution -and $distributions -notcontains $Distribution) {
    throw "WSL distribution '$Distribution' is not installed. Available: $($distributions -join ', ')"
}

$wslArguments = @()
if ($Distribution) { $wslArguments += @("-d", $Distribution) }
$currentUser = (Invoke-Wsl ($wslArguments + @("--exec", "whoami")) | Select-Object -Last 1).Trim()
$target = if ($Distribution) { $Distribution } else { "the default distribution" }
$currentUserState = Get-WslUserState $wslArguments $currentUser

if ($currentUserState.MeetsCriteria) {
  Write-DevSetupStatus found "WSL" "$target starts as $currentUser with a writable home and login shell"
    exit 0
}

if (-not $Configure -or $Audit) {
  $mode = if ($Audit) { "would configure" } else { "run with -Configure -UserName <name> to configure" }
  Write-DevSetupStatus warn "WSL" "$target is not ready: $($currentUserState.Problems -join '; '); $mode a non-root default user"
    exit 0
}

if (-not $UserName) {
  if ($currentUser -eq "root") {
    throw "-Configure requires -UserName <name> when the default WSL user is root."
  }
  $UserName = $currentUser
}

if ($RestartDistribution -and -not $Distribution) {
    throw "-RestartDistribution requires -Distribution <name>; other distributions will not be stopped."
}

$rootArguments = @()
if ($Distribution) { $rootArguments += @("-d", $Distribution) }
$rootArguments += @("-u", "root", "--exec", "id", "-u", $UserName)
$userExists = Test-WslCommand $rootArguments
if ($userExists) {
  Write-DevSetupStatus found "WSL" "$UserName already exists; configuring its default-user setting"
} else {
  Write-DevSetupStatus install "WSL" "creating $UserName in $target"
}
$configurationScript = @'
set -euo pipefail
user_name="$1"
if ! id -u "$user_name" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$user_name"
fi
'@
if ($EnablePasswordlessSudo) {
    Write-DevSetupStatus warn "WSL" "passwordless sudo explicitly enabled for $UserName for this run"
    $configurationScript += @'

printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$user_name" > "/etc/sudoers.d/$user_name"
chmod 0440 "/etc/sudoers.d/$user_name"
visudo -cf "/etc/sudoers.d/$user_name"
'@
}
$configurationScript += @'

config_file=/etc/wsl.conf
temp_file="$(mktemp)"
if [ -f "$config_file" ]; then
  awk -v user="$user_name" '
    BEGIN { in_user = 0; seen_user = 0; wrote_default = 0 }
    /^[[:space:]]*\[user\][[:space:]]*$/ {
      if (in_user && !wrote_default) print "default=" user
      in_user = 1; seen_user = 1; wrote_default = 0; print; next
    }
    /^[[:space:]]*\[/ {
      if (in_user && !wrote_default) print "default=" user
      in_user = 0
    }
    in_user && /^[[:space:]]*default[[:space:]]*=/ {
      if (!wrote_default) print "default=" user
      wrote_default = 1; next
    }
    { print }
    END {
      if (in_user && !wrote_default) print "default=" user
      if (!seen_user) print "[user]\ndefault=" user
    }
  ' "$config_file" > "$temp_file"
else
  printf '[user]\ndefault=%s\n' "$user_name" > "$temp_file"
fi
cat "$temp_file" > "$config_file"
rm -f "$temp_file"
'@
Invoke-WslRootScript $configurationScript $UserName

if (-not $RestartDistribution) {
    Write-DevSetupStatus warn "WSL" "default-user configuration written; restart pending. VS Code and all terminals remain open. Save Linux work, then manually terminate $target when ready and reopen it to verify the default user. To authorize a targeted restart on a future run, pass -Configure -Distribution <name> -RestartDistribution."
    return
}

Write-DevSetupStatus warn "WSL" "explicit restart override: terminating only $Distribution; its active Linux processes will end"
Invoke-Wsl @("--terminate", $Distribution) | Out-Null
$verifyArguments = @()
if ($Distribution) { $verifyArguments += @("-d", $Distribution) }
$verifiedUser = (Invoke-Wsl ($verifyArguments + @("--exec", "whoami")) | Select-Object -Last 1).Trim()
if ($verifiedUser -ne $UserName) {
    throw "WSL still starts as $verifiedUser; expected $UserName."
}
$verifiedState = Get-WslUserState $verifyArguments $verifiedUser
if (-not $verifiedState.MeetsCriteria) {
  throw "WSL user $verifiedUser is not ready: $($verifiedState.Problems -join '; ')"
}
Write-DevSetupStatus found "WSL" "$target starts as $verifiedUser with a writable home and login shell"
