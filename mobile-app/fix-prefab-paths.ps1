param(
  [Parameter(Mandatory = $true)]
  [string]$ProjectRoot,
  [Parameter(Mandatory = $true)]
  [string]$StopFile
)

$ErrorActionPreference = 'SilentlyContinue'
while (-not (Test-Path -LiteralPath $StopFile)) {
  Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'node_modules') -Recurse -File -Filter 'prefab_command.bat' |
    ForEach-Object {
      $raw = Get-Content -LiteralPath $_.FullName -Raw
      $fixed = $raw -replace '\\\\', '\'
      if ($fixed -ne $raw) {
        Set-Content -LiteralPath $_.FullName -Value $fixed -Encoding ASCII
      }
    }
  Start-Sleep -Milliseconds 250
}
