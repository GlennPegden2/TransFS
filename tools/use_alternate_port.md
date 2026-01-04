# Using an Alternate Port for SMB (Workaround for Port 445)

Since Windows kernel holds port 445 and won't release it without a reboot, you can run your SMB server on a different port.

## Solution: Use Port 4450 (or any other port)

### 1. Modify docker-compose.yml

```yaml
services:
  samba:
    ports:
      - "4450:445"  # Map host port 4450 to container port 445
      - "139:139"   # Keep NetBIOS as-is
```

### 2. Connect Using the Alternate Port

Windows SMB client supports custom ports:

```powershell
# Using net use
net use Z: \\localhost:4450\share /user:username password

# Or via Explorer address bar
\\localhost:4450\share
```

### 3. For MiSTer/RetroArch Devices

Most SMB clients support custom ports in the format:
```
smb://hostname:4450/share
```

## Pros and Cons

### Pros
✅ No reboot required
✅ Windows SMB stays functional
✅ Works immediately
✅ Both servers can run simultaneously

### Cons
⚠️ Non-standard port (some older clients don't support it)
⚠️ Must specify port in connection string
⚠️ Some embedded devices might not support custom ports

## Testing the Connection

```powershell
# Start your SMB server on alternate port
docker-compose up -d

# Test connection
Test-NetConnection -ComputerName localhost -Port 4450

# Mount it
net use Z: \\localhost:4450\share
```

## Alternative: Run SMB on Linux/WSL2

If you need port 445 specifically, consider:
1. Use WSL2 to run your SMB server
2. WSL2 can bind to port 445 independently from Windows
3. Configure port forwarding from WSL2 to Windows host

## When to Use This vs Rebooting

**Use alternate port if:**
- You need Windows file sharing to stay active
- You're testing/developing frequently
- Your clients support custom ports
- You want to avoid system disruption

**Reboot to free port 445 if:**
- Clients don't support custom ports
- You need true port 445 compatibility
- This is a production/final deployment
- You don't need Windows file sharing
