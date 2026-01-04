# Stop Windows SMB Server
# This script stops the Windows Server service to free up SMB ports (445, 139)
# Will automatically request Administrator privileges if needed

# Self-elevate if not running as Administrator
if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "Requesting Administrator privileges..." -ForegroundColor Yellow
    try {
        Start-Process powershell.exe -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File","`"$PSCommandPath`"" -Verb RunAs
        exit
    } catch {
        Write-Host "ERROR: Failed to elevate privileges - $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "Please run PowerShell as Administrator manually." -ForegroundColor Yellow
        pause
        exit 1
    }
}

Write-Host "Stopping Windows SMB Server..." -ForegroundColor Cyan

# Get current service status
$serverService = Get-Service -Name "LanmanServer" -ErrorAction SilentlyContinue

if ($null -eq $serverService) {
    Write-Host "ERROR: Server service not found!" -ForegroundColor Red
    exit 1
}

Write-Host "Current Server service status: $($serverService.Status)" -ForegroundColor Yellow

# Stop the Server service and disable SMB drivers
try {
    Write-Host "Stopping Server service (LanmanServer)..." -ForegroundColor Cyan
    Stop-Service -Name "LanmanServer" -Force -ErrorAction Stop
    
    # Set service to Manual startup to prevent Windows from restarting it
    Write-Host "Setting Server service to Manual startup..." -ForegroundColor Cyan
    Set-Service -Name "LanmanServer" -StartupType Manual -ErrorAction Stop
    
    # Disable SMB Server at the protocol level
    Write-Host "Disabling SMB Server protocols..." -ForegroundColor Cyan
    Set-SmbServerConfiguration -EnableSMB1Protocol $false -Force -ErrorAction SilentlyContinue
    Set-SmbServerConfiguration -EnableSMB2Protocol $false -Force -ErrorAction Stop
    
    # Disable SMB bindings on all network adapters
    Write-Host "Disabling SMB bindings on network adapters..." -ForegroundColor Cyan
    $adapters = Get-NetAdapter | Where-Object {$_.Status -eq "Up"}
    foreach ($adapter in $adapters) {
        try {
            Disable-NetAdapterBinding -Name $adapter.Name -ComponentID "ms_server" -ErrorAction SilentlyContinue
        } catch {
            # Ignore errors for adapters that don't have the binding
        }
    }
    
    # Disable SMB driver at registry level (takes effect after reboot)
    Write-Host "Disabling SMB driver in registry..." -ForegroundColor Cyan
    $regPath = "HKLM:\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters"
    if (-not (Test-Path $regPath)) {
        New-Item -Path $regPath -Force | Out-Null
    }
    Set-ItemProperty -Path $regPath -Name "SMB1" -Value 0 -Type DWord -Force
    Set-ItemProperty -Path $regPath -Name "SMB2" -Value 0 -Type DWord -Force
    
    # Give the system a moment to release the port
    Write-Host "Waiting for port to be released..." -ForegroundColor Cyan
    Start-Sleep -Seconds 3
    
    Write-Host ""
    Write-Host "SUCCESS: Windows SMB Server stopped!" -ForegroundColor Green
    Write-Host "The Server service is now set to Manual startup." -ForegroundColor Green
    Write-Host "SMB protocols have been disabled." -ForegroundColor Green
    Write-Host ""
    
    # Check port status
    Write-Host "Checking port 445 status..." -ForegroundColor Cyan
    $port445 = Get-NetTCPConnection -LocalPort 445 -ErrorAction SilentlyContinue
    if ($null -eq $port445) {
        Write-Host "Port 445 is now FREE" -ForegroundColor Green
        Write-Host ""
        Write-Host "You can now start your custom SMB server!" -ForegroundColor Green
    } else {
        Write-Host "WARNING: Port 445 is still in use by System (PID 4)" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "IMPORTANT: To fully release port 445, you must REBOOT your computer." -ForegroundColor Red
        Write-Host ""
        Write-Host "Why? The SMB kernel driver (srv2.sys) holds port 445 and can only" -ForegroundColor Yellow
        Write-Host "be unloaded during system restart. This is a Windows kernel limitation." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "OPTIONS:" -ForegroundColor Cyan
        Write-Host "1. REBOOT NOW - Port 445 will be free after restart" -ForegroundColor White
        Write-Host "2. Use a different port - Modify your Docker config to use port 4450" -ForegroundColor White
        Write-Host "   (then connect via \\localhost:4450 instead)" -ForegroundColor White
        Write-Host ""
        $rebootNow = Read-Host "Would you like to reboot now? (y/N)"
        if ($rebootNow -eq "y" -or $rebootNow -eq "Y") {
            Write-Host "Rebooting in 10 seconds... (Press Ctrl+C to cancel)" -ForegroundColor Yellow
            Start-Sleep -Seconds 10
            Restart-Computer -Force
            exit
        }
    }
    
    Write-Host ""
    Write-Host "NOTES:" -ForegroundColor Yellow
    Write-Host "- Windows file sharing is disabled until you run start_windows_smb.ps1" -ForegroundColor White
    Write-Host "- Service is set to Manual (won't auto-start on reboot)" -ForegroundColor White
    Write-Host "- To prevent port reclamation, keep this service stopped" -ForegroundColor White
    Write-Host ""
} catch {
    Write-Host "ERROR: Failed to stop service - $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

pause
