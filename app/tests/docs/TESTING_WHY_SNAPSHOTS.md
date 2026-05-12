# Why Snapshot Testing for TransFS?

## The Problem

TransFS is a complex virtual filesystem that transforms archive content into various platform-specific layouts. As development progresses, patches and new features risk introducing **breaking changes** that:

1. Remove expected files or directories
2. Change file naming conventions
3. Break emulator compatibility
4. Cause regressions in previously working systems

**Manual verification is impractical** given:
- 7+ different systems (Acorn, Amstrad, MITS, Tandy, etc.)
- Multiple file formats per system (DSK, HDF, VHD, MMB, UEF, etc.)
- Hundreds of files across the virtual filesystem
- Docker-based deployment with volume mappings

## Alternative Approaches (and Why They Fall Short)

### ❌ Manual Testing

```
Approach: Manually check directory listings after each change
```

**Cons:**
- ⏱️ Time-consuming (hours per change)
- 👤 Human error prone
- 📝 No documentation of expected state
- 🔄 Not repeatable across developers
- 🚫 Can't run in CI/CD
- 😫 Developer fatigue leads to skipped testing

**Verdict:** Not sustainable for ongoing development

---

### ❌ Integration Tests with Hardcoded Assertions

```python
def test_archimedes():
    assert os.path.exists("/mnt/transfs/Native/Acorn/Archimedes")
    assert os.path.exists("/mnt/transfs/Native/Acorn/Archimedes/Software")
    assert os.path.exists("/mnt/transfs/Native/Acorn/Archimedes/Software/BIOS")
    # ... hundreds more assertions ...
```

**Cons:**
- 📜 Verbose and hard to maintain
- 🔧 Brittle - breaks easily with legitimate changes
- 🐌 Slow to write
- 👁️ Hard to see what changed when tests fail
- 📈 Scales poorly (need assertion per file/directory)

**Verdict:** Too much maintenance burden

---

### ❌ Hash-Based File Verification

```python
def test_filesystem_hash():
    current_hash = hash_directory_tree("/mnt/transfs")
    assert current_hash == "abc123..."
```

**Cons:**
- 🕵️ No visibility into **what** changed
- 🔍 Debugging requires manual investigation
- 📊 Can't tell if change is in 1 file or 100 files
- 🤷 No diff to review

**Verdict:** Fails fast but provides no useful information

---

### ❌ Custom Comparison Scripts

```python
def compare_directories(expected, actual):
    # Custom logic to compare...
    # 50+ lines of code...
```

**Cons:**
- 🐛 Need to write and maintain comparison logic
- 🧪 Comparison logic itself needs testing
- 🔄 Reinventing the wheel
- 📚 No standard format for diffs

**Verdict:** Unnecessary complexity

---

## ✅ Our Solution: pytest + syrupy Snapshot Testing

```python
def test_transfs_structure(transfs_volume, filesystem_walker, snapshot):
    state = filesystem_walker(transfs_volume)
    assert state == snapshot
```

**Pros:**
- ✅ **Automatic change detection** - Any difference is caught immediately
- ✅ **Clear diffs** - See exactly what changed (added/removed/modified)
- ✅ **Self-documenting** - Snapshots serve as documentation
- ✅ **Easy updates** - `pytest --snapshot-update` when changes are intentional
- ✅ **Fast** - Tests run in seconds
- ✅ **Maintainable** - Minimal code to maintain
- ✅ **CI/CD ready** - Integrates seamlessly
- ✅ **Industry standard** - Well-tested tooling (pytest, syrupy)
- ✅ **Granular** - Separate snapshots per test/system
- ✅ **Comprehensive** - Captures entire filesystem state

## Real-World Comparison

### Scenario: Developer adds support for new Amstrad PCW disk format

#### Manual Testing Approach

```
1. Developer makes changes .......................... 30 min
2. Build Docker container ........................... 2 min
3. Mount SMB share .................................. 1 min
4. Manually browse directory tree ................... 10 min
5. Compare against notes from last time ............. 15 min
6. Check each system wasn't affected ................ 20 min
7. Document what changed ............................ 5 min
───────────────────────────────────────────────────────────
Total: ~83 minutes, error-prone, undocumented
```

#### Snapshot Testing Approach

```
1. Developer makes changes .......................... 30 min
2. Run: pytest -v .................................. 15 sec
3. Review diff showing new directories .............. 2 min
4. Run: pytest --snapshot-update .................... 10 sec
5. Commit (code + snapshots) ........................ 1 min
───────────────────────────────────────────────────────────
Total: ~33 minutes, automated, fully documented
```

**Result:** 60% time savings + better quality

---

### Scenario: Accidental breaking change introduced

#### Without Snapshot Testing

```
1. Developer makes "small" fix ...................... 10 min
2. Commit and push .................................. 1 min
3. Another developer notices issue .................. 2 days later
4. Investigation and debugging ...................... 60 min
5. Git bisect to find problematic commit ............ 20 min
6. Revert or fix .................................... 30 min
───────────────────────────────────────────────────────────
Total: 2+ days to discover, 110+ minutes to fix
Impact: Broken main branch, wasted team time
```

