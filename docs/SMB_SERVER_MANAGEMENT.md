# Windows SMB Server Management Guide

## Quick Start

### Stop Windows SMB Server
```powershell
# Right-click PowerShell -> Run as Administrator
.\stop_windows_smb.ps1
```

### Start Your Own SMB Server
After running `stop_windows_smb.ps1`, you can start your own SMB server (e.g., via Docker):
```powershell
docker-compose up -d
```

### Restore Windows SMB Server
```powershell
# Right-click PowerShell -> Run as Administrator
.\start_windows_smb.ps1
```

## How It Works

### stop_windows_smb.ps1
1. **Stops** the Windows Server service (LanmanServer)
2. **Sets startup type to Manual** - prevents automatic restart
3. **Frees ports 445 and 139** for your custom SMB server
4. **Checks port availability** after stopping

### start_windows_smb.ps1
1. **Sets startup type back to Automatic** - Windows default behavior
2. **Starts** the Server service
3. **Verifies** the service is running properly

## Preventing Windows Port Reclamation

### The Problem
Windows can periodically try to reclaim SMB ports (445, 139) even after you've stopped the service if certain conditions are met.

### Solutions

#### 1. Keep the Service Set to Manual (Recommended for Development)
The `stop_windows_smb.ps1` script sets the service to Manual, which means:
- ✅ Service won't start automatically on reboot
- ✅ Windows won't auto-restart the service
- ✅ You maintain full control
- ⚠️ **Important**: You must manually run `start_windows_smb.ps1` to restore file sharing

#### 2. Disable the Service Completely (More Aggressive)
If you want even stronger protection, you can disable the service entirely:

```powershell
# Run as Administrator
Set-Service -Name "LanmanServer" -StartupType Disabled
Stop-Service -Name "LanmanServer" -Force
```

To restore:
```powershell
# Run as Administrator
Set-Service -Name "LanmanServer" -StartupType Automatic
Start-Service -Name "LanmanServer"
```

#### 3. Use Docker Port Binding Strategy
When running your SMB server in Docker, use explicit port binding:

```yaml
# docker-compose.yml
services:
  samba:
    ports:
      - "445:445"   # SMB
      - "139:139"   # NetBIOS
```

Docker will fail to start if the ports are still in use, alerting you immediately.

#### 4. Monitor Port Usage
Create a simple monitoring script to alert you if Windows reclaims the port:

```powershell
# check_smb_port.ps1
$port445 = Get-NetTCPConnection -LocalPort 445 -ErrorAction SilentlyContinue
if ($port445) {
    $proc = Get-Process -Id $port445[0].OwningProcess -ErrorAction SilentlyContinue
    Write-Host "Port 445 in use by: $($proc.ProcessName) (PID: $($proc.Id))"
} else {
    Write-Host "Port 445 is FREE"
}
```

## Reboot Behavior

### Current Setup (After running stop_windows_smb.ps1)
- ✅ Rebooting does **NOT** restart the Windows SMB server (it's set to Manual)
- ⚠️ You must manually run `start_windows_smb.ps1` to restore file sharing

### If You Want Auto-Restore on Reboot
Simply run `start_windows_smb.ps1` - it sets the service back to Automatic startup.

## Troubleshooting

### Port 445 Still in Use After Stopping Service
```powershell
# Find what's using port 445
Get-NetTCPConnection -LocalPort 445 | ForEach-Object {
    $proc = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        LocalPort = $_.LocalPort
        State = $_.State
        ProcessName = $proc.ProcessName
        PID = $proc.Id
    }
}

# Force kill the process (use with caution!)
Stop-Process -Id <PID> -Force
```

### Service Won't Stop
Some dependencies might prevent stopping. Check what's dependent on the Server service:
```powershell
Get-Service -Name "LanmanServer" | Select-Object -ExpandProperty DependentServices
```

### "Access Denied" Error
- Ensure you're running PowerShell as Administrator
- Right-click PowerShell icon -> "Run as Administrator"

### Docker Can't Bind to Port 445
```bash
# Check if port is truly free
netstat -ano | findstr :445

# If something is using it, identify and stop it
Get-NetTCPConnection -LocalPort 445
```

## Best Practices for Development

1. **Use the scripts** - Don't manually manage the service; the scripts handle edge cases
2. **Check port availability** before starting your SMB server
3. **Stop your SMB server first** before running `start_windows_smb.ps1`
4. **Document your workflow** - Add these commands to your project's README
5. **Consider automation** - Add pre-docker-compose checks in your workflow

## Example Development Workflow

```powershell
# 1. Stop Windows SMB
.\stop_windows_smb.ps1

# 2. Start your development SMB server
docker-compose up -d

# 3. Do your development work...

# 4. Stop your SMB server
docker-compose down

# 5. Restore Windows SMB (if needed)
.\start_windows_smb.ps1
```

## Security Considerations

- **File sharing is disabled** when Windows SMB is stopped
- Other computers won't be able to access shared folders on your PC
- Your network discovery may be affected
- This is generally safe for development but plan accordingly

## Additional Resources

- [Windows Server Service Documentation](https://docs.microsoft.com/en-us/windows-server/storage/file-server/file-server-smb-overview)
- [Docker Compose Networking](https://docs.docker.com/compose/networking/)
