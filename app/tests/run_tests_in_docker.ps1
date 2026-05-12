# Run Tests Inside Docker Container
# ==================================
# This script runs the test suite inside the Docker container where
# the FUSE filesystem is actually mounted and accessible.
#
# Usage:
#   .\run_tests_in_docker.ps1           # Run tests normally
#   .\run_tests_in_docker.ps1 -Update   # Update snapshots

param(
    [switch]$Update
)

Write-Host "Running tests inside Docker container..." -ForegroundColor Cyan

# Check if container is running
$containerRunning = docker ps --filter "name=transfs" --format "{{.Names}}"

if (-not $containerRunning) {
    Write-Host "❌ TransFS container is not running!" -ForegroundColor Red
    Write-Host "Start it with: docker-compose up -d" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Container is running" -ForegroundColor Green

# Build pytest arguments
$pytestArgs = @("pytest", "/tests/test_filesystem_snapshots.py", "-v")
if ($Update) {
    $pytestArgs += "--snapshot-update"
    Write-Host "🔄 Snapshot update mode enabled" -ForegroundColor Yellow
}

# Run pytest inside the container
Write-Host "`nExecuting tests..." -ForegroundColor Cyan
docker exec -it transfs @pytestArgs

# Check exit code
if ($LASTEXITCODE -eq 0) {
    if ($Update) {
        Write-Host "`n✅ Snapshots updated successfully!" -ForegroundColor Green
    } else {
        Write-Host "`n✅ All tests passed!" -ForegroundColor Green
    }
} else {
    Write-Host "`n❌ Some tests failed. Review output above." -ForegroundColor Red
}
