# Phase 3: Multi-System Migration - Your Testing Guide

**Status**: Ready for your hands-on testing!  
**Date Started**: February 17, 2026  
**Your Role**: Select systems, run migrations, validate results

---

## 🎯 Your Mission

Take the proven Phase 2 approach (BBC_B with 52 files) and apply it to 1-3 additional systems from your collection. You'll use the same reusable scripts and tools we created, just for different systems.

---

## 📦 Available Systems in Your Collection

| Manufacturer | Systems | Notes |
|--------------|---------|-------|
| **Acorn** | Atom, Archimedes, Electron, **BBC_B** ✅ | BBC_B already tested |
| **Amstrad** | CPC, PCW | Multiple systems available |
| **Apple** | AppleI, AppleII | Various systems |
| **Atari** | Multiple systems | Check filesystem |
| **MITS** | Altair8800 | *Was empty - don't retry* |
| **Tandy** | Multiple systems | Available for testing |

---

## 🛠️ Reusable Tools (Already Created in Phase 2)

All these scripts are ready to use - just modify the system name!

### **Script 1: Database Migration**
```bash
docker exec transfs python3 /app/migrate_database_phase1.py
```
- Adds Phase 1 schema columns (system, content_type)
- Creates backups automatically
- Indexes all files in target system

### **Script 2: System Extraction Fix**
```bash
docker exec transfs python3 /app/migrate_fix_system.py
```
- Fixes system extraction (e.g., 'C_B' → 'Acorn/BBC_B')
- Template: Create `fix_YOUR_SYSTEM.py` for specific systems

### **Script 3: Query Verification**
```bash
docker exec transfs python3 /app/test_bbc_b_queries.py
```
- Tests database queries for BBC_B
- Adapt to test YOUR_SYSTEM instead

### **Script 4: Dual-Mode Testing**
```bash
docker exec transfs python3 /app/test_bbc_b_dualmode.py
```
- Compares YAML-driven vs database-driven access
- Use as template for your system

### **Script 5: Flattening Automation**
```bash
docker exec transfs bash /app/flatten_bbc_b.sh
```
- Merges subfolder structure into single directory
- Create `flatten_YOUR_SYSTEM.sh` for your system

### **Script 6: Performance Validation**
```bash
docker exec transfs python3 /app/test_bbc_b_performance.py
```
- Measures query performance and access times
- Adapt to test YOUR_SYSTEM

---

## 📋 Step-by-Step Testing Process for One System

### **Step 1: Choose Your System**
Pick ONE system to test first. Recommendations:
- **Easy**: Small collection (20-50 files) - similar to BBC_B
- **Medium**: Medium collection (100-500 files)  
- **Challenging**: Large collection (500+ files)

Once it works, you can repeat for other systems.

### **Step 2: Assess the System**
```bash
# Check what you're working with
docker exec transfs python3 << 'EOF'
from pathlib import Path

system_path = Path("/mnt/filestorefs/Native/MANUFACTURER/SYSTEM/Software")
if system_path.exists():
    files = list(system_path.rglob('*'))
    file_count = sum(1 for f in files if f.is_file())
    total_size = sum(f.stat().st_size for f in files if f.is_file()) / (1024*1024)
    
    print(f"System: {system_path.parent.parent.name}/{system_path.parent.name}")
    print(f"Files: {file_count}")
    print(f"Size: {total_size:.2f} MB")
    print(f"Path: {system_path}")
else:
    print("System path not found!")
EOF
```

Replace `MANUFACTURER` and `SYSTEM` with your choices.

### **Step 3: Create Backups**
```bash
docker exec transfs bash -c '
SYSTEM_PATH="/mnt/filestorefs/Native/MANUFACTURER/SYSTEM"
cd "$SYSTEM_PATH"
tar -czf Software.backup.tar.gz Software/
echo "Backup created: Software.backup.tar.gz"
ls -lh Software.backup.tar.gz
'
```

Also backup the database:
```bash
docker exec transfs cp /mnt/filestorefs/.transfs_metadata.db \
  /mnt/filestorefs/.transfs_metadata.db.YOUR_SYSTEM_backup
```

### **Step 4: Run Database Migration**
```bash
docker exec transfs python3 /app/migrate_database_phase1.py
```

Check for YOUR_SYSTEM in the output.

### **Step 5: Fix System Extraction**
Create a system-specific fix script: `app/fix_YOUR_SYSTEM.py`

Template:
```python
import sqlite3
import re

db = sqlite3.connect('/mnt/filestorefs/.transfs_metadata.db')
cur = db.cursor()

# Get files for your system
cur.execute('SELECT file_id, source_path FROM files WHERE source_path LIKE ?',
            ('%/YOUR_SYSTEM/%',))

files = cur.fetchall()
print(f"Found {len(files)} files for YOUR_SYSTEM")

# Extract system correctly
for file_id, source_path in files:
    # Example: /mnt/filestorefs/Native/Apple/AppleII/Software/...
    # Should extract: Apple/AppleII
    match = re.search(r'Native/(\w+)/([^/]+)/Software', source_path)
    if match:
        system = f"{match.group(1)}/{match.group(2)}"
        cur.execute('UPDATE files SET system = ? WHERE file_id = ?',
                    (system, file_id))

db.commit()
cur.execute('SELECT COUNT(*), system FROM files WHERE source_path LIKE ? GROUP BY system',
            ('%/YOUR_SYSTEM/%',))
for count, sys in cur.fetchall():
    print(f"  {sys}: {count} files")

db.close()
print("✓ System extraction fixed!")
```

