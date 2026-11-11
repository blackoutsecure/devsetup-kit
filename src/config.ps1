<#
.SYNOPSIS
    Loads the dev-setup config and provides safe lookup and reporting helpers.
.DESCRIPTION
    Dot-source this file, then call Get-DevSetupConfig once and read values with
    Get-DevSetupValue. Every lookup takes a fallback, so a config file that is
    missing keys degrades to the built-in default instead of failing the run.

    $DevSetupRoot is the repository root, resolved from this file's location, so
    callers in src/scripts/ and in the root both work without hardcoding paths.
#>

$DevSetupRoot = Split-Path -Parent $PSScriptRoot
$DevSetupConfigPath = Join-Path $DevSetupRoot "config\dev-setup.config.json"

function Get-DevSetupConfig {
    param([string]$Path)

    if (-not $Path) { $Path = $DevSetupConfigPath }
    if (-not (Test-Path $Path)) {
        Write-Warning "Config file not found at $Path. Using built-in defaults."
        return [pscustomobject]@{}
    }

    try {
        return Get-Content $Path -Raw | ConvertFrom-Json
    } catch {
        throw "Config file $Path is not valid JSON: $($_.Exception.Message)"
    }
}

function Get-DevSetupValue {
    param(
        $Config,
        [string]$Key,
        $Default = $null
    )

    $node = $Config
    foreach ($segment in $Key.Split(".")) {
        if ($null -eq $node) { return $Default }
        $property = $node.PSObject.Properties[$segment]
        if (-not $property) { return $Default }
        $node = $property.Value
    }

    # Treat null and empty string as "not set" so blank config entries fall back.
    if ($null -eq $node) { return $Default }
    if ($node -is [string] -and $node -eq "") { return $Default }
    return $node
}

function Expand-DevSetupPath {
    param([string]$Value)

    if (-not $Value) { return $Value }
    return [Environment]::ExpandEnvironmentVariables($Value)
}

function Get-DevSetupStringList {
    param($Config, [string]$Key, [string[]]$Default = @())

    $node = $Config
    foreach ($segment in $Key.Split(".")) {
        $property = if ($null -ne $node) { $node.PSObject.Properties[$segment] } else { $null }
        if (-not $property) { return $Default }
        $node = $property.Value
    }
    if ($null -eq $node -or ($node -is [string] -and $node -eq "")) { return $Default }
    if ($node -isnot [array]) { throw "$Key must be an array of non-empty strings." }
    foreach ($value in $node) {
        if ($value -isnot [string] -or -not $value.Trim() -or $value -match '[\r\n]') {
            throw "$Key must be an array of non-empty, single-line strings."
        }
    }
    $node | Select-Object -Unique
}

function Find-DevSetupRustExecutable {
    param([Parameter(Mandatory)][string]$Name)

    $command = Get-Command "$Name.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    $cargoHome = if ($env:CARGO_HOME) { $env:CARGO_HOME } else { Join-Path $env:USERPROFILE ".cargo" }
    $candidate = Join-Path $cargoHome "bin\$Name.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
}

function ConvertTo-DevSetupHashtable {
    <# PSCustomObject from ConvertFrom-Json -> hashtable, for iteration. #>
    param($Value)

    $result = [ordered]@{}
    if ($null -eq $Value) { return $result }
    foreach ($property in $Value.PSObject.Properties) {
        $result[$property.Name] = $property.Value
    }
    return $result
}

function Test-DevSetupElevated {
    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        try {
            $principal = New-Object Security.Principal.WindowsPrincipal($identity)
            return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        } finally {
            $identity.Dispose()
        }
    }
    $userId = & id -u
    if ($LASTEXITCODE -ne 0) { throw "Cannot determine the current execution identity." }
    return "$userId" -eq "0"
}

