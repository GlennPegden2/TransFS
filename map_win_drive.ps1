Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RegistryRoot = "HKCU:\Software\TransFS\RetroBatSync"

function Write-Info([string]$Message) { Write-Host "[INFO] $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "[ OK ] $Message" -ForegroundColor Green }
function Write-WarnMsg([string]$Message) { Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Write-ErrMsg([string]$Message) { Write-Host "[ERR ] $Message" -ForegroundColor Red }

function Get-StoredSettings {
	$result = @{}
	
	if (-not (Test-Path $RegistryRoot)) {
		return $result
	}

	try {
		$props = Get-ItemProperty -Path $RegistryRoot -ErrorAction SilentlyContinue
		if (-not $props) {
			return $result
		}
		
		# Safely access each property using PSObject.Properties
		$propNames = @('Mode', 'ShareRoot', 'DriveLetter', 'ServerName', 'ShareName', 'SmbPort')
		foreach ($propName in $propNames) {
			$propValue = $props.PSObject.Properties.Item($propName)
			if ($propValue -ne $null) {
				$result[$propName] = $propValue.Value
			}
		}
	}
	catch {
		# If any error occurs reading registry, return empty defaults
		return $result
	}

	return $result
}

function Save-StoredSettings([hashtable]$Settings) {
	if (-not (Test-Path $RegistryRoot)) {
		New-Item -Path $RegistryRoot -Force | Out-Null
	}

	foreach ($key in $Settings.Keys) {
		New-ItemProperty -Path $RegistryRoot -Name $key -Value $Settings[$key] -PropertyType String -Force | Out-Null
	}
}

function Prompt-WithDefault([string]$Prompt, [string]$Default = "") {
	if ([string]::IsNullOrWhiteSpace($Default)) {
		return Read-Host $Prompt
	}

	$value = Read-Host "$Prompt [$Default]"
	if ([string]::IsNullOrWhiteSpace($value)) {
		return $Default
	}
	return $value
}

function Select-FolderDialog([string]$Description, [string]$InitialPath = "") {
	Add-Type -AssemblyName System.Windows.Forms | Out-Null
	$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
	$dialog.Description = $Description
	if (-not [string]::IsNullOrWhiteSpace($InitialPath) -and (Test-Path $InitialPath)) {
		$dialog.SelectedPath = $InitialPath
	}

	$result = $dialog.ShowDialog()
	if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
		return $dialog.SelectedPath
	}
	return $null
}

function Test-PathWritable([string]$PathToTest) {
	try {
		if (-not (Test-Path $PathToTest -PathType Container)) {
			return $false
		}
		$testFile = Join-Path $PathToTest ("transfs_write_test_" + [guid]::NewGuid().ToString("N") + ".tmp")
		Set-Content -Path $testFile -Value "ok" -Encoding UTF8
		Remove-Item -Path $testFile -Force
		return $true
	}
	catch {
		return $false
	}
}

function Test-DriveLetterAvailable([string]$Letter) {
	$normalized = $Letter.Trim().TrimEnd(':').ToUpperInvariant()
	if ($normalized -notmatch '^[A-Z]$') {
		return $false
	}

	$drive = Get-PSDrive -Name $normalized -ErrorAction SilentlyContinue
	return $null -eq $drive
}

function Get-RetroBatInstallDir {
	$regCandidates = @(
		@{ Hive = "HKLM:"; SubKey = "SOFTWARE\RetroBat" },
		@{ Hive = "HKLM:"; SubKey = "SOFTWARE\WOW6432Node\RetroBat" },
		@{ Hive = "HKCU:"; SubKey = "SOFTWARE\RetroBat" }
	)

	foreach ($candidate in $regCandidates) {
		$keyPath = Join-Path $candidate.Hive $candidate.SubKey
		if (Test-Path $keyPath) {
			$item = Get-ItemProperty -Path $keyPath
			foreach ($name in @("InstallPath", "RootPath", "Path")) {
				if ($item.PSObject.Properties.Name -contains $name) {
					$pathValue = [string]$item.$name
					if (-not [string]::IsNullOrWhiteSpace($pathValue) -and (Test-Path $pathValue)) {
						if (Test-Path (Join-Path $pathValue "emulationstation\emulatorLauncher.cfg")) {
							return $pathValue
						}
					}
				}
			}
		}
	}

	$fallbacks = @("C:\RetroBat", "D:\RetroBat", "E:\Games\RetroBat", "E:\RetroBat")
	foreach ($path in $fallbacks) {
		if (Test-Path (Join-Path $path "emulationstation\emulatorLauncher.cfg")) {
			return $path
		}
	}

	return $null
}

function Resolve-TransFSShare([hashtable]$Defaults) {
	# Ensure Defaults is initialized
	if (-not $Defaults) {
		$Defaults = @{}
	}
	
	while ($true) {
		Write-Host ""
		Write-Host "Select TransFS path type:" -ForegroundColor White
		Write-Host "  1) Existing mapped drive" -ForegroundColor White
		Write-Host "  2) UNC path (standard SMB port)" -ForegroundColor White
		Write-Host "  3) UNC path on non-standard SMB port" -ForegroundColor White

		$defaultMode = if ($Defaults['Mode']) { [string]$Defaults['Mode'] } else { "1" }
		$mode = Prompt-WithDefault "Choose 1/2/3" $defaultMode

		switch ($mode) {
			"1" {
				$defaultShareRoot = if ($Defaults['ShareRoot']) { [string]$Defaults['ShareRoot'] } else { "" }
				$useBrowser = Prompt-WithDefault "Use folder browser? (Y/N)" "Y"
				if ($useBrowser.ToUpperInvariant() -eq "Y") {
					$selected = Select-FolderDialog "Select mapped drive root or share folder" $defaultShareRoot
					if ($selected) {
						$shareRoot = $selected
					}
					else {
						Write-WarnMsg "No folder selected."
						continue
					}
				}
				else {
					$shareRoot = Prompt-WithDefault "Enter mapped drive path (example: U:\\ or U:\\TransFS)" $defaultShareRoot
				}

				if (-not (Test-Path $shareRoot -PathType Container)) {
					Write-ErrMsg "Path does not exist: $shareRoot"
					continue
				}

				if (-not (Test-PathWritable $shareRoot)) {
					Write-ErrMsg "Path is not writable: $shareRoot"
					continue
				}

				return @{
					Mode = "1"
					ShareRoot = (Resolve-Path $shareRoot).Path
					DriveLetter = ""
					ServerName = ""
					ShareName = ""
					SmbPort = ""
				}
			}
			"2" {
				$defaultShareRoot = if ($Defaults['ShareRoot']) { [string]$Defaults['ShareRoot'] } else { "\\server\share" }
				$shareRoot = Prompt-WithDefault "Enter UNC path (example: \\server\share)" $defaultShareRoot

				if ($shareRoot -notmatch '^\\\\[^\\]+\\[^\\]+') {
					Write-ErrMsg "Invalid UNC format."
					continue
				}
				if ($shareRoot -match ':[0-9]+') {
					Write-WarnMsg "UNC with custom port requires a mapped drive. Choose option 3."
					continue
				}
				if (-not (Test-Path $shareRoot -PathType Container)) {
					Write-ErrMsg "UNC path not reachable: $shareRoot"
					continue
				}
				if (-not (Test-PathWritable $shareRoot)) {
					Write-ErrMsg "UNC path is not writable: $shareRoot"
					continue
				}

				return @{
					Mode = "2"
					ShareRoot = $shareRoot.TrimEnd('\\')
					DriveLetter = ""
					ServerName = ""
					ShareName = ""
					SmbPort = ""
				}
			}
			"3" {
				Write-Info "Non-standard SMB port requires mapping to a drive letter."
				Write-Host ""

				$defaultDrive = if ($Defaults['DriveLetter']) { [string]$Defaults['DriveLetter'] } else { "U" }
				while ($true) {
					$driveLetter = Prompt-WithDefault "Enter unused drive letter (example: U)" $defaultDrive
					$driveLetter = $driveLetter.Trim().TrimEnd(':').ToUpperInvariant()
					if (-not (Test-DriveLetterAvailable $driveLetter)) {
						Write-ErrMsg "Drive letter is invalid or already in use: ${driveLetter}:"
						continue
					}
					break
				}

				$defaultServerName = if ($Defaults.ContainsKey("ServerName") -and -not [string]::IsNullOrWhiteSpace([string]$Defaults['ServerName'])) { [string]$Defaults['ServerName'] } else { "" }
				$defaultShareName = if ($Defaults.ContainsKey("ShareName") -and -not [string]::IsNullOrWhiteSpace([string]$Defaults['ShareName'])) { [string]$Defaults['ShareName'] } else { "TransFS" }
				$defaultSmbPort = if ($Defaults.ContainsKey("SmbPort") -and -not [string]::IsNullOrWhiteSpace([string]$Defaults['SmbPort'])) { [string]$Defaults['SmbPort'] } else { "3445" }

				$serverName = Prompt-WithDefault "Enter SMB server name" $defaultServerName
				$shareName = Prompt-WithDefault "Enter share name" $defaultShareName
				$smbPort = Prompt-WithDefault "Enter SMB TCP port" $defaultSmbPort

				if ($smbPort -notmatch '^[0-9]+$') {
					Write-ErrMsg "Port must be numeric."
					continue
				}

				$remotePath = "\\$serverName\$shareName"
				$localPath = "${driveLetter}:"

				try {
				Write-Info "Mapping $localPath to $remotePath on port $smbPort"
				Write-Host ""
				Write-Host "Credentials Required" -ForegroundColor Cyan
				Write-Host "  • TransFS SMB credentials (configured in app.yaml)" -ForegroundColor Gray
				Write-Host "  • Default: root / 1" -ForegroundColor Gray
				Write-Host ""
				$creds = Get-Credential -Message "Enter TransFS SMB credentials"
				
				if (-not $creds) {
					Write-ErrMsg "Credentials required for SMB access"
					continue
				}
				
				New-SmbGlobalMapping -LocalPath $localPath -RemotePath $remotePath -TcpPort ([int]$smbPort) -Credential $creds -Persistent $true -ErrorAction Stop | Out-Null
			}
			catch {
				Write-ErrMsg "Failed to map drive: $($_.Exception.Message)"
				continue
			}
				$shareRoot = "$localPath\"
				if (-not (Test-Path $shareRoot -PathType Container)) {
					Write-ErrMsg "Mapped drive is not accessible: $shareRoot"
					continue
				}
				if (-not (Test-PathWritable $shareRoot)) {
					Write-WarnMsg "Mapped drive root is not writable: $shareRoot"
					Write-WarnMsg "Continuing - script will validate write access at the BIOS target folder."
				}

				return @{
					Mode = "3"
					ShareRoot = $shareRoot
					DriveLetter = $driveLetter
					ServerName = $serverName
					ShareName = $shareName
					SmbPort = $smbPort
				}
			}
			default {
				Write-WarnMsg "Please choose 1, 2, or 3."
			}
		}
	}
}

function Copy-BiosWithProgress([string]$SourceDir, [string]$DestinationDir) {
	$files = Get-ChildItem -Path $SourceDir -Recurse -File
	if ($files.Count -eq 0) {
		throw "No files found under source BIOS directory: $SourceDir"
	}

	$index = 0
	foreach ($file in $files) {
		$index++
		$relative = $file.FullName.Substring($SourceDir.Length).TrimStart('\\')
		$targetPath = Join-Path $DestinationDir $relative
		$targetFolder = Split-Path -Parent $targetPath
		if (-not (Test-Path $targetFolder)) {
			New-Item -Path $targetFolder -ItemType Directory -Force | Out-Null
		}

		Copy-Item -Path $file.FullName -Destination $targetPath -Force

		$percent = [int](($index / $files.Count) * 100)
		Write-Progress -Activity "Copying RetroBat BIOS" -Status "$index / $($files.Count): $relative" -PercentComplete $percent
	}
	Write-Progress -Activity "Copying RetroBat BIOS" -Completed
}

function Update-RetroBatConfig([string]$RetroBatDir, [string]$BiosPath) {
	$configPath = Join-Path $RetroBatDir "emulationstation\emulatorLauncher.cfg"
	if (-not (Test-Path $configPath)) {
		throw "Cannot find emulatorLauncher.cfg at $configPath"
	}

	$backupPath = "$configPath.transfs"
	if (-not (Test-Path $backupPath)) {
		Copy-Item -Path $configPath -Destination $backupPath -Force
		Write-Ok "Backup created: $backupPath"
	}
	else {
		Write-Info "Backup already exists: $backupPath"
	}

	$lines = Get-Content -Path $configPath
	$updated = $false
	for ($i = 0; $i -lt $lines.Count; $i++) {
		if ($lines[$i] -match '^\s*bios=') {
			$lines[$i] = "bios=$BiosPath"
			$updated = $true
			break
		}
	}

	if (-not $updated) {
		$lines = @("bios=$BiosPath") + $lines
	}

	Set-Content -Path $configPath -Value $lines -Encoding UTF8
	Write-Ok "Updated bios= in $configPath"
}

try {
	Write-Host ""
	Write-Host "TransFS RetroBat BIOS Setup" -ForegroundColor White
	Write-Host "==========================" -ForegroundColor White

	Write-Info "Loading stored settings from registry..."
	$defaults = Get-StoredSettings
	
	if ($defaults['ShareRoot']) {
		Write-Info "Found saved default share path: $($defaults['ShareRoot'])"
	}

	$shareConfig = Resolve-TransFSShare -Defaults $defaults
	Save-StoredSettings -Settings $shareConfig
	Write-Ok "Saved share settings to registry: HKCU\\Software\\TransFS\\RetroBatSync"

	$targetBiosDir = Join-Path $shareConfig['ShareRoot'] "RetroBat\bios"
	if (Test-Path $targetBiosDir -PathType Container) {
		Write-Ok "Target BIOS folder already exists: $targetBiosDir"
		Write-Info "Nothing to copy."
		exit 0
	}

	$retroBatDir = Get-RetroBatInstallDir
	if ($retroBatDir) {
		Write-Info "Detected RetroBat install: $retroBatDir"
	}

	while (-not $retroBatDir) {
		$browse = Prompt-WithDefault "RetroBat install not auto-detected. Use folder browser? (Y/N)" "Y"
		if ($browse.ToUpperInvariant() -eq "Y") {
			$selected = Select-FolderDialog "Select RetroBat install folder"
			if ($selected) {
				$retroBatDir = $selected
			}
		}
		else {
			$retroBatDir = Read-Host "Enter full RetroBat install path"
		}

		if (-not (Test-Path (Join-Path $retroBatDir "emulationstation\emulatorLauncher.cfg"))) {
			Write-ErrMsg "Invalid RetroBat path. emulatorLauncher.cfg not found."
			$retroBatDir = $null
		}
	}

	$sourceBiosDir = Join-Path $retroBatDir "bios"
	if (-not (Test-Path $sourceBiosDir -PathType Container)) {
		throw "RetroBat BIOS folder does not exist: $sourceBiosDir"
	}

	New-Item -Path $targetBiosDir -ItemType Directory -Force | Out-Null
	Write-Info "Copying BIOS from $sourceBiosDir"
	Write-Info "Copying BIOS to   $targetBiosDir"

	Copy-BiosWithProgress -SourceDir $sourceBiosDir -DestinationDir $targetBiosDir

	$srcCount = (Get-ChildItem -Path $sourceBiosDir -Recurse -File).Count
	$dstCount = (Get-ChildItem -Path $targetBiosDir -Recurse -File).Count

	if ($dstCount -lt $srcCount) {
		throw "Copy verification failed. Source files: $srcCount, Destination files: $dstCount"
	}

	Write-Ok "Copy verified. Source files: $srcCount, Destination files: $dstCount"

	$configuredBiosPath = Join-Path $shareConfig['ShareRoot'] "RetroBat\bios"
	$updateConfig = Prompt-WithDefault "Update local RetroBat config to use '$configuredBiosPath'? (Y/N)" "Y"
	if ($updateConfig.ToUpperInvariant() -eq "Y") {
		Update-RetroBatConfig -RetroBatDir $retroBatDir -BiosPath $configuredBiosPath
	}
	else {
		Write-Info "Skipped config update."
	}

	Write-Host ""
	Write-Ok "Done."
}
catch {
	Write-Host ""
	Write-ErrMsg $_.Exception.Message
	exit 1
}