param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$RebuildIcon
)

$iconPath = Join-Path $ProjectRoot 'assets\video-download-round.ico'
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutName = -join [char[]](0x89C6, 0x9891, 0x4E0B, 0x8F7D)
$shortcutPath = Join-Path $desktop ($shortcutName + '.lnk')
$oldShortcutPath = Join-Path $desktop 'Video Link Analyzer.lnk'
$shell = New-Object -ComObject WScript.Shell

if (Test-Path -LiteralPath $oldShortcutPath) {
    Remove-Item -LiteralPath $oldShortcutPath -Force
}

# Remove an earlier shortcut to this program, including one whose Chinese
# name was damaged by Windows PowerShell's legacy text encoding.
Get-ChildItem -LiteralPath $desktop -Filter '*.lnk' -File | ForEach-Object {
    try {
        $existing = $shell.CreateShortcut($_.FullName)
        if ($existing.Arguments -like "*$ProjectRoot\scripts\start_desktop_app.bat*") {
            Remove-Item -LiteralPath $_.FullName -Force
        }
    } catch {
        # Ignore unrelated or unreadable desktop shortcuts.
    }
}

if ($RebuildIcon -or -not (Test-Path -LiteralPath $iconPath)) {
    Add-Type -AssemblyName System.Drawing
    $bitmap = New-Object System.Drawing.Bitmap 256, 256
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.Clear([System.Drawing.Color]::Transparent)

    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddArc(16, 16, 224, 224, 0, 360)
    $brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
        (New-Object System.Drawing.Point(35, 25)),
        (New-Object System.Drawing.Point(220, 230)),
        ([System.Drawing.Color]::FromArgb(112, 158, 245)),
        ([System.Drawing.Color]::FromArgb(63, 112, 218))
    )
    $graphics.FillPath($brush, $path)

    $inner = New-Object System.Drawing.Drawing2D.GraphicsPath
    $inner.AddArc(29, 29, 198, 198, 0, 360)
    $graphics.FillPath((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(31, 73, 162))), $inner)

    $play = [System.Drawing.Point[]]@(
        (New-Object System.Drawing.Point(105, 76)),
        (New-Object System.Drawing.Point(105, 180)),
        (New-Object System.Drawing.Point(190, 128))
    )
    $graphics.FillPolygon((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)), $play)
    $graphics.FillEllipse((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(215, 232, 255))), 57, 107, 23, 23)

    # Write a standard 32-bit ICO with an AND transparency mask. Windows
    # Explorer uses this mask when rendering desktop shortcut icons.
    $pixelBytes = New-Object byte[] (256 * 256 * 4)
    $maskRowBytes = 32
    $maskBytes = New-Object byte[] ($maskRowBytes * 256)
    for ($row = 0; $row -lt 256; $row++) {
        $sourceY = 255 - $row
        for ($x = 0; $x -lt 256; $x++) {
            $color = $bitmap.GetPixel($x, $sourceY)
            $pixelOffset = ($row * 256 + $x) * 4
            $pixelBytes[$pixelOffset] = $color.B
            $pixelBytes[$pixelOffset + 1] = $color.G
            $pixelBytes[$pixelOffset + 2] = $color.R
            $pixelBytes[$pixelOffset + 3] = $color.A
            if ($color.A -lt 128) {
                $maskOffset = $row * $maskRowBytes + [int][math]::Floor($x / 8)
                $maskBytes[$maskOffset] = [byte]([int]$maskBytes[$maskOffset] -bor (0x80 -shr ($x % 8)))
            }
        }
    }

    $imageSize = 40 + $pixelBytes.Length + $maskBytes.Length
    $stream = [System.IO.File]::Open($iconPath, [System.IO.FileMode]::Create)
    $writer = New-Object System.IO.BinaryWriter($stream)
    try {
        $writer.Write([uint16]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]1)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([uint32]$imageSize)
        $writer.Write([uint32]22)
        $writer.Write([uint32]40)
        $writer.Write([int32]256)
        $writer.Write([int32]512)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([uint32]0)
        $writer.Write([uint32]$pixelBytes.Length)
        $writer.Write([int32]0)
        $writer.Write([int32]0)
        $writer.Write([uint32]0)
        $writer.Write([uint32]0)
        $writer.Write($pixelBytes)
        $writer.Write($maskBytes)
    } finally {
        $writer.Dispose(); $brush.Dispose(); $graphics.Dispose(); $bitmap.Dispose()
    }
}

$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$env:ComSpec"
$shortcut.Arguments = "/c `"`"$ProjectRoot\scripts\start_desktop_app.bat`"`""
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.IconLocation = "$iconPath,0"
$shortcut.Description = $shortcutName
$shortcut.Save()

Write-Output $shortcutPath
