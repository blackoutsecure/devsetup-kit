<#
.SYNOPSIS
    Optional helper to generate, export, or import a GPG signing identity for Git.
.DESCRIPTION
    Separate from setup.ps1 because it changes real state: a new secret key in your
    GPG keyring and your global git signing config (user.signingkey, commit.gpgsign,
    tag.gpgsign). Nothing here runs as part of the main setup flow.

    -Export bundles the public/secret key into a single archive encrypted with GPG's
    symmetric cipher (AES-256), so the "zip" this produces is password protected
    without adding a dependency on a third-party archiver. -Import reverses that.

    Requires gpg on PATH; run .\setup.ps1 first if it's missing.

    KeyPassphrase/ZipPassword are SecureString; plaintext is only materialized
    transiently to satisfy gpg.exe's --passphrase argument, which has no
    SecureString equivalent. A linter may still flag the parameter names.
#>
param(
    [switch]$Audit,
    [switch]$Generate,
    [string]$Export,
    [string]$Import,
    [securestring]$KeyPassphrase,
    [securestring]$ZipPassword,
    [string]$KeyName,
    [string]$KeyEmail
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "src\config.ps1")
Assert-DevSetupExecutionMode -ReadOnly:$Audit
$config = Get-DevSetupConfig

function ConvertFrom-DevSetupSecureString {
    <# Plaintext is only ever materialized right before gpg/file output needs it. #>
    param([securestring]$Secure)

    if (-not $Secure) { return $null }
    return [System.Net.NetworkCredential]::new("", $Secure).Password
}

