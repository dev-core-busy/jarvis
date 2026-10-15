#requires -Version 5.1
<#
.SYNOPSIS
    Publishes AI Mouse as a single portable .exe (no installation required).

.EXAMPLE
    .\build.ps1
    .\build.ps1 -Runtime win-arm64
#>
[CmdletBinding()]
param(
    [ValidateSet('win-x64', 'win-arm64')]
    [string]$Runtime = 'win-x64',

    [string]$Output = "$PSScriptRoot\publish"
)

$ErrorActionPreference = 'Stop'

$project = Join-Path $PSScriptRoot 'src\AiMouse\AiMouse.csproj'

dotnet publish $project `
    --configuration Release `
    --runtime $Runtime `
    --self-contained true `
    --output $Output `
    -p:PublishSingleFile=true

if ($LASTEXITCODE -ne 0) {
    throw "dotnet publish failed with exit code $LASTEXITCODE."
}

Write-Host ''
Write-Host "Portable build ready: $Output\AiMouse.exe" -ForegroundColor Green
Write-Host 'Copy AiMouse.exe together with prompts.json and settings.json to any Windows 11 machine.'
