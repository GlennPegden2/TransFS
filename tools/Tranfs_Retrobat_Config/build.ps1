#!/usr/bin/env pwsh

<#
.SYNOPSIS
Build script for TransFS RetroBat Configuration utility

.DESCRIPTION
Builds the C# Windows Forms application for easy RetroBat and TransFS integration

.EXAMPLE
.\build.ps1
#>

param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommandPath
$projectFile = Join-Path $projectDir "Tranfs_Retrobat_Config.csproj"

if (-not (Test-Path $projectFile)) {
    Write-Host "ERROR: Project file not found at $projectFile" -ForegroundColor Red
    exit 1
}

Write-Host "Building TransFS RetroBat Configuration Tool..." -ForegroundColor Cyan
Write-Host "Configuration: $Configuration`n"

# Check if dotnet is available
$dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
if (-not $dotnet) {
    Write-Host "ERROR: dotnet CLI not found. Please install .NET 6.0 SDK or higher." -ForegroundColor Red
    Write-Host "Download from: https://dotnet.microsoft.com/download" -ForegroundColor Yellow
    exit 1
}

# Clean previous builds
Write-Host "Cleaning previous builds..."
& dotnet clean -c $Configuration -nologo -q 2>$null

# Restore dependencies
Write-Host "Restoring NuGet packages..."
& dotnet restore -nologo -q

# Build
Write-Host "Building project..."
& dotnet build -c $Configuration -nologo

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed!" -ForegroundColor Red
    exit 1
}

$outputPath = Join-Path $projectDir "bin/$Configuration/net6.0-windows"
$exePath = Join-Path $outputPath "Tranfs_Retrobat_Config.exe"

Write-Host ""
Write-Host "✓ Build completed successfully!" -ForegroundColor Green
Write-Host "Output: $exePath" -ForegroundColor Cyan
Write-Host ""
Write-Host "To run the application:"
Write-Host "  .\$($exePath | Split-Path -Leaf)" -ForegroundColor Yellow
Write-Host ""
