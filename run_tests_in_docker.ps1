# Run TransFS Tests Inside Docker Container
# ==========================================
# This script runs pytest inside the Docker container where the FUSE mount is accessible

Write-Host "TransFS Test Runner (Docker Mode)" -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan
Write-Host ""

# Check if container is running
Write-Host "Checking Docker container status..." -ForegroundColor Yellow
$containerStatus = docker inspect -f '{{.State.Running}}' transfs 2>$null

if ($containerStatus -ne "true") {
    Write-Host "❌ Container 'transfs' is not running." -ForegroundColor Red
    Write-Host "   Starting container..." -ForegroundColor Yellow
    docker-compose up -d
    Start-Sleep -Seconds 5
    
    $containerStatus = docker inspect -f '{{.State.Running}}' transfs 2>$null
    if ($containerStatus -ne "true") {
        Write-Host "❌ Failed to start container. Please run: docker-compose up -d" -ForegroundColor Red
        exit 1
    }
}

Write-Host "✅ Container is running" -ForegroundColor Green
Write-Host ""

# Parse command line arguments
$pytestArgs = $args
if ($pytestArgs.Count -eq 0) {
    # Default: run all snapshot tests
    $pytestArgs = @("/tests/test_filesystem_snapshots.py", "-v")
}
else {
    # Convert any relative 'tests/' paths to absolute '/tests/' paths for container
    $pytestArgs = $pytestArgs | ForEach-Object {
        if ($_ -match '^tests/') {
            $_ -replace '^tests/', '/tests/'
        }
        else {
            $_
        }
    }
}

Write-Host "Running tests inside Docker container..." -ForegroundColor Cyan
Write-Host "Command: pytest $($pytestArgs -join ' ')" -ForegroundColor Gray
Write-Host ""

# Run pytest inside the container
# Set RUNNING_IN_DOCKER=1 to ensure conftest.py uses container paths
docker exec -e RUNNING_IN_DOCKER=1 transfs pytest $pytestArgs

$exitCode = $LASTEXITCODE

Write-Host ""
Write-Host "===========================================" -ForegroundColor Cyan
if ($exitCode -eq 0) {
    Write-Host "✅ All tests PASSED" -ForegroundColor Green
    Write-Host "   No breaking changes detected!" -ForegroundColor Green
} else {
    Write-Host "❌ Some tests FAILED (exit code: $exitCode)" -ForegroundColor Red
    Write-Host "   Review the output above for details" -ForegroundColor Yellow
}
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""

# Show useful commands
Write-Host "Useful Commands:" -ForegroundColor Gray
Write-Host "  Update snapshots: .\run_tests_in_docker.ps1 --snapshot-update" -ForegroundColor Gray
Write-Host "  Run specific test: .\run_tests_in_docker.ps1 tests/test_filesystem_snapshots.py::TestName::test_name" -ForegroundColor Gray
Write-Host "  Run with coverage: .\run_tests_in_docker.ps1 --cov=app --cov-report=html" -ForegroundColor Gray
Write-Host ""

exit $exitCode
