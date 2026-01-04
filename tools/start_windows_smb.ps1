# Start Windows SMB Server (Return to Normal)
# This script restores the Windows Server service to its normal state
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

Write-Host "Restoring Windows SMB Server..." -ForegroundColor Cyan

# Get current service status
$serverService = Get-Service -Name "LanmanServer" -ErrorAction SilentlyContinue

if ($null -eq $serverService) {
    Write-Host "ERROR: Server service not found!" -ForegroundColor Red
    exit 1
}

Write-Host "Current Server service status: $($serverService.Status)" -ForegroundColor Yellow

# Restore the Server service and SMB protocols
try {
    # Re-enable SMB registry settings
    Write-Host "Re-enabling SMB in registry..." -ForegroundColor Cyan
    $regPath = "HKLM:\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters"
    if (Test-Path $regPath) {
        Remove-ItemProperty -Path $regPath -Name "SMB1" -ErrorAction SilentlyContinue
        Remove-ItemProperty -Path $regPath -Name "SMB2" -ErrorAction SilentlyContinue
    }
    
    # Re-enable SMB bindings on network adapters
    Write-Host "Re-enabling SMB bindings on network adapters..." -ForegroundColor Cyan
    $adapters = Get-NetAdapter | Where-Object {$_.Status -eq "Up"}
    foreach ($adapter in $adapters) {
        try {
            Enable-NetAdapterBinding -Name $adapter.Name -ComponentID "ms_server" -ErrorAction SilentlyContinue
        } catch {
            # Ignore errors
        }
    }
    
    # Re-enable SMB protocols
    Write-Host "Re-enabling SMB Server protocols..." -ForegroundColor Cyan
    Set-SmbServerConfiguration -EnableSMB2Protocol $true -Force -ErrorAction Stop
    
    # Set service back to Automatic startup (Windows default)
    Write-Host "Setting Server service to Automatic startup..." -ForegroundColor Cyan
    Set-Service -Name "LanmanServer" -StartupType Automatic -ErrorAction Stop
    
    # Start the Server service
    Write-Host "Starting Server service (LanmanServer)..." -ForegroundColor Cyan
    Start-Service -Name "LanmanServer" -ErrorAction Stop
    
    # Wait a moment for service to fully start
    Start-Sleep -Seconds 2
    
    # Verify service is running
    $serverService = Get-Service -Name "LanmanServer"
    
    Write-Host ""
    Write-Host "SUCCESS: Windows SMB Server restored!" -ForegroundColor Green
    Write-Host "Service Status: $($serverService.Status)" -ForegroundColor Green
    Write-Host "Startup Type: Automatic" -ForegroundColor Green
    Write-Host "SMB protocols have been re-enabled." -ForegroundColor Green
    Write-Host ""
    Write-Host "NOTES:" -ForegroundColor Yellow
    Write-Host "- Windows file sharing is now active" -ForegroundColor White
    Write-Host "- SMB ports (445, 139) are in use by Windows" -ForegroundColor White
    Write-Host "- The service will automatically start on reboot" -ForegroundColor White
    Write-Host ""
    
} catch {
    Write-Host "ERROR: Failed to start service - $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

pause
