# TransFS Testing Quick Commands
# ===============================
# Run these commands in PowerShell to test your TransFS installation

# 1. FIRST TIME SETUP
# -------------------
Write-Host "Installing test dependencies..." -ForegroundColor Cyan
pip install -r requirements-dev.txt

# 2. START DOCKER CONTAINER
# -------------------------
Write-Host "`nStarting Docker container..." -ForegroundColor Cyan
docker-compose up --build -d

Write-Host "`nWaiting for services to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

# 3. RUN TESTS
# ------------
Write-Host "`nRunning snapshot tests..." -ForegroundColor Cyan
pytest tests/test_filesystem_snapshots.py -v

# 4. INTERPRET RESULTS
# --------------------
Write-Host "`n" -ForegroundColor Green
Write-Host "===========================================" -ForegroundColor Green
Write-Host "Test Results Interpretation:" -ForegroundColor Green
Write-Host "===========================================" -ForegroundColor Green
Write-Host "✅ All tests PASSED    = No breaking changes detected!" -ForegroundColor Green
Write-Host "❌ Some tests FAILED   = Review changes carefully!" -ForegroundColor Red
Write-Host "⏭️  Tests SKIPPED      = Docker volumes not accessible" -ForegroundColor Yellow
Write-Host "" -ForegroundColor Green

# ADDITIONAL USEFUL COMMANDS
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
