param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$iconPath = Join-Path $ProjectRoot 'assets\app-icon.ico'
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'Video Link Analyzer.lnk'

if (-not (Test-Path -LiteralPath $iconPath)) {
    Add-Type -AssemblyName System.Drawing
    $bitmap = New-Object System.Drawing.Bitmap 256, 256
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.Clear([System.Drawing.Color]::FromArgb(14, 17, 24))

    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddArc(16, 16, 224, 224, 0, 360)
    $brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
        (New-Object System.Drawing.Point(35, 25)),
        (New-Object System.Drawing.Point(220, 230)),
        ([System.Drawing.Color]::FromArgb(84, 132, 255)),
        ([System.Drawing.Color]::FromArgb(34, 83, 220))
    )
    $graphics.FillPath($brush, $path)

    $inner = New-Object System.Drawing.Drawing2D.GraphicsPath
    $inner.AddArc(29, 29, 198, 198, 0, 360)
    $graphics.FillPath((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(20, 27, 46))), $inner)

    $play = [System.Drawing.Point[]]@(
        (New-Object System.Drawing.Point(105, 76)),
        (New-Object System.Drawing.Point(105, 180)),
        (New-Object System.Drawing.Point(190, 128))
    )
    $graphics.FillPolygon((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)), $play)
    $graphics.FillEllipse((New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(131, 167, 255))), 57, 107, 23, 23)

    $icon = [System.Drawing.Icon]::FromHandle($bitmap.GetHicon())
    $stream = [System.IO.File]::Open($iconPath, [System.IO.FileMode]::Create)
    $icon.Save($stream)
    $stream.Dispose(); $icon.Dispose(); $brush.Dispose(); $graphics.Dispose(); $bitmap.Dispose()
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$env:ComSpec"
$shortcut.Arguments = "/c `"`"$ProjectRoot\scripts\start_desktop_app.bat`"`""
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.IconLocation = "$iconPath,0"
$shortcut.Description = 'Open Video Link Analyzer Desktop Downloader'
$shortcut.Save()

Write-Output $shortcutPath
