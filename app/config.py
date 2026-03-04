import yaml
import os
from dataclasses import dataclass
from typing import Optional
from functools import lru_cache


def _normalize_native_local_base_path(local_base_path: Optional[str]) -> str:
    """Normalize system local base paths under Native/Systems for new architecture."""
    normalized = (local_base_path or "").replace("\\", "/").strip("/")
    if not normalized:
        return ""

    lower = normalized.lower()
    if lower.startswith("systems/") or lower.startswith("clients/"):
        return normalized

    return f"Systems/{normalized}"


def _normalize_source_base_path(base_path: Optional[str]) -> str:
    """Normalize source base_path under Native/Systems for new architecture."""
    normalized = (base_path or "").replace("\\", "/").strip("/")
    if not normalized:
        return ""

    lower = normalized.lower()
    if lower.startswith("systems/") or lower.startswith("clients/"):
        return normalized

    return f"Systems/{normalized}"

@dataclass
class Pack:
    """Represents a downloadable pack of software for a system."""
    id: str
    name: str
    description: str
    estimated_size: str
    sources: list[str]  # List of source names from archive_sources to download
    post_process: Optional[list[dict]] = None  # Declarative post-processing operations
    build_script: Optional[str] = None  # Legacy bash script for complex cases
    info_links: Optional[list[dict]] = None  # List of {"label": "...", "url": "..."} info links
    metadata: Optional[dict] = None  # Optional pack-level metadata defaults
    supported_by: Optional[list[str]] = None  # List of client names that support this pack

@dataclass
class SystemConfig:
    """Represents a system configuration with available packs."""
    name: str
    manufacturer: str
    canonical_name: str
    local_base_path: str
    packs: list[Pack]
    download_layout: str = "folder_based"  # folder_based (default) | flat | source_based