#### With Snapshot Testing

```
1. Developer makes "small" fix ...................... 10 min
2. Run: pytest -v .................................. 15 sec
   ❌ FAILED: 2 files missing from Electron/
3. Developer: "Oops, that's not right!"
4. Fix the issue .................................... 5 min
5. Run: pytest -v .................................. 15 sec
   ✅ PASSED
6. Commit .......................................... 1 min
───────────────────────────────────────────────────────────
Total: 16 minutes, caught immediately
Impact: Zero broken commits, zero team disruption
```

**Result:** Breaking change caught before commit

---

## Feature Comparison Table

| Feature | Manual | Hardcoded Assertions | Hash-Based | Snapshot Testing |
|---------|--------|---------------------|------------|------------------|
| **Speed** | 🐌 Slow | ⚡ Fast | ⚡ Fast | ⚡ Fast |
| **Maintenance** | ❌ High | ❌ High | ✅ Low | ✅ Low |
| **Visibility** | ⚠️ Medium | ✅ Good | ❌ Poor | ✅ Excellent |
| **CI/CD Ready** | ❌ No | ✅ Yes | ✅ Yes | ✅ Yes |
| **Scalability** | ❌ Poor | ⚠️ Medium | ✅ Good | ✅ Excellent |
| **Documentation** | ❌ None | ⚠️ Implicit | ❌ None | ✅ Self-documenting |
| **Updates** | N/A | ❌ Manual code changes | ❌ Manual hash update | ✅ `--snapshot-update` |
| **Diff Quality** | ❌ None | ⚠️ Basic | ❌ None | ✅ Detailed |
| **Learning Curve** | ✅ Easy | ⚠️ Medium | ✅ Easy | ⚡ Easy |
| **Industry Standard** | ❌ No | ⚠️ Common | ❌ Custom | ✅ Yes |

## Cost-Benefit Analysis

### Initial Investment

| Approach | Setup Time | Code Written | External Dependencies |
|----------|------------|--------------|---------------------|
| Manual | 0 hours | 0 lines | None |
| Hardcoded Assertions | 8-16 hours | 500+ lines | pytest |
| Hash-Based | 2-4 hours | 100 lines | pytest, hashlib |
| **Snapshot Testing** | **2-3 hours** | **~200 lines** | **pytest, syrupy, deepdiff** |

### Ongoing Costs

| Approach | Per Feature | Per Bug Fix | Per System Added |
|----------|-------------|-------------|------------------|
| Manual | 60+ min | 30+ min | 120+ min |
| Hardcoded Assertions | 30 min (update assertions) | 15 min | 60 min |
| Hash-Based | 5 min (update hash) | 5 min | 10 min |
| **Snapshot Testing** | **2 min (review diff)** | **15 sec (just run tests)** | **3 min (add parameterized test)** |

### Return on Investment

```
Break-even point: After ~5-10 changes
ROI after 1 month: ~10 hours saved
ROI after 1 year: ~100+ hours saved + prevented production issues
```

## Real Developer Quotes (Simulated)

### Before Snapshot Testing

> "I'm afraid to touch the transformation logic because I don't know what it might break."
> — Developer A

> "It took me 2 hours to verify my change didn't break the 7 supported systems."
> — Developer B

> "We had to roll back a release because Electron support broke and we didn't notice."
> — Team Lead

### After Snapshot Testing

> "I can make changes confidently knowing tests will catch any issues immediately."
> — Developer A

> "Tests run in 15 seconds and tell me exactly what changed. Game changer!"
> — Developer B

> "Haven't had a broken release since we added snapshot testing."
> — Team Lead

## When NOT to Use Snapshot Testing

Snapshot testing is **not ideal** for:

1. **Dynamic/non-deterministic output** - Timestamps, random IDs, etc.
   - *TransFS doesn't have this problem - filesystem structure is deterministic*

2. **Large binary files** - Snapshots would be huge
   - *We snapshot structure, not file contents*

3. **Frequently changing APIs** - Every change requires snapshot update
   - *TransFS structure changes are rare and intentional*

4. **Performance-critical paths** - Snapshot comparison adds overhead
   - *Our tests run in seconds, acceptable for dev workflow*

**Verdict:** TransFS is an **ideal** use case for snapshot testing!

## Conclusion

For TransFS, snapshot testing with pytest + syrupy provides:

✅ **Maximum protection** against breaking changes
✅ **Minimal maintenance** burden
✅ **Clear visibility** into what changed
✅ **Fast feedback** loop
✅ **Industry-standard** tooling
✅ **Excellent ROI**

The choice is clear: **snapshot testing is the right solution** for detecting breaking changes in TransFS's complex virtual filesystem.

---

## Further Reading

- [Snapshot Testing Best Practices](https://kentcdodds.com/blog/effective-snapshot-testing)
- [Syrupy Documentation](https://github.com/tophat/syrupy)
- [pytest Documentation](https://docs.pytest.org/)
- [When to Use Snapshot Testing](https://jestjs.io/docs/snapshot-testing) (Jest, but principles apply)
