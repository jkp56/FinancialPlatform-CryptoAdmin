[CmdletBinding()]
param(
    [string]$NucHost = 'intelnuc',
    [string]$NucUser = 'jkpieters',
    [string]$RemoteAppPath = '/opt/apps/crypto-admin/app'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($NucHost -notmatch '^[a-zA-Z0-9.-]+$') {
    throw 'NucHost bevat ongeldige tekens.'
}
if ($NucUser -notmatch '^[a-z_][a-z0-9_-]*$') {
    throw 'NucUser bevat ongeldige tekens.'
}
if ($RemoteAppPath -notmatch '^/[a-zA-Z0-9._/-]+$') {
    throw 'RemoteAppPath moet een absoluut Linux-pad zonder spaties zijn.'
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$archiveName = "crypto-admin-app-$([guid]::NewGuid().ToString('N')).tar.gz"
$localArchive = Join-Path ([System.IO.Path]::GetTempPath()) $archiveName
$remoteArchive = "/home/$NucUser/$archiveName"
$destination = "${NucUser}@${NucHost}"

try {
    Write-Host 'Applicatiebestanden inpakken...'
    & tar `
        -czf $localArchive `
        --exclude='.git' `
        --exclude='.agents' `
        --exclude='__pycache__' `
        --exclude='*.pyc' `
        --exclude='*.sqlite3' `
        -C $projectRoot `
        .
    if ($LASTEXITCODE -ne 0) {
        throw "Inpakken is mislukt met exitcode $LASTEXITCODE."
    }

    Write-Host "Uploaden naar $destination..."
    & scp $localArchive "${destination}:${remoteArchive}"
    if ($LASTEXITCODE -ne 0) {
        throw "Uploaden is mislukt met exitcode $LASTEXITCODE."
    }

    Write-Host "Uitpakken in $RemoteAppPath..."
    $remoteCommand = "tar -xzf '$remoteArchive' -C '$RemoteAppPath' && rm -f '$remoteArchive'"
    & ssh $destination $remoteCommand
    if ($LASTEXITCODE -ne 0) {
        throw "Uitpakken op de NUC is mislukt met exitcode $LASTEXITCODE."
    }

    Write-Host "Gereed: de app staat in $RemoteAppPath."
}
finally {
    if (Test-Path -LiteralPath $localArchive) {
        Remove-Item -LiteralPath $localArchive -Force
    }
}
