#!/usr/bin/env python3
"""
Quick test to verify empty directory result caching is working.
This test will call the _get_subdirectories_from_db function multiple times
for an empty directory path and check if cache hits occur.
"""
import sys
import time

sys.path.insert(0, '/app')

from dirlisting import _get_subdirectories_from_db
from logging_setup import setup_logging

# Set up logging to see cache messages
setup_logging()

print("\n=== Testing Empty Directory Result Caching ===\n")

# Test path that should return no subdirectories
# Format: mount_path, virtual_prefix
test_mount = "/mnt/transfs"
test_virtual = "RetroBat/bios/mame/empty_test"

print(f"Mount path: {test_mount}")
print(f"Virtual prefix: {test_virtual}")
print(f"This virtual path has no subdirectories in the database.\n")

# First call - should hit database and cache the result
print("Call 1 (should hit database and store in cache):")
start = time.time()
result1 = _get_subdirectories_from_db(test_mount, test_virtual)
elapsed1 = time.time() - start
print(f"  Result: {result1}")
print(f"  Time: {elapsed1*1000:.1f}ms\n")

# Second call immediately - should hit cache
print("Call 2 (should hit cache immediately):")
start = time.time()
result2 = _get_subdirectories_from_db(test_mount, test_virtual)
elapsed2 = time.time() - start
print(f"  Result: {result2}")
print(f"  Time: {elapsed2*1000:.1f}ms\n")

# Third call after short delay - should still hit cache
print("Call 3 (after 1 second, should still hit cache):")
time.sleep(1)
start = time.time()
result3 = _get_subdirectories_from_db(test_mount, test_virtual)
elapsed3 = time.time() - start
print(f"  Result: {result3}")
print(f"  Time: {elapsed3*1000:.1f}ms\n")

# Performance improvement assessment
if elapsed1 > 0 and elapsed2 > 0:
    speedup = elapsed1 / elapsed2 if elapsed2 > 0 else float('inf')
    print(f"Performance improvement: {speedup:.0f}x faster (cache vs database)")
    print(f"  First call (DB):    {elapsed1*1000:.1f}ms")
    print(f"  Cached calls (avg): {(elapsed2+elapsed3)/2*1000:.1f}ms")

print("\n✅ Cache test complete!")
print("\nExpected log output:")
print("  1st call: 'DB_QUERY...' or 'CACHE STORE (empty)...'")
print("  2nd call: 'CACHE HIT (empty)...'")
print("  3rd call: 'CACHE HIT (empty)...'")
