#!/bin/bash
# Run TransFS Tests Inside Docker Container
# ==========================================
# This script runs pytest inside the Docker container where the FUSE mount is accessible

set -e

echo -e "\033[36mTransFS Test Runner (Docker Mode)\033[0m"
echo -e "\033[36m==================================\033[0m"
echo ""

# Check if container is running
echo -e "\033[33mChecking Docker container status...\033[0m"
if ! docker inspect -f '{{.State.Running}}' transfs 2>/dev/null | grep -q "true"; then
    echo -e "\033[31m❌ Container 'transfs' is not running.\033[0m"
    echo -e "\033[33m   Starting container...\033[0m"
    docker-compose up -d
    sleep 5
    
    if ! docker inspect -f '{{.State.Running}}' transfs 2>/dev/null | grep -q "true"; then
        echo -e "\033[31m❌ Failed to start container. Please run: docker-compose up -d\033[0m"
        exit 1
    fi
fi

echo -e "\033[32m✅ Container is running\033[0m"
echo ""

# Parse command line arguments (default to running all snapshot tests)
if [ $# -eq 0 ]; then
    PYTEST_ARGS="/tests/test_filesystem_snapshots.py -v"
else
    # Convert any relative 'tests/' paths to absolute '/tests/' paths for container
    PYTEST_ARGS=""
    for arg in "$@"; do
        if [[ "$arg" == tests/* ]]; then
            PYTEST_ARGS="$PYTEST_ARGS /${arg}"
        else
            PYTEST_ARGS="$PYTEST_ARGS $arg"
        fi
    done
fi

echo -e "\033[36mRunning tests inside Docker container...\033[0m"
echo -e "\033[90mCommand: pytest $PYTEST_ARGS\033[0m"
echo ""

# Run pytest inside the container
# Set RUNNING_IN_DOCKER=1 to ensure conftest.py uses container paths
docker exec -e RUNNING_IN_DOCKER=1 transfs pytest $PYTEST_ARGS

EXIT_CODE=$?

echo ""
echo -e "\033[36m===========================================\033[0m"
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "\033[32m✅ All tests PASSED\033[0m"
    echo -e "\033[32m   No breaking changes detected!\033[0m"
else
    echo -e "\033[31m❌ Some tests FAILED (exit code: $EXIT_CODE)\033[0m"
    echo -e "\033[33m   Review the output above for details\033[0m"
fi
echo -e "\033[36m===========================================\033[0m"
echo ""

# Show useful commands
echo -e "\033[90mUseful Commands:\033[0m"
echo -e "\033[90m  Update snapshots: ./run_tests_in_docker.sh --snapshot-update\033[0m"
echo -e "\033[90m  Run specific test: ./run_tests_in_docker.sh tests/test_filesystem_snapshots.py::TestName::test_name\033[0m"
echo -e "\033[90m  Run with coverage: ./run_tests_in_docker.sh --cov=app --cov-report=html\033[0m"
echo ""

exit $EXIT_CODE
