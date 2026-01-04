import yaml
import os
from dataclasses import dataclass
from typing import Optional

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

@dataclass
class SystemConfig:
    """Represents a system configuration with available packs."""
    name: str
    manufacturer: str
    canonical_name: str
    local_base_path: str
    packs: list[Pack]

def read_app_config(config_dir="config"):
    """Read application configuration (mountpoint, filestore, web_api, ssl_ignore_hosts)."""
    path = os.path.join(config_dir, "app.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def read_clients_config(config_dir="config"):
    """Read clients configuration (all client definitions and system mappings)."""
    path = os.path.join(config_dir, "clients.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def read_source_config(manufacturer: str, canonical_name: str, config_dir="config") -> Optional[dict]:
    """Read source configuration for a specific system."""
    path = os.path.join(config_dir, "sources", manufacturer, f"{canonical_name}.yaml")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return None

def read_config(config_dir="config"):
    """
    Compatibility function that merges all config files into a single dict structure.
    Returns a dict with keys: mountpoint, filestore, web_api, ssl_ignore_hosts, clients, archive_sources
    """
    # Read app config
    app_config = read_app_config(config_dir)
    
    # Read clients config
    clients_config = read_clients_config(config_dir)
    
    # Build archive_sources by discovering all source files
    archive_sources = {}
    sources_dir = os.path.join(config_dir, "sources")
    
    if os.path.exists(sources_dir):
        for manufacturer_name in os.listdir(sources_dir):
            manufacturer_path = os.path.join(sources_dir, manufacturer_name)
            if os.path.isdir(manufacturer_path):
                archive_sources[manufacturer_name] = {}
                for source_file in os.listdir(manufacturer_path):
                    if source_file.endswith(".yaml"):
                        canonical_name = source_file[:-5]  # Remove .yaml extension
                        source_config = read_source_config(manufacturer_name, canonical_name, config_dir)
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
            return [system["name"] for system in client.get("systems", []) if "name" in system]
    return []

def get_manufacturers_and_canonical_names(config_dir="config"):
    clients_config = read_clients_config(config_dir)
    manufacturer_map = {}
    for client in clients_config.get("clients", []):
        for system in client.get("systems", []):
            manufacturer = system.get("manufacturer")
            canonical = system.get("cananonical_system_name")
            if manufacturer and canonical:
                manufacturer_map.setdefault(manufacturer, set()).add(canonical)
    # Convert sets to sorted lists
    return {man: sorted(list(systems)) for man, systems in manufacturer_map.items()}

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
    
    for client in clients_config.get("clients", []):
        if client.get("name") == client_name:
            for system in client.get("systems", []):
                if system.get("name") == system_name:
                    manufacturer = system.get("manufacturer")
                    canonical_name = system.get("cananonical_system_name")
                    local_base_path = system.get("local_base_path")
                    break
            break
    
    if not manufacturer or not canonical_name or not local_base_path:
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
                info_links=pack_data.get("info_links")
            ))
    
    return SystemConfig(
        name=system_name,
        manufacturer=manufacturer,
        canonical_name=canonical_name,
        local_base_path=local_base_path,
        packs=packs
    )