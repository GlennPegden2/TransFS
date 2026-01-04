#!/usr/bin/env pwsh
# Quick validation test that runs in seconds, not minutes
# Verifies core functionality without full filesystem walks

Write-Host "=== TransFS Quick Validation ===" -ForegroundColor Cyan
Write-Host ""

# Check if Docker container is running
$containerStatus = docker ps --filter "name=transfs" --format "{{.Status}}"
if (-not $containerStatus) {
    Write-Host "ERROR: TransFS container is not running" -ForegroundColor Red
    Write-Host "Start it with: docker-compose up -d" -ForegroundColor Yellow
    exit 1
}

docker exec transfs python3 /tests/test_docker_quick.py

$exitCode = $LASTEXITCODE
Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "=== Validation Passed ===" -ForegroundColor Green
} else {
    Write-Host "=== Validation Failed ===" -ForegroundColor Red
}

exit $exitCode
