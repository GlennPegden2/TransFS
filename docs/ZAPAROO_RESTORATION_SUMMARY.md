# Zaparoo Launch Feature - Restoration Summary

## Status: FEATURE MISSING FROM CURRENT CODEBASE

The Zaparoo remote launch feature was implemented in commit `120261b` but is **missing from the current codebase**. The feature allowed users to launch games/ROMs remotely on MiSTer and other clients running the Zaparoo service.

## What Was Lost

### 1. Documentation (Recovered)
✅ **Restored Files:**
- `docs/ZAPAROO_FEATURE.md` - Comprehensive feature documentation
- `docs/ZAPAROO_IMPLEMENTATION.md` - Implementation summary
- `docs/ZAPAROO_QUICKSTART.md` - Quick start guide

### 2. Backend API Endpoints (Missing)
❌ **Need to Restore:**
- `GET /api/zaparoo/status` - Check Zaparoo configuration and connectivity
- `POST /api/zaparoo/launch` - Launch a file using Zaparoo

### 3. Frontend UI Components (Missing)
❌ **Need to Restore:**
- Launch buttons (🚀) on files in Browse Virtual tab
- Multi-client selector modal
- Toast notifications for launch feedback
- Zaparoo status checking on page load

### 4. Configuration (Missing)
❌ **Need to Add to `app/config/app.yaml`:**
```yaml
zaparoo:
  clients:
    - name: "MiSTer"
      enabled: true
      host: "192.168.1.100"
      port: 7497
      mount_path: "/media/fat/cifs"
```

## Feature Overview

### What It Did
- Added 🚀 launch buttons next to files in the Browse Virtual tab
- Clicking a button would send the file path to a Zaparoo service running on MiSTer/other clients
- Zaparoo would then launch the game/ROM in the appropriate core
- Supported multiple Zaparoo clients with a dropdown selector
- Visual feedback: ⏳ loading → ✔ success or ✖ error
- Toast notifications for user feedback

### Architecture
1. **Frontend**: JavaScript checks Zaparoo status on page load
2. **Frontend**: Adds launch buttons to file entries if Zaparoo is configured
3. **Backend**: `/api/zaparoo/launch` endpoint receives file path and client name
4. **Backend**: Converts TransFS path to client mount path
5. **Backend**: Sends ZapScript command to Zaparoo JSON-RPC API
6. **Backend**: Returns success/error to frontend
7. **Frontend**: Shows visual feedback and toast notification

## Implementation Details from Original Code

### Backend API (app/api.py)

#### 1. Zaparoo Status Endpoint
```python
@app.get("/api/zaparoo/status")
def zaparoo_status():
    """Check Zaparoo configuration and connectivity for all clients."""
    # - Reads zaparoo.clients from app.yaml
    # - Tests connectivity to each configured client
    # - Returns list of clients with enabled/reachable status
```

#### 2. Zaparoo Launch Endpoint
```python
class ZaparooLaunchRequest(BaseModel):
    file_path: str
    client_name: str = "MiSTer"

@app.post("/api/zaparoo/launch")
def zaparoo_launch(request: ZaparooLaunchRequest):
    """Launch a file/game using Zaparoo remote launching."""
    # - Validates client exists and is enabled
    # - Converts TransFS path to client mount path
    # - Calls Zaparoo JSON-RPC API with ZapScript
    # - Handles enabling/disabling runZapScript setting
    # - Returns success/error response
```

**Key Path Conversion:**
- Input: `/mnt/transfs/MiSTer/AcornElectron/Tapes/file.uef`
- Output: `/media/fat/cifs/AcornElectron/Tapes/file.uef`
- Logic: Remove `/mnt/transfs/{client_name}/`, prepend `mount_path`

**Zaparoo Communication:**
- Uses JSON-RPC 2.0 API at `http://host:port/api/v0.1`
- Methods used:
  - `settings` - Check if runZapScript is enabled
  - `settings.update` - Enable/disable runZapScript
  - `run` - Execute ZapScript command