function Assert-DevSetupExecutionMode {
    param([switch]$ReadOnly)

    $adminMode = $env:DEVSETUP_ADMIN_MODE
    if ($adminMode -and $adminMode -notin @("0", "1")) {
        throw "DEVSETUP_ADMIN_MODE must be 0 (standard user, the default) or 1 (explicit admin opt-in)."
    }
    if (-not (Test-DevSetupElevated)) { return }
    if ($ReadOnly) {
        Write-DevSetupStatus warn "Execution mode" "elevated read-only inspection; run write operations from a standard, non-admin shell"
    } elseif ($adminMode -eq "1") {
        Write-DevSetupStatus warn "Execution mode" "explicit admin mode enabled; child processes inherit elevation; installation scope remains per-user"
    } else {
        throw "Run this script from a standard, non-admin shell. To explicitly permit an already-elevated shell for this run, set DEVSETUP_ADMIN_MODE=1. No automatic elevation or de-elevation is performed."
    }
}

function Write-DevSetupStatus {
    <#
    .SYNOPSIS
        One audit line per component so a run reads as a report.
    .DESCRIPTION
        found   - already present, nothing to do
        install - something is about to change
        skip    - disabled in config, or not applicable on this platform
        warn    - proceeded, but the result is degraded
        update  - a newer version is available (reported only, never applied automatically)
        remove  - uninstalled, only reachable via -Uninstall
    #>
    param(
        [Parameter(Mandatory)][ValidateSet("found", "install", "skip", "warn", "update", "remove")][string]$State,
        [Parameter(Mandatory)][string]$Component,
        [string]$Detail = ""
    )

    $color = switch ($State) {
        "found"   { "Green" }
        "install" { "Cyan" }
        "skip"    { "DarkGray" }
        "warn"    { "Yellow" }
        "update"  { "Magenta" }
        "remove"  { "Red" }
    }
    Write-Host ("  {0,-9} " -f "[$State]") -ForegroundColor $color -NoNewline
    Write-Host ("{0,-24} {1}" -f $Component, $Detail)

    # DEVSETUP_STATUS_LOG lets the top-level runner tally every line, including
    # ones emitted by configure-vscode.py in a separate process later in the run.
    if ($env:DEVSETUP_STATUS_LOG) {
        Add-Content -Path $env:DEVSETUP_STATUS_LOG -Value "$State|$Component|$Detail"
    }
}

