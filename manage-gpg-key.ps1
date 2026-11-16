<#
.SYNOPSIS
    Manage GPG signing keys using native pinentry and encrypted backups.
.DESCRIPTION
    This opt-in helper delegates to the shared Python implementation. Run
    -Audit first. Passphrases are entered only in GnuPG's pinentry dialog.
#>
param(
    [switch]$Audit,
    [switch]$List,
    [switch]$Generate,
    [switch]$Verify,
    [switch]$Cache,
    [switch]$GithubCheck,
    [switch]$GithubPublish,
    [switch]$VSCodeSigning,
    [string]$Export,
    [string]$Import,
    [string]$Remove,
    [string]$Default,
    [string[]]$Key,
    [string]$KeyName,
    [string]$KeyEmail,
    [string]$Title,
    [securestring]$KeyPassphrase,
    [securestring]$ZipPassword
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "src\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit

if ($KeyPassphrase -or $ZipPassword) {
    throw "Passphrase arguments are no longer supported. Enter passphrases in GnuPG's native pinentry prompt."
}

$python = $null
foreach ($candidate in @((Join-Path $PSScriptRoot ".venv\Scripts\python.exe"), "python3", "python")) {
    $command = Get-Command $candidate -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) {
        & $command.Source -c "import sys; sys.exit(sys.version_info < (3, 10))"
        if ($LASTEXITCODE -eq 0) { $python = $command.Source; break }
    }
}
if (-not $python) { throw "Python 3.10 or later is required; run setup first." }

$arguments = @()
if ($Audit) { $arguments += "--audit" }
if ($List) { $arguments += "--list" }
if ($Generate) { $arguments += "--generate" }
if ($Verify) { $arguments += "--verify" }
if ($Cache) { $arguments += "--cache" }
if ($GithubCheck) { $arguments += "--github-check" }
if ($GithubPublish) { $arguments += "--github-publish" }
if ($VSCodeSigning) { $arguments += "--vscode-signing" }
if ($Export) { $arguments += @("--export", $Export) }
if ($Import) { $arguments += @("--import", $Import) }
if ($Remove) { $arguments += @("--remove", $Remove) }
if ($Default) { $arguments += @("--default", $Default) }
foreach ($item in $Key) { $arguments += @("--key", $item) }
if ($KeyName) { $arguments += @("--key-name", $KeyName) }
if ($KeyEmail) { $arguments += @("--key-email", $KeyEmail) }
if ($Title) { $arguments += @("--title", $Title) }

& $python (Join-Path $PSScriptRoot "src\manage-gpg-key.py") @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