- ZapScript format: `**launch:{path}` or `**launch.path:{path}`
- Automatically enables runZapScript if disabled, then restores setting after launch

### Frontend UI (app/templates/index.html)

#### 1. Zaparoo Status Check
```javascript
let zaparooStatus = { clients: [], has_enabled: false };

async function checkZaparooStatus() {
    // Called on page load and tab switches
    // Fetches /api/zaparoo/status
    // Stores result in zaparooStatus global
}
```

#### 2. Launch Button Generation
```javascript
// In loadDirectory() function, when rendering file entries:
if (type === 'virtual' && entryType === 'file') {
    const availableClients = zaparooStatus.clients.filter(c => c.enabled && c.reachable);
    
    // Create launch button
    const launchBtn = document.createElement('button');
    launchBtn.textContent = '🚀';
    
    // Button states:
    // - Disabled (gray) if no clients enabled
    // - Orange if clients unreachable
    // - Orange (clickable) if 1 client available - direct launch
    // - Orange (clickable) if multiple clients - show selector modal
}
```

#### 3. Launch Function
```javascript
async function launchWithZaparoo(filePath, clientName, button) {
    // 1. Show loading state (⏳)
    // 2. POST to /api/zaparoo/launch
    // 3. Handle response:
    //    - Success: ✔ green, show success toast
    //    - Error: ✖ red, show error toast
    // 4. Revert button after 2-3 seconds
}
```

#### 4. Client Selector Modal
```javascript
function showClientSelector(filePath, clients, button) {
    // Creates modal overlay with semi-transparent background
    // Lists available clients as buttons
    // Shows client details (host:port → mount_path)
    // Clicking a client calls launchWithZaparoo()
}
```

#### 5. Toast Notifications
```javascript
function showToast(message, type = 'info', duration = 3000) {
    // Creates toast notification in top-right corner
    // Types: success (green), error (red), info (blue), warning (orange)
    // Auto-dismisses after duration
    // Slide-in/slide-out animations
}
```

### CSS Styling (app/static/style.css)

#### Launch Button Styles
```css
.launch-btn {
    padding: 0.3em 0.6em;
    margin-left: auto;
    border-radius: 4px;
    border: none;
    cursor: pointer;
    font-size: 0.9em;
    background: #ff9800;  /* Orange */
    color: white;
}

.launch-btn:hover {
    background: #f57c00;  /* Darker orange */
}

.launch-btn:disabled {
    background: #ccc;
    color: #666;
    cursor: not-allowed;
}
```

#### Toast Animations
```css
@keyframes slideIn {
    from {
        transform: translateX(100%);
        opacity: 0;
    }
    to {
        transform: translateX(0);
        opacity: 1;
    }
}

@keyframes slideOut {
    from {
        transform: translateX(0);
        opacity: 1;
    }
    to {
        transform: translateX(100%);
        opacity: 0;
    }
}
```

## Configuration Schema

### app/config/app.yaml
```yaml
zaparoo:
  clients:
    - name: "MiSTer"           # Display name for this client
      enabled: true             # Enable/disable this client
      host: "192.168.1.100"     # IP address or hostname
      port: 7497                # Zaparoo API port (default 7497)
      mount_path: "/media/fat/cifs"  # Where TransFS is mounted on the client
    
    - name: "RetroArch"
      enabled: false
      host: "192.168.1.101"
      port: 7497
      mount_path: "/storage/roms"
```

### Configuration Details
- **name**: Identifier for the client (shown in UI)
- **enabled**: Toggle to enable/disable without removing config
- **host**: IP address or hostname of Zaparoo server
- **port**: Zaparoo JSON-RPC API port (standard is 7497)
- **mount_path**: Absolute path on the client where TransFS mount is accessible
  - MiSTer: typically `/media/fat/cifs`
  - RetroArch/Linux: varies by setup