function Write-DevSetupSummary {
    <#
    .SYNOPSIS
        Prints one total per status tag for the whole run.
    .DESCRIPTION
        Reads the log written by every Write-DevSetupStatus call this run (including
        from configure-vscode.py), so the summary reflects every step, not just the
        ones setup.ps1 called directly. In -Audit runs, also recommends whether to
        run the real setup, lists what it would change, and gives the exact command.
    #>
    param([string]$LogPath, [switch]$Audit, [string]$ApplyCommand = ".\setup.ps1")

    $counts = [ordered]@{ found = 0; install = 0; skip = 0; warn = 0; update = 0; remove = 0 }
    $pending = @()
    if ($LogPath -and (Test-Path $LogPath)) {
        foreach ($line in Get-Content $LogPath) {
            $parts = $line -split '\|', 3
            $state = $parts[0]
            if (-not $counts.Contains($state)) { continue }
            $counts[$state]++
            if ($Audit -and $state -eq "install") {
                $component = if ($parts.Count -gt 1) { $parts[1] } else { "" }
                $detail = if ($parts.Count -gt 2) { $parts[2] } else { "" }
                $pending += "$component`: $detail"
            }
        }
    }

    $installLabel = if ($Audit) { "would install" } else { "installed" }
    $warnLabel = if ($counts.warn -eq 1) { "warning" } else { "warnings" }
    $summaryLine = "Summary: $($counts.found) found, $($counts.install) $installLabel, $($counts.skip) skipped, $($counts.warn) $warnLabel"
    if ($counts.update -gt 0) { $summaryLine += ", $($counts.update) update$(if ($counts.update -ne 1) { 's' }) available" }
    if ($counts.remove -gt 0) { $summaryLine += ", $($counts.remove) removed" }
    Write-Host ""
    Write-Host $summaryLine

    Write-Host ""
    Write-Host ("=" * 78) -ForegroundColor DarkCyan
    Write-Host "  RESULTS REPORT" -ForegroundColor Cyan
    Write-Host ("=" * 78) -ForegroundColor DarkCyan
    if ($LogPath -and (Test-Path $LogPath)) {
        foreach ($line in Get-Content $LogPath) {
            $parts = $line -split '\|', 3
            if ($parts.Count -ge 2) {
                $detail = if ($parts.Count -eq 3) { " - $($parts[2])" } else { "" }
                $color = switch ($parts[0]) {
                    "found"   { "Green" }
                    "install" { "Cyan" }
                    "skip"    { "DarkGray" }
                    "warn"    { "Yellow" }
                    "update"  { "Magenta" }
                    "remove"  { "Red" }
                    default   { "White" }
                }
                Write-Host ("  [{0}]" -f $parts[0]) -ForegroundColor $color -NoNewline
                Write-Host (" {0,-24} {1}" -f $parts[1], $detail)
            }
        }
    } else {
        Write-Host "  No status entries were recorded."
    }

    if ($Audit) {
        Write-Host ""
        Write-Host ("=" * 78) -ForegroundColor DarkCyan
        Write-Host "  RECOMMENDATION" -ForegroundColor Cyan
        Write-Host ("=" * 78) -ForegroundColor DarkCyan
        Write-Host ""
        if ($pending.Count -eq 0) {
            Write-Host "  STATUS: No changes needed." -ForegroundColor Green
            Write-Host "  The environment already matches config/dev-setup.config.json."
            Write-Host "  No further action is required."
        } else {
            Write-Host "  STATUS: $($pending.Count) change(s) pending." -ForegroundColor Yellow
            Write-Host "  The following actions would run without -Audit:"
            for ($index = 0; $index -lt $pending.Count; $index++) {
                Write-Host ("    {0}. [install]" -f ($index + 1)) -ForegroundColor Cyan -NoNewline
                Write-Host (" {0}" -f $pending[$index])
            }
            Write-Host ""
            Write-Host "  APPLY: $ApplyCommand" -ForegroundColor Cyan
        }
        if ($counts.warn -gt 0) {
            Write-Host ""
            Write-Host "  ATTENTION: $($counts.warn) item(s) need attention." -ForegroundColor Yellow
            Write-Host "  Review the [warn] entries in the results report above."
        }
    }

    Write-Host ""
    Write-Host ""
    Write-Host ("-" * 78) -ForegroundColor DarkCyan
    Write-Host "  END OF REPORT" -ForegroundColor Cyan
    Write-Host ("-" * 78) -ForegroundColor DarkCyan
    Write-Host ""
    Write-Host ""
}

function Get-DevSetupVSCodeProfilePath {
    <# Resolved settings.json paths for the profiles named in user.vscode.profiles. #>
    param($Config, [string]$Platform = "windows")

    $names = Get-DevSetupValue $Config "user.vscode.profiles" @("stable", "insiders")
    $dirs = ConvertTo-DevSetupHashtable (Get-DevSetupValue $Config "advanced.vscode.profileDirectories.$Platform")

    foreach ($name in $names) {
        if (-not $dirs.Contains($name)) { continue }
        $settingsPath = Join-Path (Expand-DevSetupPath $dirs[$name]) "settings.json"
        if (Test-Path $settingsPath) {
            [pscustomobject]@{ Name = $name; Path = $settingsPath }
        }
    }
}

