$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$androidRoot = Join-Path $projectRoot 'android'
$androidStudioJbr = 'C:\Program Files\Android\Android Studio\jbr'
$sdkCandidates = @($env:ANDROID_SDK_ROOT, $env:ANDROID_HOME) | Where-Object { $_ -and (Test-Path $_) }
if ($env:LOCALAPPDATA) {
  $defaultSdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
  if (Test-Path $defaultSdk) { $sdkCandidates += $defaultSdk }
}

if (-not $env:JAVA_HOME -or -not (Test-Path (Join-Path $env:JAVA_HOME 'bin\java.exe'))) {
  if (Test-Path (Join-Path $androidStudioJbr 'bin\java.exe')) {
    $env:JAVA_HOME = $androidStudioJbr
  } else {
    throw '未找到 Java。请安装 Android Studio（它自带 JDK），然后重新运行此脚本。'
  }
}

if (-not $sdkCandidates) {
  throw '未找到 Android SDK。请在 Android Studio 的 SDK Manager 中安装 Android SDK 后重新运行。'
}

$env:ANDROID_SDK_ROOT = $sdkCandidates[0]
$env:ANDROID_HOME = $sdkCandidates[0]
$localProperties = Join-Path $androidRoot 'local.properties'
"sdk.dir=$($sdkCandidates[0].Replace('\', '/'))" | Set-Content -Path $localProperties -Encoding ASCII

# Avoid Windows path-limit failures in Expo Modules Core's CMake build.
$nodeModulesRoot = Join-Path $projectRoot 'node_modules'
if (Test-Path $nodeModulesRoot) {
  Get-ChildItem -LiteralPath $nodeModulesRoot -Recurse -File -Filter 'build.gradle' -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match 'expo-modules-core[\\/]android[\\/]build.gradle$' } |
    ForEach-Object {
      $gradleFile = $_.FullName
      $text = Get-Content -LiteralPath $gradleFile -Raw
      if ($text -notmatch 'CMAKE_SUPPRESS_REGENERATION') {
        $text = $text.Replace('"-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON",', '"-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON",' + [Environment]::NewLine + '            "-DCMAKE_SUPPRESS_REGENERATION=ON",' + [Environment]::NewLine + '            "-DCMAKE_OBJECT_PATH_MAX=128",')
        Set-Content -LiteralPath $gradleFile -Value $text -Encoding UTF8
      }
    }
}

Push-Location $androidRoot
try {
  & .\gradlew.bat assembleRelease --no-daemon -PreactNativeArchitectures=arm64-v8a
  if ($LASTEXITCODE -ne 0) { throw "Gradle 构建失败，退出码 $LASTEXITCODE。" }
} finally {
  Pop-Location
}

$apk = Join-Path $androidRoot 'app\build\outputs\apk\release\app-release.apk'
if (-not (Test-Path $apk)) { throw '构建完成但没有找到 APK 文件。' }
$dist = Join-Path $projectRoot 'dist'
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$target = Join-Path $dist 'video-link-v4-local.apk'
Copy-Item -LiteralPath $apk -Destination $target -Force
Write-Host "APK 已生成：$target"
