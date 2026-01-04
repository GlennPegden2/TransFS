#!/usr/bin/env pwsh
# TransFS Testing - Docker Required
# ==================================
# Tests must be run inside Docker to access the FUSE mount.
# This script redirects to the Docker-based test runner.

Write-Host ""
Write-Host "⚠️  Tests must be run inside Docker container" -ForegroundColor Yellow
Write-Host "   (FUSE mounts not accessible from host)" -ForegroundColor Yellow
Write-Host ""
Write-Host "Quick validation (recommended):" -ForegroundColor Cyan
Write-Host "  .\validate_docker.ps1" -ForegroundColor White
Write-Host ""
Write-Host "Full regression tests:" -ForegroundColor Cyan
Write-Host "  .\run_tests_in_docker.ps1" -ForegroundColor White
Write-Host ""

# If user really wants to try anyway, let them
if ($args -contains "--force-host") {
    Write-Host "Running on host (may fail)..." -ForegroundColor Red
    pytest tests/ @args
} else {
    Write-Host "Run with --force-host to attempt host testing (not recommended)" -ForegroundColor Gray
    exit 1
}
# --------------------------

# Run specific test
# pytest tests/test_filesystem_snapshots.py::TestTransFSSnapshots::test_transfs_root_structure -v

# Update snapshots (after reviewing changes)
# pytest --snapshot-update

# Run with coverage
# pytest --cov=app --cov-report=html
# Then open: htmlcov/index.html

# Run all tests including old ones
# pytest tests/ -v

# Stop Docker when done
# docker-compose down
