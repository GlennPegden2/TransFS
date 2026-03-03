# RetroBat & TransFS Configuration Sync - Setup Guide

## Installation & Build Instructions

This utility helps synchronize your RetroBat BIOS directory with TransFS and update your RetroBat configuration automatically.

### Prerequisites

1. **Install .NET 6.0 SDK or higher**
   - Download from: https://dotnet.microsoft.com/download
   - Choose the latest LTS or current version
   - Run the installer and follow prompts
   - Verify installation:
     ```powershell
     dotnet --version
     ```

2. **Windows 10/11**
   - Built for .NET 6.0 on Windows
   - Requires Windows Forms support (standard Windows install)

### Build Instructions

#### Option 1: Using the Build Script (Recommended)

```powershell
cd "g:\Projects\TransFS\tools\Tranfs_Retrobat_Config"
.\build.ps1
```

This will:
- Download/restore NuGet dependencies
- Compile the application in Release mode
- Output: `bin/Release/net6.0-windows/Tranfs_Retrobat_Config.exe`

#### Option 2: Using dotnet CLI Directly

```powershell
cd "g:\Projects\TransFS\tools\RetroBatConfigSync"
dotnet build -c Release
```

### Running the Application

After build completes, run:

```powershell
.\bin\Release\net6.0-windows\Tranfs_Retrobat_Config.exe
```

Or double-click the `.exe` in Windows Explorer.

## What This Tool Does

### Step by Step

1. **Auto-Detects RetroBat**
   - Checks Windows registry for RetroBat installation
   - Falls back to common paths: `C:\RetroBat`, `D:\RetroBat`, `Program Files\RetroBat`
   - Manual browse option available as fallback

2. **Validates TransFS Location**
   - Confirms the path exists and is writable
   - Tests write access with a temporary file
   - Creates `RetroBat/bios/` target directory if needed

3. **Copies BIOS Files**
   - Recursively copies entire `{RetroBat}\bios\` directory
   - Shows progress bar and current file
   - Preserves directory structure

4. **Updates Configuration**
   - Backs up original `emulatorLauncher.cfg` to `.transfs` extension
   - Updates `bios=` line to point to TransFS location
   - Changes only the BIOS path, leaves all other settings intact

### Path Examples

**Local RetroBat BIOS Directory:**
```
C:\RetroBat\bios\
├── mame\
├── mame2003\
├── dolphin-emu\
└── [other systems]/
```

**TransFS Target Location (Mapped Drive):**
```
U:\RetroBat\bios\
├── mame\
├── mame2003\
├── dolphin-emu\
└── [other systems]/
```

**TransFS Target Location (UNC Path):**
```
\\server\share\RetroBat\bios\
```

## Workflow

### First Time Setup

```
1. Launch Tranfs_Retrobat_Config.exe
   ↓
2. Auto-detect or browse to RetroBat installation
   ↓
3. Select TransFS share (mapped drive, e.g., `U:\` or UNC path, e.g., `\\server\share`)
   ↓
4. Click "Validate Paths" to verify access
   ↓
5. Click "Copy BIOS Files" (may take several minutes)
   ↓
6. Click "Update Configuration" when copy completes
   ↓
7. Original config backed up as: emulatorLauncher.cfg.transfs
   ↓
8. RetroBat now uses TransFS for BIOS - Done!
```

### Rollback (if needed)

**To revert configuration changes:**

```powershell
cd "{RetroBat}\emulationstation\.emulationstation\"
copy emulatorLauncher.cfg.transfs emulatorLauncher.cfg
```

Then restart RetroBat.

## Technical Details

### Project Structure
Located in: `TransFS/tools/Tranfs_Retrobat_Config/`

- `RetroBatHelper.cs` - Registry detection and RetroBat path discovery
- `FileOperationHelper.cs` - File operations and config modifications  
- `MainForm.cs` - Windows Forms user interface
- `Program.cs` - Application entry point
- `Tranfs_Retrobat_Config.csproj` - .NET project configuration
- `build.ps1` - Build automation script
- `README.md` & `SETUP_GUIDE.md` - Documentation

## Troubleshooting

### ".NET SDK not found"

- Download and install .NET 6.0 or higher from https://dotnet.microsoft.com/download
- Restart PowerShell after installation
- Verify: `dotnet --version`

### Build Fails / Compilation Errors

- Ensure .NET 6.0+ is installed
- Try cleaning the build directory:
  ```powershell
  dotnet clean
  dotnet restore
  dotnet build -c Release
  ```

### "RetroBat not found"

- Click "Browse..." next to RetroBat Directory
- Navigate to your RetroBat installation
- Should contain `emulators/` and `emulationstation/` folders

### "TransFS path not writable"

- For **Mapped Drives**: Ensure drive is connected (`net use`)
- For **UNC Paths**: Verify network access and credentials
- Try running as Administrator (right-click exe → Run as Administrator)

### Copy Takes Too Long

- Large BIOS packs (500MB+) can take several minutes
- Check Task Manager → disk I/O to verify process is working
- Don't close the window prematurely

## Advanced: Configuration File Format

### emulatorLauncher.cfg

The utility looks for and updates the `bios=` line:

```
[System]
bios=U:\RetroBat\bios
# or
bios=\\server\share\RetroBat\bios
```

If `bios=` line doesn't exist, it's added at the beginning of the file.

## Technical Details

### Files Created

- **RetroBatConfigSync.exe** - Main executable
- **Dependencies** - .NET runtime (redistributable)

### Permissions Required

- Read: Local RetroBat BIOS directory
- Write: TransFS share location
- Read/Write: RetroBat config directory (for backup/update)

### Backup Files

- **emulatorLauncher.cfg.transfs** - Backup of original config
  - Created only if it doesn't already exist
  - Safe to delete after confirming new config works
  - Actually contains the pre-TransFS configuration

## Support

If issues occur:

1. Check the **Operation Log** window in the application for detailed error messages
2. Verify paths are correct in the Windows path indicators
3. Check file permissions on both source and destination
4. Ensure sufficient disk space on TransFS location
5. Review this README for your specific error scenario

## Next Steps

1. Build the application
2. Run RetroBatConfigSync.exe
3. Configure your RetroBat and TransFS paths
4. Copy BIOS files to the shared store
5. Test RetroBat to confirm BIOS are accessible
6. Commit your changes to the TransFS project (if desired)

---

Part of the TransFS project: https://github.com/yourusername/TransFS

Utility location: `tools/Tranfs_Retrobat_Config/`