function Set-DevSetupVSCodeSetting {
    <#
    .SYNOPSIS
        Write one setting into every configured VS Code profile, skipping no-ops.
    .DESCRIPTION
        Used for the machine-local paths that only the platform installers can
        resolve. Bulk settings are handled by src/configure-vscode.py instead.
    #>
    param($Config, [Parameter(Mandatory)][string]$Key, [Parameter(Mandatory)]$Value)

    foreach ($vscodeProfile in Get-DevSetupVSCodeProfilePath $Config) {
        $settings = Get-Content $vscodeProfile.Path -Raw | ConvertFrom-Json
        $property = $settings.PSObject.Properties[$Key]
        if ($property -and $property.Value -eq $Value) {
            Write-DevSetupStatus found "vscode" "$Key already correct ($($vscodeProfile.Name))"
            continue
        }
        if ($property) { $property.Value = $Value }
        else { $settings | Add-Member -MemberType NoteProperty -Name $Key -Value $Value }
        ($settings | ConvertTo-Json -Depth 20) | Set-Content $vscodeProfile.Path
        Write-DevSetupStatus install "vscode" "$Key -> $Value ($($vscodeProfile.Name))"
    }
}

function Add-DevSetupUserPath {
    <#
    .SYNOPSIS
        Add a directory to the user-level PATH, once.
    .DESCRIPTION
        Compares whole PATH entries. A substring test would both miss paths
        containing PowerShell wildcard characters and wrongly treat
        C:\Python314 as present when only C:\Python314\Scripts is.
    #>
    param([Parameter(Mandatory)][string]$Directory, [switch]$Prepend, [switch]$Audit)

    if (-not $Audit -and -not (Test-Path $Directory)) { return }

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $target = $Directory.TrimEnd("\")
    $entries = @($userPath -split ";" | Where-Object { $_ } | ForEach-Object { $_.Trim().TrimEnd("\") })
    if ($entries -contains $target) { return }

    if ($Audit) {
        Write-DevSetupStatus install "PATH" "would add $Directory to the user PATH"
        return
    }

    $updated = if ($Prepend) { "$Directory;$userPath" } else { "$userPath;$Directory" }
    [Environment]::SetEnvironmentVariable("Path", $updated, "User")
    Write-DevSetupStatus install "PATH" "added $Directory to the user PATH"
}

function Update-DevSetupSessionPath {
    <# Refreshes $env:Path for this process after an installer (winget) updates PATH out-of-process. #>
    $env:Path = (@(
        $env:Path,
        [Environment]::GetEnvironmentVariable("Path", "Machine"),
        [Environment]::GetEnvironmentVariable("Path", "User")
    ) | Where-Object { $_ }) -join ";"
}

function Find-DevSetupWingetExecutable {
    <#
    .SYNOPSIS
        Get-Command lookup, falling back to configured WinGet package-install glob paths.
    .DESCRIPTION
        Shared by installers whose tool isn't reliably added to PATH by WinGet
        (install-php.ps1, install-shellcheck.ps1). $DefaultPaths entries may
        contain a {wingetPackageId} placeholder.
    #>
    param($Config, [Parameter(Mandatory)][string]$ExeName, [Parameter(Mandatory)][string]$ConfigKey,
        [Parameter(Mandatory)][string]$PackageId, [string[]]$DefaultPaths)

    $command = Get-Command $ExeName -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
    if ($command) { return $command }

    $configuredPaths = Get-DevSetupValue $Config $ConfigKey $DefaultPaths
    $configuredPaths |
        ForEach-Object { Expand-DevSetupPath ($_ -replace '\{wingetPackageId\}', $PackageId) } |
        ForEach-Object { Get-ChildItem $_ -File -ErrorAction SilentlyContinue } |
        Select-Object -First 1 -ExpandProperty FullName
}

function Install-DevSetupWingetTool {
    <#
    .SYNOPSIS
        Shared single-package WinGet install pattern.
    .DESCRIPTION
        Used by install-php.ps1, install-powershell.ps1, and install-shellcheck.ps1,
        which differ only in component name, package ID, and how the executable is
        located. $Find is called before and (if installing) after the WinGet run.
    #>
    param(
        [Parameter(Mandatory)][string]$Component,
        [Parameter(Mandatory)][string]$PackageId,
        [Parameter(Mandatory)][scriptblock]$Find,
        [Parameter(Mandatory)][string]$ManualInstallHint,
        [string[]]$VersionArgs = @("--version"),
        [scriptblock]$FallbackInstall,
        [string]$FallbackDescription = "an official checksum-verified ZIP in the user profile",
        [switch]$Audit,
        [switch]$CheckUpgrades
    )

    $exe = & $Find

    if ($Audit) {
        if ($exe) {
            Write-DevSetupStatus found $Component "$(& $exe @VersionArgs | Select-Object -First 1) at $exe"
            if ($CheckUpgrades) { Test-DevSetupWingetUpgrade -Component $Component -PackageId $PackageId }
        } elseif (Get-Command winget.exe -ErrorAction SilentlyContinue) {
            Write-DevSetupStatus install $Component "would install $PackageId via winget"
        } elseif ($FallbackInstall) {
            Write-DevSetupStatus install $Component "would install $FallbackDescription"
        } else {
            Write-DevSetupStatus warn $Component "missing and winget is unavailable"
        }
        return $exe
    }

    if (-not $exe) {
        if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
            if (-not $FallbackInstall) {
                throw "$Component is unavailable and winget is not installed. $ManualInstallHint"
            }
        } else {
            Write-DevSetupStatus install $Component "installing $PackageId via winget (per-user, no admin, no GUI)"
            & winget.exe install --id $PackageId -e --scope user --accept-package-agreements --accept-source-agreements --silent --disable-interactivity | Out-Host
            if ($LASTEXITCODE -ne 0) {
                if (-not $FallbackInstall) {
                    throw "winget failed to install $PackageId (exit code $LASTEXITCODE), and a per-user install may not be supported for this package. $ManualInstallHint"
                }
                Write-DevSetupStatus warn $Component "user-scoped WinGet install failed; trying $FallbackDescription instead"
            }
            Update-DevSetupSessionPath
            $exe = & $Find
        }
        if (-not $exe -and $FallbackInstall) {
            $exe = & $FallbackInstall
        }
    }
    if (-not $exe) { throw "$Component setup completed but the executable was not found. Open a new terminal and run setup again." }

    Write-DevSetupStatus found $Component "$(& $exe @VersionArgs | Select-Object -First 1) at $exe"
    if ($CheckUpgrades) { Test-DevSetupWingetUpgrade -Component $Component -PackageId $PackageId }
    return $exe
}

function Install-DevSetupPortableRuntime {
    param(
        [Parameter(Mandatory)]$Config,
        [Parameter(Mandatory)][ValidateSet("node", "powershell", "githubCli")][string]$Tool,
        [string]$InstallDirectory,
        $ReleaseMetadata
    )

    $defaultDir = switch ($Tool) {
        "node" { "%LOCALAPPDATA%\Programs\nodejs" }
        "powershell" { "%LOCALAPPDATA%\Programs\PowerShell" }
        "githubCli" { "%LOCALAPPDATA%\Programs\GitHub CLI" }
    }
    if (-not $InstallDirectory) {
        $InstallDirectory = Get-DevSetupValue $Config "advanced.$Tool.portableInstallDir" $defaultDir
    }
    $installDir = [IO.Path]::GetFullPath((Expand-DevSetupPath $InstallDirectory))
    $userRoot = [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\') + '\'
    if (-not $installDir.StartsWith($userRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Portable $Tool must be installed below the user profile, not $installDir."
    }
    $exeName = switch ($Tool) {
        "node" { "node.exe" }
        "powershell" { "pwsh.exe" }
        "githubCli" { "bin\gh.exe" }
    }
    $exe = Join-Path $installDir $exeName
    $binDir = Split-Path -Parent $exe
    if (Test-Path $exe) {
        Add-DevSetupUserPath $binDir -Prepend
        return $exe
    }
    if (Test-Path $installDir) {
        throw "Portable destination $installDir already exists without $exeName; inspect it manually. Nothing was overwritten."
    }
    $architecture = if ("$env:PROCESSOR_ARCHITECTURE $env:PROCESSOR_ARCHITEW6432" -match "ARM64") { "arm64" } elseif ([Environment]::Is64BitOperatingSystem) { "x64" } else { "x86" }
    if ($Tool -eq "node") {
        $baseUrl = Get-DevSetupValue $Config "advanced.node.portableBaseUrl" "https://nodejs.org/dist"
        $releases = Invoke-RestMethod -Uri "$baseUrl/index.json" -TimeoutSec 30
        $release = $releases | Where-Object { $_.lts } | Select-Object -First 1
        if (-not $release -or $release.files -notcontains "win-$architecture-zip") {
            throw "The current Node.js LTS has no ZIP for Windows $architecture. No older, potentially unsupported runtime was selected."
        }
        $archiveRoot = "node-$($release.version)-win-$architecture"
        $assetName = "$archiveRoot.zip"
        $url = "$baseUrl/$($release.version)/$assetName"
        $checksums = (Invoke-WebRequest -Uri "$baseUrl/$($release.version)/SHASUMS256.txt" -UseBasicParsing -TimeoutSec 30).Content
        $hashLine = $checksums -split "\r?\n" | Where-Object { $_ -match ("^[a-fA-F0-9]{64}\s+\*?" + [regex]::Escape($assetName) + "$") } | Select-Object -First 1
        if (-not $hashLine) { throw "Official Node.js checksums do not include $assetName." }
        $expectedHash = ($hashLine -split '\s+')[0]
    } else {
        $defaultApi = if ($Tool -eq "powershell") { "https://api.github.com/repos/PowerShell/PowerShell/releases/latest" } else { "https://api.github.com/repos/cli/cli/releases/latest" }
        $releaseApi = Get-DevSetupValue $Config "advanced.$Tool.portableReleaseApiUrl" $defaultApi
        $release = if ($ReleaseMetadata) { $ReleaseMetadata } else { Invoke-RestMethod -Uri $releaseApi -TimeoutSec 30 }
        $version = $release.tag_name -replace '^v', ''
        if ($Tool -eq "powershell") {
            $assetName = "PowerShell-$version-win-$architecture.zip"
        } else {
            $cliArchitecture = switch ($architecture) { "x64" { "amd64" }; "x86" { "386" }; default { $architecture } }
            $assetName = "gh_${version}_windows_$cliArchitecture.zip"
        }
        $asset = $release.assets | Where-Object { $_.name -eq $assetName } | Select-Object -First 1
        if (-not $asset -or $asset.digest -notmatch '^sha256:([a-fA-F0-9]{64})$') {
            throw "Official $Tool release metadata has no checksum-verified $assetName."
        }
        $expectedHash = $Matches[1]
        $url = $asset.browser_download_url
        $archiveRoot = ""
    }
    $parent = Split-Path -Parent $installDir
    New-Item -Path $parent -ItemType Directory -Force | Out-Null
    $stage = Join-Path $parent (".devsetup-{0}" -f [guid]::NewGuid())
    New-Item -Path $stage -ItemType Directory | Out-Null
    try {
        $archive = Join-Path $stage "runtime.zip"
        Write-DevSetupStatus install $Tool "downloading official $assetName to user-local staging (deadline 600s)"
        Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing -TimeoutSec 600
        $actualHash = (Get-FileHash -Path $archive -Algorithm SHA256).Hash
        if ($actualHash -ne $expectedHash) { throw "SHA256 verification failed for $assetName. Nothing was installed." }
        $expanded = Join-Path $stage "expanded"
        Expand-Archive -Path $archive -DestinationPath $expanded
        $source = if ($archiveRoot) { Join-Path $expanded $archiveRoot } else { $expanded }
        if (-not (Test-Path (Join-Path $source $exeName))) {
            throw "$assetName does not contain the expected $exeName. Nothing was installed."
        }
        Move-Item -Path $source -Destination $installDir
    } finally {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
    Add-DevSetupUserPath $binDir -Prepend
    Write-DevSetupStatus install $Tool "installed official portable runtime to $installDir; start a new terminal yourself when ready"
    return $exe
}

function Test-DevSetupWingetUpgrade {
    <#
    .SYNOPSIS
        Reports (never applies) whether winget has a newer version of an installed package.
    .DESCRIPTION
        Silent when winget is unavailable or the tool is already current. Upgrading
        is left to the user; this script never applies an upgrade automatically.
    #>
    param([Parameter(Mandatory)][string]$Component, [Parameter(Mandatory)][string]$PackageId)

    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { return }
    $output = & winget.exe upgrade --disable-interactivity 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-DevSetupStatus warn $Component "could not query available WinGet upgrades (exit code $LASTEXITCODE)"
        return
    }
    $row = $output | Where-Object { $_ -match ("(^|\s)" + [regex]::Escape($PackageId) + "(\s|$)") } | Select-Object -First 1
    if ($row) {
        $installedVersion = "unknown"
        $availableVersion = "unknown"
        if ($row) {
            $columns = @($row -split '\s{2,}' | Where-Object { $_ })
            if ($columns.Count -ge 4) {
                $installedVersion = $columns[$columns.Count - 3]
                $availableVersion = $columns[$columns.Count - 2]
            }
        }
        Write-DevSetupStatus update $Component "newer version available: installed $installedVersion, latest $availableVersion (run: winget upgrade --id $PackageId)"
    }
}

function Uninstall-DevSetupWingetTool {
    <#
    .SYNOPSIS
        Removes a WinGet-managed tool. Only ever called when -Uninstall is passed explicitly.
    #>
    param([Parameter(Mandatory)][string]$Component, [Parameter(Mandatory)][string]$PackageId, [switch]$Audit)

    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        Write-DevSetupStatus warn $Component "winget is unavailable; cannot uninstall"
        return
    }
    if ($Audit) {
        Write-DevSetupStatus remove $Component "would uninstall user-scoped $PackageId via winget; machine installations are left alone"
        return
    }
    & winget.exe uninstall --id $PackageId -e --scope user --accept-source-agreements --silent --disable-interactivity
    if ($LASTEXITCODE -eq 0) {
        Write-DevSetupStatus remove $Component "uninstalled $PackageId via winget"
    } else {
        Write-DevSetupStatus warn $Component "not installed via winget, or uninstall failed (exit $LASTEXITCODE)"
    }
}

function Get-DevSetupGitCredentialSetting {
    <# The git config keys/values this setup owns on Windows. #>
    param($Config)

    @(
        [pscustomobject]@{
            Key = "credential.helper"
            Value = (Get-DevSetupValue $Config "advanced.git.credential.windows.helper" "manager")
            ReplaceAll = $true
        },
        [pscustomobject]@{
            Key = "credential.credentialStore"
            Value = (Get-DevSetupValue $Config "advanced.git.credential.windows.credentialStore" "wincredman")
            ReplaceAll = $false
        },
        [pscustomobject]@{
            # git expects lowercase true/false, not PowerShell's True/False.
            Key = "credential.guiPrompt"
            Value = "$(Get-DevSetupValue $Config 'advanced.git.credential.windows.guiPrompt' $false)".ToLowerInvariant()
            ReplaceAll = $false
        }
    )
}

function Write-DevSetupGitIdentityStatus {
    <# Reports identity state the same way in audit and apply runs. #>
    param($Config, [string]$GitExe, [switch]$Audit)

    $configured = Get-DevSetupValue $Config "user.git.userEmail"
    $current = (& $GitExe config --global --get user.email 2>$null)

    if ($configured) {
        $verb = if ($Audit) { "would apply" } else { "applied" }
        Write-DevSetupStatus install "identity" "$verb $configured from config"
    } elseif ($current) {
        Write-DevSetupStatus found "identity" "already set to $current"
    } else {
        Write-DevSetupStatus warn "identity" "not set; fill user.git.userName / user.git.userEmail"
    }
}
