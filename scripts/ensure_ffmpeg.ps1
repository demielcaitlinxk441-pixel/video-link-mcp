$ErrorActionPreference = 'Stop'

function Find-Ffmpeg {
    $command = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($command -and (Test-Path -LiteralPath $command.Source)) {
        return $command.Source
    }

    $packageRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    if (Test-Path -LiteralPath $packageRoot) {
        $candidate = Get-ChildItem -LiteralPath $packageRoot -Filter 'ffmpeg.exe' -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -like '*Gyan.FFmpeg*' } |
            Select-Object -First 1
        if ($candidate) {
            return $candidate.FullName
        }
    }

    return $null
}

$ffmpeg = Find-Ffmpeg
if (-not $ffmpeg) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'Windows App Installer (winget) is required to install ffmpeg automatically.'
    }

    Write-Error 'ffmpeg was not found. Installing ffmpeg...'
    & winget install --id Gyan.FFmpeg.Shared --exact --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "ffmpeg installation failed with exit code $LASTEXITCODE."
    }
    $ffmpeg = Find-Ffmpeg
}

if (-not $ffmpeg) {
    throw 'ffmpeg installation finished, but ffmpeg.exe could not be located.'
}

Write-Output $ffmpeg