## Testing Checklist

### Without Zaparoo (Quick Test)
- [ ] No `zaparoo` section in app.yaml
- [ ] Navigate to Browse Virtual tab
- [ ] Verify NO 🚀 buttons appear
- [ ] No errors in console

### With Zaparoo Disabled
- [ ] Add `zaparoo` section with `enabled: false`
- [ ] Navigate to Browse Virtual tab
- [ ] Verify 🚀 buttons appear but are **disabled** (gray)
- [ ] Clicking button shows "Zaparoo is disabled" toast

### With Zaparoo Enabled (Unreachable)
- [ ] Set `enabled: true` with unreachable host
- [ ] Navigate to Browse Virtual tab
- [ ] Verify 🚀 buttons appear in **orange** but disabled
- [ ] Clicking button shows "Zaparoo unreachable" toast

### With Zaparoo Enabled (Single Client)
- [ ] Set `enabled: true` with correct host/port
- [ ] Verify Zaparoo is running: `curl http://host:port/api/v0.1` returns JSON-RPC response
- [ ] Navigate to Browse Virtual tab
- [ ] Verify 🚀 buttons appear in **orange** (clickable)
- [ ] Click button
- [ ] Button shows ⏳ loading state
- [ ] Game launches on MiSTer
- [ ] Button shows ✔ green with success toast
- [ ] Button reverts to 🚀 after 2 seconds

### With Zaparoo Enabled (Multiple Clients)
- [ ] Configure 2+ clients with `enabled: true`
- [ ] Click 🚀 button
- [ ] Modal appears with client selector
- [ ] Select a client
- [ ] Launch proceeds as in single client test

## Restoration Priority

### Phase 1: Backend (High Priority)
1. ✅ Restore documentation (DONE)
2. ❌ Add `zaparoo` configuration schema to app.yaml
3. ❌ Implement `/api/zaparoo/status` endpoint in app/api.py
4. ❌ Implement `/api/zaparoo/launch` endpoint in app/api.py
5. ❌ Test endpoints with curl/Postman

### Phase 2: Frontend (Medium Priority)
6. ❌ Add `checkZaparooStatus()` function to index.html
7. ❌ Add `launchWithZaparoo()` function to index.html
8. ❌ Add `showClientSelector()` function to index.html
9. ❌ Add `showToast()` function to index.html
10. ❌ Modify `loadDirectory()` to add launch buttons
11. ❌ Add toast container CSS to style.css
12. ❌ Add animation keyframes to style.css

### Phase 3: Testing & Documentation (Low Priority)
13. ❌ Test with real Zaparoo instance
14. ❌ Update CONFIGURATION_GUIDE.md with Zaparoo section
15. ❌ Add Zaparoo to FEATURES.md

## Files Requiring Changes

### To Restore Feature Completely:
1. **app/config/app.yaml** - Add zaparoo configuration section
2. **app/api.py** - Add two endpoints (~150 lines)
3. **app/templates/index.html** - Add JavaScript functions (~250 lines)
4. **app/static/style.css** - Add launch button and toast styles (~50 lines)

### Reference Files Available:
- Original implementation in commit `120261b`
- Extracted to `temp_index_old.html` (can be deleted after restoration)
- Documentation in `docs/ZAPAROO_*.md`

## Next Steps

To restore the feature:
1. Review this summary
2. Decide if you want to restore the feature
3. If yes, implement Phase 1 (backend) first
4. Test backend endpoints
5. Implement Phase 2 (frontend)
6. Test end-to-end with real Zaparoo instance

## Original Commit Reference

**Commit**: `120261b` - "Massive refactor, new systems, better testing"
- This commit contains the full working implementation
- Use `git show 120261b:path/to/file` to view original versions
- Temp file created: `temp_index_old.html` (full HTML from that commit)
