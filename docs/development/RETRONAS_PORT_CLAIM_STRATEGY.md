# RetroNAS Port Claim and Fallback Strategy (TransFS)

## Goal

Define a predictable installer-time strategy for port ownership when TransFS is installed as a RetroNAS contribution, while keeping existing Docker behavior unchanged.

## Scope

- Bare-metal RetroNAS installer behavior for TransFS services.
- Port selection for SMB and Web API listeners.
- Conflict detection, fallback, warnings, and fail-fast modes.
- Config schema required to persist selected ports.

Out of scope:

- Runtime dynamic rebinding after service start.
- Automatic migration of client-side mounts/shortcuts.

## Constraints and assumptions

- RetroNAS commonly expects canonical protocol ports for compatibility (for SMB: 445).
- Some RetroNAS systems may already run Samba or other web stacks.
- Non-standard ports are possible but can reduce compatibility for legacy clients.
- TransFS currently defaults to non-standard SMB in Docker to avoid host conflicts; this remains valid for Docker mode.

## Important protocol note

- Preferred SMB standard port is 445.
- Port 443 is HTTPS and should not be used as SMB default.

## Ownership model

Installer supports two explicit modes:

1. Host SMB owned by RetroNAS:
- TransFS does not launch/manage Samba.
- TransFS provides FUSE mount + optional Web API only.
- RetroNAS Samba exports the relevant mount path(s).

2. SMB owned by TransFS:
- TransFS manages Samba service/config for its own share(s).
- Installer allocates SMB port using the algorithm below.

Default recommendation for RetroNAS integration:

- `smb.mode = retronas_managed`

This avoids duplicate Samba stacks and eliminates most port conflict risk.

## Installer port allocation algorithm

Apply this order for each service with a configurable listener.

### Inputs

- `preferred_port`: canonical default.
- `fallback_ports`: ordered list.
- `strict_standard_port`: boolean.
- `bind_host`: host/interface to bind.

### Algorithm

1. Probe `preferred_port` on `bind_host`.
2. If free: assign `preferred_port`.
3. If in use and `strict_standard_port = true`: fail installation with clear remediation.
4. If in use and `strict_standard_port = false`:
- Iterate `fallback_ports` in order.
- First free port is assigned.
5. If no port free in fallback set: fail installation.

### Warning semantics

If assigned port differs from preferred port:

- Emit installer warning (stdout and install log).
- Persist warning flag in config.
- Expose warning in UI/API status endpoint.

## Proposed defaults

### SMB (only when `smb.mode = transfs_managed`)

- `preferred_port = 445`
- `fallback_ports = [3445, 1445, 2445]`
- `strict_standard_port = false`

Rationale:

- 445 is best compatibility.
- 3445 already exists as TransFS non-standard convention.

### Web API

- `preferred_port = 8000`
- `fallback_ports = [8001, 8080, 18000]`
- `strict_standard_port = false`

Rationale:

- Preserve current TransFS default first.
- Allow a deterministic fallback sequence.

## Config schema (app.yaml)

```yaml
runtime:
  profile: retronas-baremetal

smb:
  mode: retronas_managed  # retronas_managed | transfs_managed | disabled
  bind_host: 0.0.0.0
  preferred_port: 445
  fallback_ports: [3445, 1445, 2445]
  strict_standard_port: false
  allocated_port: 445
  warning_nonstandard_port: false

web_api:
  host: 0.0.0.0
  preferred_port: 8000
  fallback_ports: [8001, 8080, 18000]
  strict_standard_port: false
  allocated_port: 8000
  warning_nonstandard_port: false
```

Notes:

- `allocated_port` is installer/runtime resolved state, not a static recommendation.
- `warning_nonstandard_port` is set when allocated != preferred.
- Existing keys can be kept for backward compatibility; resolver can map old fields to new structure.

## Installer output contract

At end of install, print and log:

- selected mode (`retronas_managed` vs `transfs_managed`)
- selected SMB port and compatibility note
- selected Web API port
- any conflicts found and fallback ports attempted

Example:

```text
TransFS SMB mode: transfs_managed
Requested SMB port: 445 (in use by smbd)
Allocated SMB port: 3445
Warning: non-standard SMB port may not work for all legacy clients.

Requested Web API port: 8000 (free)
Allocated Web API port: 8000
```

## API/status exposure

Expose resolved port state via status endpoint for diagnostics/UI:

- `smb.mode`
- `smb.allocated_port`
- `smb.warning_nonstandard_port`
- `web_api.allocated_port`
- `port_conflicts_detected`

## Test plan

### Installer tests

1. Preferred ports free:
- Expect preferred assigned.
- No warning flags.

2. SMB preferred occupied, fallback available:
- Expect first free fallback assigned.
- Warning set true.

3. SMB preferred occupied, strict mode true:
- Expect install failure with remediation message.

4. All fallback ports occupied:
- Expect install failure.

5. `retronas_managed` mode:
- Ensure TransFS does not attempt to bind/manage Samba.

### Runtime smoke tests

1. Verify listening sockets on allocated ports.
2. Verify config persistence after reboot/restart.
3. Verify status endpoint values match actual bound ports.

## Backward compatibility

- Docker defaults remain unchanged unless Docker profile explicitly opts into this strategy.
- Existing non-standard Docker SMB mapping remains supported.
- New schema fields should be optional with safe defaults.

## Rollout sequence

1. Add config schema and resolver.
2. Add installer probe + allocation logic.
3. Add warning/status surfaces.
4. Add tests.
5. Add docs for RetroNAS operator workflow.
