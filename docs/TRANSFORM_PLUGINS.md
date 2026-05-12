# Transform Plugins

## Purpose
Transform plugins let TransFS alter files on the fly during reads (e.g., strip headers, unpack formats, or adjust extensions). Plugins are a subfeature of mappings and are invoked when a mapping defines transforms for a file type.

## Where This Fits
- Virtual File System
  - Mappings
    - Transform plugins (this page)

## Plugin Discovery
TransFS scans the plugin directory on startup and loads any Python files found.

Location:
- app/transform_plugins

Each plugin file can expose either:
- TRANSFORM_PLUGINS = {"name": TransformClass, ...}
- register_transforms(registry: dict[str, type[Transform]]) -> None

## Minimal Plugin Example
See the example at:
- app/transform_plugins/example_transform.py

## Configuration Usage
Use transform names in YAML where transforms are supported.

Example mapping snippet:
- ...SoftwareArchives...:
    source_dir: Software
    filetypes:
      - HDs: 2MG
    transforms:
      2MG:
        - type: two_mg

If a plugin registers "custom_transform", it can be referenced like this:
- transforms:
    2MG:
      - type: custom_transform

## Best Practices
- Keep transforms stateless and thread-safe.
- Validate file headers before transforming.
- Use get_output_extension() for dynamic output types.
- Log concise messages; avoid large per-read logs.

## Notes
- Plugins are loaded at startup. Restart the container to pick up new plugins.
- If a plugin name matches a built-in transform, the plugin overrides it.
