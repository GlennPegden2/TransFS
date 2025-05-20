import yaml

def read_config(path="transfs.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_clients(path="transfs.yaml"):
    config = read_config(path)
    return [client["name"] for client in config.get("clients", []) if "name" in client]

def get_systems_for_client(client_name, path="transfs.yaml"):
    config = read_config(path)
    for client in config.get("clients", []):
        if client.get("name") == client_name:
            return [system["name"] for system in client.get("systems", []) if "name" in system]
    return []

def get_manufacturers_and_canonical_names(path="transfs.yaml"):
    config = read_config(path)
    manufacturer_map = {}
    for client in config.get("clients", []):
        for system in client.get("systems", []):
            manufacturer = system.get("manufacturer")
            canonical = system.get("cananonical_system_name")
            if manufacturer and canonical:
                manufacturer_map.setdefault(manufacturer, set()).add(canonical)
    # Convert sets to sorted lists
    return {man: sorted(list(systems)) for man, systems in manufacturer_map.items()}