function New-DevSetupRandomSecret {
    <# 24 random bytes, base64url-ish (strip characters that upset shells/batch files). #>
    [OutputType([securestring])]
    param()

    $bytes = [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(24)
    $plain = ([Convert]::ToBase64String($bytes) -replace '[+/=]', '').Substring(0, 24)
    return (ConvertTo-SecureString -String $plain -AsPlainText -Force)
}

function Get-DevSetupGpgExe {
    $configuredGpg = & git config --global --get gpg.program 2>$null
    if ($configuredGpg -and (Test-Path $configuredGpg)) {
        return (Resolve-Path $configuredGpg).Path
    }

    $gpg = Get-Command gpg.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
    if (-not $gpg) {
        throw "gpg.exe was not found. Run .\setup.ps1 first so PortableGit's user-local GPG is configured."
    }
    return $gpg
}

function Set-DevSetupGitSigningKey {
    param([string]$GpgExe, [string]$KeyId)

    & git config --global user.signingkey $KeyId
    & git config --global commit.gpgsign true
    & git config --global tag.gpgsign true
    & git config --global gpg.program $GpgExe
    Write-DevSetupStatus install "GPG key" "git configured to sign commits/tags with $KeyId"
}

function Get-DevSetupSigningKeyId {
    <# The key ID git is currently configured to sign with, if any. #>
    (& git config --global --get user.signingkey 2>$null)
}

if ($Audit) {
    try {
        $gpg = Get-DevSetupGpgExe
    } catch {
        Write-DevSetupStatus warn "GPG key" $_.Exception.Message
        return
    }
    Write-DevSetupStatus found "GPG key" "using $gpg"
    $signingKey = Get-DevSetupSigningKeyId
    if ($signingKey) {
        Write-DevSetupStatus found "GPG key" "git signs commits/tags with $signingKey"
    } else {
        Write-DevSetupStatus install "GPG key" "no signing key configured; run -Generate or -Import"
    }
    if ($Generate) { Write-DevSetupStatus install "GPG key" "would generate a new key and configure git to sign with it" }
    if ($Export) { Write-DevSetupStatus install "GPG key" "would export the current signing key to $Export" }
    if ($Import) { Write-DevSetupStatus install "GPG key" "would import a key from $Import and configure git to sign with it" }
    return
}

if (-not ($Generate -or $Export -or $Import)) {
    throw "Nothing to do. Pass -Generate, -Export <path>, and/or -Import <path>."
}

$gpg = Get-DevSetupGpgExe
$keyId = $null

if ($Generate) {
    if (-not $KeyName) { $KeyName = Get-DevSetupValue $config "user.git.userName" }
    if (-not $KeyEmail) { $KeyEmail = Get-DevSetupValue $config "user.git.userEmail" }
    if (-not $KeyName -or -not $KeyEmail) {
        throw "Set user.git.userName and user.git.userEmail in config/dev-setup.config.json (or pass -KeyName/-KeyEmail) before generating a key."
    }

    $generatedPassphrase = $false
    if (-not $KeyPassphrase) {
        $KeyPassphrase = New-DevSetupRandomSecret
        $generatedPassphrase = $true
    }
    $plainKeyPassphrase = ConvertFrom-DevSetupSecureString $KeyPassphrase

    $expiry = Get-DevSetupValue $config "advanced.gpg.keyExpiry" "2y"
    $batchFile = New-TemporaryFile
    @"
%echo Generating GPG key for git signing
Key-Type: RSA
Key-Length: 4096
Subkey-Type: RSA
Subkey-Length: 4096
Name-Real: $KeyName
Name-Email: $KeyEmail
Expire-Date: $expiry
Passphrase: $plainKeyPassphrase
%commit
%echo done
"@ | Set-Content $batchFile.FullName -Encoding ascii

    Write-DevSetupStatus install "GPG key" "generating a new RSA 4096 key for $KeyName <$KeyEmail> (expires in $expiry)"
    & $gpg --batch --pinentry-mode loopback --gen-key $batchFile.FullName 2>&1 | Out-Null
    Remove-Item $batchFile.FullName -ErrorAction SilentlyContinue
    if ($LASTEXITCODE -ne 0) { throw "gpg key generation failed (exit code $LASTEXITCODE)." }

    $keyId = (& $gpg --list-secret-keys --with-colons $KeyEmail | Where-Object { $_ -like "fpr:*" } | Select-Object -First 1) -split ":" | Select-Object -Last 1
    if (-not $keyId) { throw "Key generation reported success but the new key could not be found for $KeyEmail." }
    Write-DevSetupStatus found "GPG key" "generated $keyId"

    if ($generatedPassphrase) {
        Write-Host ""
        Write-Host "Generated key passphrase (shown once - save it now): $plainKeyPassphrase" -ForegroundColor Yellow
        Write-Host ""
    }

    Set-DevSetupGitSigningKey -GpgExe $gpg -KeyId $keyId
}

if ($Export) {
    if (-not $keyId) { $keyId = Get-DevSetupSigningKeyId }
    if (-not $keyId) { throw "No signing key configured. Pass -Generate first, or set one up with 'git config --global user.signingkey <id>'." }

    $generatedZipPassword = $false
    if (-not $ZipPassword) {
        $ZipPassword = New-DevSetupRandomSecret
        $generatedZipPassword = $true
    }
    $plainZipPassword = ConvertFrom-DevSetupSecureString $ZipPassword

    $bundleDir = Join-Path ([System.IO.Path]::GetTempPath()) ("devsetup-gpg-{0}" -f [guid]::NewGuid())
    New-Item -Path $bundleDir -ItemType Directory -Force | Out-Null
    try {
        & $gpg --batch --yes --export --armor $keyId | Set-Content (Join-Path $bundleDir "public.asc") -Encoding ascii
        & $gpg --batch --yes --export-secret-keys --armor $keyId | Set-Content (Join-Path $bundleDir "secret.asc") -Encoding ascii
        @"
GPG signing identity backup
Key ID: $keyId
Exported: $(Get-Date -Format o)

To restore: .\manage-gpg-key.ps1 -Import <this file> -ZipPassword <the password you were given for this export>
"@ | Set-Content (Join-Path $bundleDir "README.txt")
        if ($KeyPassphrase) {
            # Only ever written inside the archive we are about to encrypt, never left on disk in the clear.
            $notes = "Private key passphrase: $(ConvertFrom-DevSetupSecureString $KeyPassphrase)"
            $notes | Set-Content (Join-Path $bundleDir "KEY-PASSPHRASE.txt")
        }

        $plainZip = Join-Path ([System.IO.Path]::GetTempPath()) ("devsetup-gpg-{0}.zip" -f [guid]::NewGuid())
        Compress-Archive -Path (Join-Path $bundleDir "*") -DestinationPath $plainZip -Force

        $outputPath = $Export
        if ($outputPath -notlike "*.gpg") { $outputPath = "$outputPath.gpg" }
        & $gpg --batch --yes --passphrase $plainZipPassword --pinentry-mode loopback --symmetric --cipher-algo AES256 -o $outputPath $plainZip
        if ($LASTEXITCODE -ne 0) { throw "Encrypting the export failed (exit code $LASTEXITCODE)." }

        Write-DevSetupStatus install "GPG key" "exported $keyId to $outputPath (password protected)"
        if ($generatedZipPassword) {
            Write-Host ""
            Write-Host "Generated archive password (shown once - save it now): $plainZipPassword" -ForegroundColor Yellow
            Write-Host ""
        }
    } finally {
        Remove-Item $bundleDir -Recurse -Force -ErrorAction SilentlyContinue
        if ($plainZip -and (Test-Path $plainZip)) { Remove-Item $plainZip -Force -ErrorAction SilentlyContinue }
    }
}

if ($Import) {
    if (-not (Test-Path $Import)) { throw "Import file not found: $Import" }

    $workDir = Join-Path ([System.IO.Path]::GetTempPath()) ("devsetup-gpg-{0}" -f [guid]::NewGuid())
    New-Item -Path $workDir -ItemType Directory -Force | Out-Null
    try {
        $plainZip = Join-Path $workDir "bundle.zip"
        if ($Import -like "*.gpg") {
            if (-not $ZipPassword) { throw "This archive is encrypted. Pass -ZipPassword <the password you were given when it was exported>." }
            $plainZipPassword = ConvertFrom-DevSetupSecureString $ZipPassword
            & $gpg --batch --yes --passphrase $plainZipPassword --pinentry-mode loopback --decrypt -o $plainZip $Import
            if ($LASTEXITCODE -ne 0) { throw "Decrypting the archive failed (exit code $LASTEXITCODE); check -ZipPassword." }
        } else {
            Copy-Item $Import $plainZip
        }

        $extractDir = Join-Path $workDir "extracted"
        Expand-Archive -Path $plainZip -DestinationPath $extractDir -Force

        $secretKeyFile = Join-Path $extractDir "secret.asc"
        if (-not (Test-Path $secretKeyFile)) { throw "No secret.asc found in the archive; this doesn't look like a bundle from -Export." }

        & $gpg --batch --yes --import $secretKeyFile 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "gpg import failed (exit code $LASTEXITCODE)." }

        $readme = Join-Path $extractDir "README.txt"
        $importedKeyId = $null
        if (Test-Path $readme) {
            $match = Select-String -Path $readme -Pattern "^Key ID: (.+)$" | Select-Object -First 1
            if ($match) { $importedKeyId = $match.Matches[0].Groups[1].Value.Trim() }
        }
        if (-not $importedKeyId) {
            throw "Key imported, but its ID could not be determined automatically. Run 'gpg --list-secret-keys' and set it with 'git config --global user.signingkey <id>'."
        }

        Write-DevSetupStatus found "GPG key" "imported $importedKeyId"
        Set-DevSetupGitSigningKey -GpgExe $gpg -KeyId $importedKeyId

        $passphraseFile = Join-Path $extractDir "KEY-PASSPHRASE.txt"
        if (Test-Path $passphraseFile) {
            Write-Host ""
            Write-Host "This bundle included a saved private key passphrase: $(Get-Content $passphraseFile)" -ForegroundColor Yellow
            Write-Host ""
        }
    } finally {
        Remove-Item $workDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
