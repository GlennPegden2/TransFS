# Configure NetBIOS Settings for Docker/SMB Compatibility
# Disables NetBIOS on virtual adapters, enables on physical LAN adapter
# Run as Administrator

# Check for admin privileges
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

Write-Host "Configuring NetBIOS settings..." -ForegroundColor Cyan
Write-Host ""

# Get all active network adapters
$adapters = Get-NetAdapter | Where-Object {$_.Status -eq "Up"}

foreach ($adapter in $adapters) {
    $adapterName = $adapter.Name
    $adapterDesc = $adapter.InterfaceDescription
    
    # Get the adapter's GUID for registry access
    $adapterGuid = $adapter.InterfaceGuid
    $regPath = "HKLM:\SYSTEM\CurrentControlSet\Services\NetBT\Parameters\Interfaces\Tcpip_$adapterGuid"
    
    # Determine if this is a virtual/Docker adapter or physical
    $isVirtual = $adapterDesc -match "Virtual|Hyper-V|VirtualBox|VMware|Docker"
    
    if ($isVirtual) {
        # Disable NetBIOS on virtual adapters
        Write-Host "[$adapterName] $adapterDesc" -ForegroundColor Yellow
        Write-Host "  → Disabling NetBIOS (virtual adapter)" -ForegroundColor Yellow
        
        if (Test-Path $regPath) {
            Set-ItemProperty -Path $regPath -Name "NetbiosOptions" -Value 2 -Type DWord
        } else {
            Write-Host "  → Warning: Registry path not found, skipping" -ForegroundColor DarkYellow
        }
    } else {
        # Enable NetBIOS on physical adapters
        Write-Host "[$adapterName] $adapterDesc" -ForegroundColor Green
        Write-Host "  → Enabling NetBIOS (physical adapter)" -ForegroundColor Green
        
        if (Test-Path $regPath) {
            Set-ItemProperty -Path $regPath -Name "NetbiosOptions" -Value 1 -Type DWord
        } else {
            Write-Host "  → Warning: Registry path not found, skipping" -ForegroundColor DarkYellow
        }
    }
    Write-Host ""
}

Write-Host ""
Write-Host "SUCCESS: NetBIOS configuration complete!" -ForegroundColor Green
Write-Host ""
Write-Host "IMPORTANT: You must restart network adapters or reboot for changes to take effect." -ForegroundColor Yellow
Write-Host ""

$restart = Read-Host "Would you like to restart network adapters now? (y/N)"
if ($restart -eq "y" -or $restart -eq "Y") {
    Write-Host "Restarting network adapters..." -ForegroundColor Cyan
    
    foreach ($adapter in $adapters) {
        Write-Host "  Restarting $($adapter.Name)..." -ForegroundColor White
        Restart-NetAdapter -Name $adapter.Name -Confirm:$false
        Start-Sleep -Seconds 2
    }
    
    Write-Host ""
    Write-Host "Network adapters restarted!" -ForegroundColor Green
} else {
    Write-Host "Please restart adapters manually or reboot when convenient." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Testing NetBIOS resolution..." -ForegroundColor Cyan
Write-Host "Your hostname: $(hostname)" -ForegroundColor White
Write-Host "Physical LAN IP should now be the primary NetBIOS address." -ForegroundColor White
Write-Host ""

pause