def read_app_config(config_dir="config"):
    """Read application configuration (mountpoint, filestore, web_api, ssl_ignore_hosts)."""
    path = os.path.join(config_dir, "app.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def read_clients_config(config_dir="config", config_set=None):
    """Read clients configuration from individual client files in clients/<config_set>/ directory.
    
    Args:
        config_dir: Base config directory
        config_set: Name of the config set to load (e.g., 'default'). If None, uses active_client_config from app.yaml
    """
    # Get active config set if not specified
    if config_set is None:
        app_config = read_app_config(config_dir)
        config_set = app_config.get("config_sets", {}).get("active_client_config", "default")
    
    clients = []
    clients_set_dir = os.path.join(config_dir, "clients", config_set)
    
    # If config set directory doesn't exist, fall back to legacy clients.yaml
    if not os.path.exists(clients_set_dir):
        legacy_path = os.path.join(config_dir, "clients.yaml")
        if os.path.exists(legacy_path):
            with open(legacy_path, "r", encoding="utf-8") as f:
                legacy_config = yaml.safe_load(f) or {"clients": []}
                for client_data in legacy_config.get("clients", []):
                    for system in client_data.get("systems", []):
                        if "local_base_path" in system:
                            system["local_base_path"] = _normalize_native_local_base_path(system.get("local_base_path"))
                return legacy_config
        # Try direct clients directory (backward compatibility)
        clients_dir = os.path.join(config_dir, "clients")
        if os.path.exists(clients_dir) and os.path.isdir(clients_dir):
            for filename in sorted(os.listdir(clients_dir)):
                if filename.endswith(".yaml"):
                    client_path = os.path.join(clients_dir, filename)
                    if os.path.isfile(client_path):
                        with open(client_path, "r", encoding="utf-8") as f:
                            client_data = yaml.safe_load(f)
                            if client_data and isinstance(client_data, dict):
                                for system in client_data.get("systems", []):
                                    if "local_base_path" in system:
                                        system["local_base_path"] = _normalize_native_local_base_path(system.get("local_base_path"))
                                clients.append(client_data)
            return {"clients": clients}
        return {"clients": []}
    
    # Load all client YAML files from config set directory
    for filename in sorted(os.listdir(clients_set_dir)):
        if filename.endswith(".yaml"):
            client_path = os.path.join(clients_set_dir, filename)
            with open(client_path, "r", encoding="utf-8") as f:
                client_data = yaml.safe_load(f)
                if client_data and isinstance(client_data, dict):
                    for system in client_data.get("systems", []):
                        if "local_base_path" in system:
                            system["local_base_path"] = _normalize_native_local_base_path(system.get("local_base_path"))
                    clients.append(client_data)
    
    return {"clients": clients}

def read_source_config(manufacturer: str, canonical_name: str, config_dir="config", config_set=None) -> Optional[dict]:
    """Read source configuration for a specific system.
    
    Args:
        manufacturer: Manufacturer name (e.g., 'Acorn')
        canonical_name: System canonical name (e.g., 'Atom')
        config_dir: Base config directory
        config_set: Name of the config set to load. If None, uses active_source_config from app.yaml
    """
    # Get active config set if not specified
    if config_set is None:
        app_config = read_app_config(config_dir)
        config_set = app_config.get("config_sets", {}).get("active_source_config", "default")
    
    path = os.path.join(config_dir, "sources", config_set, manufacturer, f"{canonical_name}.yaml")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            source_config = yaml.safe_load(f)
            if isinstance(source_config, dict) and "base_path" in source_config:
                source_config["base_path"] = _normalize_source_base_path(source_config.get("base_path"))
            return source_config
    
    # Fallback to legacy location (no config_set subdirectory)
    legacy_path = os.path.join(config_dir, "sources", manufacturer, f"{canonical_name}.yaml")
    if os.path.exists(legacy_path):
        with open(legacy_path, "r", encoding="utf-8") as f:
            source_config = yaml.safe_load(f)
            if isinstance(source_config, dict) and "base_path" in source_config:
                source_config["base_path"] = _normalize_source_base_path(source_config.get("base_path"))
            return source_config
    
    return None

@lru_cache(maxsize=1)
def read_config(config_dir="config"):
    """
    Compatibility function that merges all config files into a single dict structure.
    Returns a dict with keys: mountpoint, filestore, web_api, ssl_ignore_hosts, clients, archive_sources
    
    Note: This function is cached. To reload config after changes, call read_config.cache_clear()
    """
    # Read app config
    app_config = read_app_config(config_dir)
    
    # Read clients config
    clients_config = read_clients_config(config_dir)

    # Apply client-level download_layout defaults to systems
    for client in clients_config.get("clients", []):
        client_layout = client.get("download_layout")
        if not client_layout:
            continue
        for system in client.get("systems", []):
            system.setdefault("download_layout", client_layout)
    
    # Build archive_sources by discovering all source files
    archive_sources = {}
    config_set = app_config.get("config_sets", {}).get("active_source_config", "default")
    sources_set_dir = os.path.join(config_dir, "sources", config_set)
    
    # Try config set directory first
    if os.path.exists(sources_set_dir):
        for manufacturer_name in os.listdir(sources_set_dir):
            manufacturer_path = os.path.join(sources_set_dir, manufacturer_name)
            if os.path.isdir(manufacturer_path):
                archive_sources[manufacturer_name] = {}
                for source_file in os.listdir(manufacturer_path):
                    if source_file.endswith(".yaml"):
                        canonical_name = source_file[:-5]  # Remove .yaml extension
                        source_config = read_source_config(manufacturer_name, canonical_name, config_dir, config_set)
                        if source_config:
                            archive_sources[manufacturer_name][canonical_name] = source_config
    else:
        # Fallback to legacy sources directory (no config_set subdirectory)
        sources_dir = os.path.join(config_dir, "sources")
        if os.path.exists(sources_dir):
            for manufacturer_name in os.listdir(sources_dir):
                manufacturer_path = os.path.join(sources_dir, manufacturer_name)
                if os.path.isdir(manufacturer_path):
                    archive_sources[manufacturer_name] = {}
                    for source_file in os.listdir(manufacturer_path):
                        if source_file.endswith(".yaml"):
                            canonical_name = source_file[:-5]  # Remove .yaml extension
                            source_config = read_source_config(manufacturer_name, canonical_name, config_dir, "legacy")
                            if source_config:
                                archive_sources[manufacturer_name][canonical_name] = source_config
    
    # Merge into single config dict for compatibility
    return {
        **app_config,
        **clients_config,
        "archive_sources": archive_sources
    }

def get_clients(config_dir="config"):
    clients_config = read_clients_config(config_dir)
    return [client["name"] for client in clients_config.get("clients", []) if "name" in client]

def get_systems_for_client(client_name, config_dir="config"):
    clients_config = read_clients_config(config_dir)
    for client in clients_config.get("clients", []):
        if client.get("name") == client_name:
            return [system.get("display_name", system["name"]) for system in client.get("systems", []) if "name" in system]
    return []

def get_manufacturers_and_canonical_names(config_dir="config"):
    clients_config = read_clients_config(config_dir)
    archive_sources = read_config(config_dir).get("archive_sources", {})
    manufacturer_map = {}
    for client in clients_config.get("clients", []):
        client_name = client.get("name")
        for system in client.get("systems", []):
            manufacturer = system.get("manufacturer")
            mapping_name = system.get("system_mapping_name") or system.get("cananonical_system_name")
            display_name = system.get("display_name") or system.get("name") or mapping_name
            name = system.get("name")
            if manufacturer and mapping_name:
                manufacturer_map.setdefault(manufacturer, {})
                # Use mapping_name as key and track all clients that support it
                key = mapping_name
                if key not in manufacturer_map[manufacturer]:
                    manufacturer_map[manufacturer][key] = {
                        "mapping_name": mapping_name,
                        "display_name": display_name,
                        "name": name,
                        "supported_by": []
                    }
                # Add this client to the supported_by list if not already there
                if client_name not in manufacturer_map[manufacturer][key]["supported_by"]:
                    manufacturer_map[manufacturer][key]["supported_by"].append(client_name)
    
    # Merge supported_by from pack metadata (if present)
    for manufacturer, systems in archive_sources.items():
        if manufacturer not in manufacturer_map:
            continue
        for canonical_name, source_config in systems.items():
            if canonical_name not in manufacturer_map[manufacturer]:
                continue
            packs = source_config.get("packs", []) or []
            if not packs:
                continue
            pack_supported = set()
            for pack in packs:
                supported = pack.get("supported_by") or ["MiSTer"]
                pack_supported.update(supported)
            if pack_supported:
                combined = set(manufacturer_map[manufacturer][canonical_name].get("supported_by", []))
                combined.update(pack_supported)
                manufacturer_map[manufacturer][canonical_name]["supported_by"] = sorted(combined)

    # Convert dicts to sorted lists and return sorted by manufacturer name
    result = {}
    for man in sorted(manufacturer_map.keys()):
        result[man] = sorted(manufacturer_map[man].values(), key=lambda s: s.get("display_name", s.get("mapping_name", "")))
    return result

def get_web_api_config(config_dir="config") -> dict:
    """Get web API host and port configuration."""
    app_config = read_app_config(config_dir)
    web_api = app_config.get("web_api", {})
    return {
        "host": web_api.get("host", "0.0.0.0"),
        "port": web_api.get("port", 8000)
    }

def get_system_config(client_name: str, system_name: str, config_dir="config") -> Optional[SystemConfig]:
    """Get detailed system configuration including packs from source files."""
    clients_config = read_clients_config(config_dir)
    
    # Find the system in clients to get manufacturer and canonical name
    manufacturer = None
    canonical_name = None
    local_base_path = None
    actual_system_name = None
    
    for client in clients_config.get("clients", []):
        if client.get("name") == client_name:
            for system in client.get("systems", []):
                # Check both system name and system_mapping_name
                system_actual_name = system.get("name")
                system_mapping = system.get("system_mapping_name")
                if system_actual_name == system_name or system_mapping == system_name:
                    manufacturer = system.get("manufacturer")
                    canonical_name = system_mapping or system.get("cananonical_system_name")
                    local_base_path = system.get("local_base_path")
                    actual_system_name = system_actual_name
                    break
            break
    
    if not manufacturer or not canonical_name or not local_base_path or not actual_system_name:
        return None
    
    # Get packs from source config
    packs = []
    source_config = read_source_config(manufacturer, canonical_name, config_dir)
    if source_config:
        for pack_data in source_config.get("packs", []):
            packs.append(Pack(
                id=pack_data.get("id"),
                name=pack_data.get("name"),
                description=pack_data.get("description"),
                estimated_size=pack_data.get("estimated_size"),
                sources=pack_data.get("sources", []),
                post_process=pack_data.get("post_process"),
                build_script=pack_data.get("build_script"),
                info_links=pack_data.get("info_links"),
                metadata=pack_data.get("metadata"),
                supported_by=pack_data.get("supported_by")
            ))
    
    # Get download_layout from clients config
    download_layout = "folder_based"  # default
    for client in clients_config.get("clients", []):
        if client.get("name") == client_name:
            client_layout = client.get("download_layout")
            for system in client.get("systems", []):
                # Check both system name and system_mapping_name
                system_actual_name = system.get("name")
                system_mapping = system.get("system_mapping_name")
                if system_actual_name == system_name or system_mapping == system_name:
                    download_layout = system.get("download_layout", client_layout or "folder_based")
                    break
            break
    
    return SystemConfig(
        name=system_name,
        manufacturer=manufacturer,
        canonical_name=canonical_name,
        local_base_path=local_base_path,
        packs=packs,
        download_layout=download_layout
    )

def reload_config():
    """Clear the config cache to force reload on next read_config() call."""
    read_config.cache_clear()
    return {"status": "Config cache cleared"}

def get_available_config_sets(config_dir="config"):
    """Get lists of available client and source config sets."""
    client_sets = []
    source_sets = []
    
    # Scan clients directory for config sets
    clients_dir = os.path.join(config_dir, "clients")
    if os.path.exists(clients_dir):
        for item in os.listdir(clients_dir):
            item_path = os.path.join(clients_dir, item)
            if os.path.isdir(item_path):
                client_sets.append(item)
    
    # Scan sources directory for config sets
    sources_dir = os.path.join(config_dir, "sources")
    if os.path.exists(sources_dir):
        for item in os.listdir(sources_dir):
            item_path = os.path.join(sources_dir, item)
            if os.path.isdir(item_path):
                source_sets.append(item)
    
    return {
        "client_sets": sorted(client_sets),
        "source_sets": sorted(source_sets)
    }

def get_active_config_sets(config_dir="config"):
    """Get the currently active client and source config sets."""
    app_config = read_app_config(config_dir)
    return {
        "active_client_config": app_config.get("config_sets", {}).get("active_client_config", "default"),
        "active_source_config": app_config.get("config_sets", {}).get("active_source_config", "default")
    }

def set_active_config_set(config_type: str, config_set: str, config_dir="config"):
    """Set the active config set for clients or sources.
    
    Args:
        config_type: Either 'client' or 'source'
        config_set: Name of the config set to activate
        config_dir: Base config directory
    """
    if config_type not in ['client', 'source']:
        raise ValueError("config_type must be 'client' or 'source'")
    
    app_config_path = os.path.join(config_dir, "app.yaml")
    with open(app_config_path, "r", encoding="utf-8") as f:
        app_config = yaml.safe_load(f)
    
    # Ensure config_sets section exists
    if "config_sets" not in app_config:
        app_config["config_sets"] = {}
    
    # Update the appropriate config set
    key = f"active_{config_type}_config"
    app_config["config_sets"][key] = config_set
    
    # Write back to app.yaml
    with open(app_config_path, "w", encoding="utf-8") as f:
        yaml.dump(app_config, f, default_flow_style=False, sort_keys=False)
    
    # Clear config cache to force reload
    read_config.cache_clear()
    
    return {"success": True, "config_type": config_type, "active_config_set": config_set}
