# Lost Template Functionality - Restoration Plan

## Investigation Summary

I've examined the legacy templates (index_fixed.html, index_clean.html) and git history to identify exactly what functionality was lost when templates were consolidated into index_complete.html.

---

## 1. DOWNLOAD PAGE: Carriage Return Progress Display

### What Was Lost
The Download page's log display had special handling for carriage returns (`\r`) used by the downloader to show "percentage complete" at the start of lines.

**Example of lost behavior:**
```
Installing pack: MyGame.zip...
[████████░░░░░░░░░░] 45%↲  (shows on same line, updating)
```

When `\r` was received, it would clear the current line and overwrite from the start, creating the illusion of a progress bar updating in place.

### Exact Code to Restore (from index_fixed.html lines 1304-1340)

**State tracking object:** (Goes near top of script)
```javascript
window.logState = { 
    lines: [],  // Array of completed lines
    currentLine: '',  // Current line being built
    carriage_return_mode: false  // Are we in overwrite mode (after \r)?
};
```

**appendLog() function:** (Replaces current simple log appending)
```javascript
function appendLog(msg) {
    const logDiv = document.getElementById('log');
    const state = window.logState;
    
    for (let i = 0; i < msg.length; i++) {
        const char = msg[i];
        
        if (char === '\r') {
            // Carriage return: enter overwrite mode, clearing current line
            state.currentLine = '';
            state.carriage_return_mode = true;
        } else if (char === '\n') {
            // Newline: finalize the current line and start a new one
            state.lines.push(state.currentLine);
            state.currentLine = '';
            state.carriage_return_mode = false;
        } else {
            // Regular character
            if (state.carriage_return_mode) {
                // In overwrite mode: characters replace from start (build new line)
                state.currentLine += char;
            } else {
                // Normal mode: just append
                state.currentLine += char;
            }
        }
    }
    
    // Reconstruct the full content: completed lines + current line
    let fullContent = state.lines.join('\n');
    if (state.lines.length > 0 && state.currentLine) {
        fullContent += '\n' + state.currentLine;
    } else if (state.currentLine) {
        fullContent = state.currentLine;
    }
    
    logDiv.textContent = fullContent;
    logDiv.scrollTop = logDiv.scrollHeight;
}
```

**Location:** After the install/download functions in app/templates/index_complete.html

---

## 2. TEST RESULTS PAGE: Progress Bar Display

### What Was Lost
The Test Results tab had a progress bar that appeared while tests were running, showing visual feedback.

**HTML Elements (lines 6-20 in index_fixed.html):**
```html
<div id="test-status" style="padding: 1em; background: #f5f5f5; border-radius: 4px; margin-bottom: 1.5em; display: none;">
    <div><strong id="test-status-text">Status</strong></div>
    <div id="test-progress-bar" style="margin-top: 0.5em; display: none; height: 20px; background: #ddd; border-radius: 4px; overflow: hidden;">
        <div id="test-progress-fill" style="height: 100%; background: #4CAF50; width: 0%; transition: width 0.3s;"></div>
    </div>
</div>
```

**JavaScript showTestStatus() function (lines 2882-2900 in index_fixed.html):**
```javascript
function showTestStatus(message, isRunning = false, progress = 0) {
    const statusDiv = document.getElementById('test-status');
    const statusText = document.getElementById('test-status-text');
    const progressBar = document.getElementById('test-progress-bar');
    const progressFill = document.getElementById('test-progress-fill');

    statusText.textContent = message;
    statusDiv.style.display = 'block';

    if (isRunning) {
        progressBar.style.display = 'block';
        if (progress > 0) {
            progressFill.style.width = progress + '%';
        }
    } else {
        progressBar.style.display = 'none';
    }
}
```

**Location in current template:** 
- HTML: Finding where test-results-container is, add above it
- JavaScript: In the "TEST RESULTS TAB FUNCTIONS" section

---

## 3. DEBUG PAGE: Docker/FUSE Log Auto-Refresh

### What Was Lost
The Debug page had a `refreshFuseLog()` function that fetched the FUSE log from `/api/logs` endpoint and displayed it. The function still exists in index_complete.html but is never called automatically.

**Exact function to verify/restore (from index_fixed.html lines 1503-1516):**
```javascript
// FUSE log fetch and display
async function refreshFuseLog() {
    const fuseLogDiv = document.getElementById('fuse-log');
    try {
        const resp = await fetch('/api/logs');
        if (resp.ok) {
            const text = await resp.text();
            fuseLogDiv.textContent = text;
            fuseLogDiv.scrollTop = fuseLogDiv.scrollHeight;
        } else {
            fuseLogDiv.textContent = "Failed to fetch FUSE log.";
        }
    } catch (e) {
        fuseLogDiv.textContent = "Error fetching FUSE log: " + e;
    }
}
```

**Auto-refresh pattern (optional, from comment at line 1951):**
```javascript
// Optional: auto-refresh FUSE log every 10 seconds:
// setInterval(refreshFuseLog, 10000);
```

**Location in current template:**
- The function exists at line ~1503 in index_complete.html
- Needs to be called when Debug tab loads (in switchTab function)

---

## Restoration Tasks

### Task 1: Download Page - Carriage Return Support
- [ ] Add `window.logState` object initialization before script functions
- [ ] Replace current `appendLog()` function with version that handles `\r` and `\n` separately
- [ ] Test: Download a pack and verify progress shows on same line (not new lines)

### Task 2: Test Results Page - Progress Bar
- [ ] Add progress bar HTML elements to test-results-tab (above test-results-container)
- [ ] Add `showTestStatus()` function to JavaScript
- [ ] Modify `runTests()` function to call `showTestStatus()` when tests start
- [ ] Test: Run a test suite and verify progress bar appears and fills

### Task 3: Debug Page - Auto-Load FUSE Log
- [ ] Verify `refreshFuseLog()` function exists in index_complete.html
- [ ] Call `refreshFuseLog()` in the switchTab function when tabName === 'debug'
- [ ] Test: Click Debug tab and verify FUSE log appears without manual refresh button click

---

## Key Findings

✓ **Download Progress**: Relies on special character encoding (`\r`) from the API - no backend changes needed, only frontend display logic
✓ **Test Progress**: showTestStatus() function exists, just needs to be called during test execution
✓ **Debug Log**: refreshFuseLog() function exists, just needs to be triggered on tab load

All three features are **frontend-only fixes**. No API or backend changes required.