### **Step 6: Test Queries**
Create `app/test_YOUR_SYSTEM_queries.py` - adapt from `test_bbc_b_queries.py`

Key changes:
- Change `'Acorn/BBC_B'` to `'YOUR_MANUFACTURER/YOUR_SYSTEM'`
- Adjust expected file counts and types
- Run and verify output

### **Step 7: Dual-Mode Testing**
Create `app/test_YOUR_SYSTEM_dualmode.py` - adapt from `test_bbc_b_dualmode.py`

Verify both YAML-driven and database-driven return same file count.

### **Step 8: Optional - Test Flattening**
Create `app/flatten_YOUR_SYSTEM.sh` if you want to test folder flattening.

```bash
#!/bin/bash
SYSTEM_PATH="/mnt/filestorefs/Native/MANUFACTURER/YOUR_SYSTEM/Software"
TEMP_DIR="${SYSTEM_PATH}_flat"

mkdir -p "$TEMP_DIR"

# Copy all files from subfolders
find "$SYSTEM_PATH" -maxdepth 2 -type f -exec cp {} "$TEMP_DIR/" \;

# Backup original
mv "$SYSTEM_PATH" "${SYSTEM_PATH}_old"

# Move flattened
mv "$TEMP_DIR" "$SYSTEM_PATH"

# Cleanup
rm -rf "${SYSTEM_PATH}_old"

echo "✓ Flattened YOUR_SYSTEM"
```

### **Step 9: Performance Test**
Create `app/test_YOUR_SYSTEM_performance.py` - adapt from `test_bbc_b_performance.py`

Measure:
- Database query times
- Filesystem access times
- File type filtering times

### **Step 10: Document Results**
Create `PHASE_3_YOUR_SYSTEM_RESULTS.md` with:
- System name and file count
- Migration steps taken
- Query verification results
- Dual-mode comparison
- Performance metrics
- Any issues encountered and resolved

### **Step 11: Rollback Test (Optional)**
Restore from backup to verify reversibility:
```bash
docker exec transfs bash -c '
cd /mnt/filestorefs/Native/MANUFACTURER/YOUR_SYSTEM
rm -rf Software
tar -xzf Software.backup.tar.gz
echo "✓ Restored from backup"
'
```

### **Step 12: Commit to GitHub**
```bash
git add -A
git commit -m "Phase 3: Migrate MANUFACTURER/YOUR_SYSTEM - X files indexed"
git push origin dev
```

---

## 🎯 Testing Checklist

For each system you test:

- [ ] System assessed (file count, size, file types documented)
- [ ] Backups created (Software.tar.gz + database snapshot)
- [ ] Database migration ran successfully
- [ ] System extraction verified (correct format: Manufacturer/System)
- [ ] Database queries work (get all, by extension, by type)
- [ ] Dual-mode testing passed (YAML vs DB identical counts)
- [ ] Performance measured (database query times recorded)
- [ ] Rollback tested successfully
- [ ] Results documented in markdown file
- [ ] Work committed to GitHub

---

## 💡 Pro Tips

1. **Test One System at a Time**: Complete the full process for one before starting another
2. **Start Small**: Pick a system with fewer files (20-100) first
3. **Keep Backups**: Always backup before and after testing
4. **Document Everything**: Note any anomalies or unexpected results
5. **Adapt Scripts**: Copy Phase 2 scripts and modify for your system
6. **Performance Baseline**: Compare your results to BBC_B numbers (sub-30ms queries)
7. **Check Database**: Query directly if tests fail

---

## 🔍 Troubleshooting Common Issues

### **"System not found in database"**
- Verify database migration ran
- Check system name format (should be Manufacturer/System, e.g., Apple/AppleII)
- Query database directly: `SELECT DISTINCT system FROM files LIMIT 20`

### **"Query returns 0 files"**
- Migration may have failed for that system
- Check if files exist in filesystem
- Verify system name is correct in queries

### **"File counts don't match (YAML vs DB)"**
- Some files may be in folders not scanned
- Check for hidden files (dotfiles)
- Verify backup was created before migration

### **"Performance is slow"**
- Check database indexes: `PRAGMA index_info(idx_system)`
- Large files may affect stat() times
- Compare with BBC_B baseline (28.40 MB = ~567ms stat time)

### **"Rollback failed"**
- Check backup file exists: `ls -lh Software.backup.tar.gz`
- Verify disk space before restore
- Try extracting manually: `tar -xzf Software.backup.tar.gz`

---

## 📊 Expected Results (Based on BBC_B)

**BBC_B Baseline** (for comparison):
- Files: 52
- Size: 28.40 MB
- Database queries: 3-28 ms
- Dual-mode match: 100% (52 vs 52)
- Rollback: 100% successful

Your systems may vary - that's expected! Document what you find.

---

## 🚀 Next Steps After Testing

Once you complete 1-3 systems:

1. **Compare Results**: Which system behaved differently? Why?
2. **Identify Patterns**: What file types are most common?
3. **Performance Analysis**: Did any system have slower queries?
4. **Automation**: Create batch migration script for all systems
5. **User Feature**: Implement download_layout selection in web UI

---

## 📞 Need Help?

If you hit any snags:
- Check the error message carefully
- Review the troubleshooting section above
- Look at working examples from Phase 2 (BBC_B scripts)
- Compare your system's structure with BBC_B
- Database queries can be tested manually if needed

---

**You've got this!** 🎉 The infrastructure is proven, the tools are ready. Go pick your system(s) and start testing. I'm here if you get stuck!
