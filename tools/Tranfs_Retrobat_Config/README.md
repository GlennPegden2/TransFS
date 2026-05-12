# Tranfs_Retrobat_Config

A Windows utility to synchronize RetroBat BIOS files to a TransFS share and update local RetroBat configuration automatically.

## Features

- **Auto-detect RetroBat Installation**: Searches registry and common paths for RetroBat installation
- **Path Validation**: Confirms both RetroBat and TransFS paths exist and are accessible
- **BIOS Copy with Progress**: Copies all BIOS files from RetroBat to TransFS with real-time progress tracking
- **Configuration Backup**: Automatically backs up original config to `.transfs` extension before modification
- **Config Update**: Updates `emulatorLauncher.cfg` to point `bios=` line to the TransFS share

## Usage

### Building

```
dotnet build -c Release
```

Produces: `Tranfs_Retrobat_Config.exe` in the `bin/Release/net6.0-windows/` folder

### Running

1. Launch `Tranfs_Retrobat_Config.exe`
2. **RetroBat Installation Directory**: 
   - Should auto-detect from registry or common paths
   - Click "Browse..." to manually select if needed
3. **TransFS Share Location**:
   - Enter the mapped drive (e.g., `U:\`) or UNC path (e.g., `\\server\share`)
   - This is where `RetroBat/bios/` subdirectory will be created
   - Click "Browse..." to browse to the location
4. **Validate Paths**: Click to verify both directories exist and are accessible
5. **Copy BIOS Files**: Initiates recursive copy of all BIOS files with progress tracking
6. **Update Configuration**: 
   - Backs up original `emulatorLauncher.cfg` to `.transfs` extension
   - Updates `bios=` line to point to TransFS location
   - Original config preserved for rollback if needed

## File Operations

### BIOS Copy
- Copies entire `{RetroBat}/bios/` directory tree to `{TransFS}/RetroBat/bios/`
- Preserves directory structure and file attributes
- Shows progress and current file being copied

### Configuration Update
- Target: `{RetroBat}/emulationstation/.emulationstation/emulatorLauncher.cfg`
- Finds and updates line: `bios={new_transfs_bios_path}`
- Adds `bios=` line if it doesn't exist
- Backup created at: `emulatorLauncher.cfg.transfs` (only first time)

## Requirements

- Windows (tested on Windows 10/11)
- .NET 6.0 Runtime or higher
- Read access to RetroBat BIOS directory
- Write access to TransFS share path
- Administrator may be required for some network paths

## Troubleshooting

**"RetroBat installation not found automatically"**
- Click "Browse..." next to RetroBat Directory
- Navigate to your RetroBat installation folder (usually `C:\RetroBat` or similar)
- Folder should contain `emulators/` and `emulationstation/` subdirectories

**"Directory is not writable"**
- Ensure you have write permissions to the TransFS share
- For mapped drives: Verify the drive is connected
- For UNC paths: Confirm you have network access and appropriate permissions
- Try running as Administrator if issues persist

**"BIOS directory not found"**
- Verify RetroBat directory selection is correct
- Should have a `bios/` subdirectory
- Check file permissions if directory exists but appears inaccessible

**Copy appears to hang**
- Large BIOS packs may take several minutes
- Check Windows Task Manager to confirm process is running
- Check disk I/O if percentage isn't increasing

## Configuration Rollback

If you need to revert the configuration changes:

1. Restore the backup file:
   ```
   copy emulatorLauncher.cfg.transfs emulatorLauncher.cfg
   ```

2. Or manually edit `emulatorLauncher.cfg`:
   - Find the `bios=` line
   - Change it back to your original BIOS path

## Notes

- The application creates backups with `.transfs` extension (not `.bak` or `.backup`)
- Subsequent runs skip backup creation if already exists
- Progress bar updates in real-time during file copy
- Operation log shows detailed status of each step
- All operations are reported in the log window for troubleshooting

## Project Structure

```
TransFS/
└── tools/
    └── Tranfs_Retrobat_Config/     # This utility
        ├── RetroBatHelper.cs        # Registry detection and path discovery
        ├── FileOperationHelper.cs   # File copy and config updates
        ├── MainForm.cs              # Windows Forms UI
        ├── Program.cs               # Entry point
        ├── README.md                # This file
        ├── SETUP_GUIDE.md           # Build and setup instructions
        ├── build.ps1                # PowerShell build script
        └── Tranfs_Retrobat_Config.csproj  # Project configuration
```
