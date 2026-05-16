# RetroNAS Namespace Compatibility Layer

## Purpose

TransFS stores content canonically and exposes virtual client namespaces through FUSE.
The RetroNAS compatibility layer adds an optional namespace projection mode that reshapes
paths for RetroNAS-style SMB/CIFS clients without moving or duplicating content.

## Canonical Storage vs Client Projection

Canonical storage remains source-of-truth under Native canonical roots (for example:
`Canonical/roms/{src}`, `Canonical/saves/{src}`, `Canonical/savestates/{src}`, `Canonical/bios/{src}`).

Client projection is a view-only path translation layer:

- Canonical system id: `sony/playstation1`
- Client-facing name: `PSX`
- Projected paths:
  - `MiSTer/games/PSX`
  - `MiSTer/saves/PSX`
  - `MiSTer/savestates/PSX`
  - `MiSTer/BIOS/PSX`

Each projected path resolves to canonical storage paths.

## Namespace Compatibility

"Namespace compatibility" means path/layout compatibility only:

- Compatible folder naming and hierarchy for a target client.
- No content conversion.
- No emulator/runtime semantic validation.
- No deduplication side effects; content remains single-copy.

## Configuration

Enable per-client using `retronas_support` in client config.

- `enabled`: false by default (opt-in).
- `transport`: currently `smb`.
- `top_levels`: projected folders and canonical root mapping.
- `mappings`: canonical system id to client-facing name.
- `overrides`: explicit additional aliases/entries.

Backward compatibility: legacy key `projection` is still accepted by the loader.

## Current Limitations

- Tier 1 only (namespace/path projection).
- No extension filtering, BIOS validation, conversion, or multi-disc normalization.
- Intended for SMB/CIFS presentation compatibility, not runtime correctness guarantees.
