""" API Wrapper """
import os
import subprocess
import math
import asyncio
import re
import requests
import internetarchive
from pydantic import BaseModel
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from config import (
    get_clients,
    get_systems_for_client,
    get_manufacturers_and_canonical_names,
)

app = FastAPI()


class DownloadRequest(BaseModel):
    """Request model for download endpoints."""
    manufacturer: str
    system: str


class BuildRequest(BaseModel):
    """Request model for build endpoints."""
    builds: list  # List of dicts: {"manufacturer": ..., "system": ...}
    clients: list  # List of client names


@app.get("/clients")
def api_get_clients():
    """Return a list of all configured clients."""
    return get_clients()


@app.get("/clients/{client_name}/systems")
def api_get_systems(client_name: str):
    """Return a list of systems for a given client."""
    return get_systems_for_client(client_name)


@app.get("/systems/meta")
def api_get_manufacturers_and_canonical_names():
    """Return manufacturers and canonical system names metadata."""
    return get_manufacturers_and_canonical_names()


def estimate_download_time(url, speed_mbps=10):
    """
    Estimate download time in seconds for a given URL and speed in Mbps.

    Args:
        url (str): The URL of the file to estimate.
        speed_mbps (int): Download speed in megabits per second.

    Returns:
        int or None: Estimated download time in seconds, or None if unknown.
    """
    try:
        head = requests.head(url, allow_redirects=True, timeout=10)
        size = int(head.headers.get("Content-Length", 0))
        if size == 0:
            return None
        speed_bps = speed_mbps * 1024 * 1024 / 8  # Convert Mbps to bytes/sec
        seconds = math.ceil(size / speed_bps)
        return seconds
    except Exception:  # pylint: disable=broad-except
        return None


@app.post("/build")
async def api_build_stream(req: BuildRequest):
    """
    Stream output from running build scripts for the specified builds and clients.

    Args:
        req (BuildRequest): The build request.

    Returns:
        StreamingResponse: Streaming output of build script execution.
    """
    with open("transfs.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    filestore = config.get("filestore", "filestore")
    archive_sources = config.get("archive_sources", {})

    async def run_and_stream():
        """Async generator to run build scripts and yield output lines."""
        for build in req.builds:
            manufacturer = build.get("manufacturer")
            system = build.get("system")
            manufacturer_sources = archive_sources.get(manufacturer, {})
            system_entry = manufacturer_sources.get(system, {})
            base_path_rel = system_entry.get("base_path", "")
            base_path = os.path.join(filestore, "Native" , base_path_rel)
            for client in req.clients:
                script_path = os.path.join(
                    "build_scripts", client, manufacturer, system, "build.sh"
                )
                if os.path.isfile(script_path):
                    yield f"Running {script_path} with BASE_PATH={base_path}...\n"
                    process = await asyncio.create_subprocess_exec(
                        "bash",
                        script_path,
                        env={**os.environ, "BASE_PATH": base_path},
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    if process.stdout is not None:
                        while True:
                            line = await process.stdout.readline()
                            if not line:
                                break
                            yield line.decode(errors="replace")
                    await process.wait()
                    yield (
                        f"Completed {script_path} (exit code {process.returncode})\n"
                    )
                else:
                    yield f"Script not found: {script_path}\n"

    return StreamingResponse(run_and_stream(), media_type="text/plain")


@app.post("/download")
async def api_download_stream(req: DownloadRequest):
    """
    Stream download progress for DDL and IA-COL sources for a given manufacturer/system.
    Only downloads filetypes specified in the maps for the selected client/system.
    """
    with open("transfs.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    archive_sources = config.get("archive_sources", {})
    filestore = config.get("filestore", "filestore")
    clients = config.get("clients", [])

    async def run_and_stream():
        manufacturer_sources = archive_sources.get(req.manufacturer)
        if not manufacturer_sources:
            yield "Manufacturer not found\n"
            return
        system_entry = manufacturer_sources.get(req.system)
        if not system_entry:
            yield "System not found\n"
            return

        base_path_rel = system_entry.get("base_path", "")
        base_path = os.path.join(filestore, "Native" , base_path_rel)
        sources = system_entry.get("sources", [])

        # --- Find filetypes for this client/system ---
        filetypes = None
        # Find the client config
        for client in clients:
            for system in client.get("systems", []):
                if (
                    system.get("manufacturer") == req.manufacturer
                    and system.get("cananonical_system_name") == req.system
                ):
                    # Look for ...SoftwareArchives... map
                    for map_entry in system.get("maps", []):
                        if "...SoftwareArchives..." in map_entry:
                            ft = []
                            for ft_entry in map_entry["...SoftwareArchives..."].get("filetypes", []):
                                # filetypes can be dicts like {'Tape': 'UEF'} or {'HD': 'MMB,VHD'}
                                if isinstance(ft_entry, dict):
                                    for v in ft_entry.values():
                                        ft.extend([x.strip() for x in v.split(",")])
                                elif isinstance(ft_entry, str):
                                    ft.extend([x.strip() for x in ft_entry.split(",")])
                            filetypes = list(set(ft))
        # --- End filetype extraction ---

        found = False
        for entry in sources:
            if entry.get("type") == "ddl":
                found = True
                url = entry.get("url")
                platform = entry.get("platform", "")
                filename = os.path.basename(url)
                dest_dir = os.path.join(base_path, platform)
                os.makedirs(dest_dir, exist_ok=True)
                dest_path = os.path.join(dest_dir, filename)
                # Estimate download time
                est_sec = estimate_download_time(url)
                if est_sec is not None:
                    est_msg = f"Estimated download time for {filename}: ~{est_sec//60}m {est_sec%60}s at 10Mbps\n"
                else:
                    est_msg = f"Could not estimate download time for {filename}\n"
                yield est_msg
                try:
                    resp = requests.get(url, stream=True, timeout=30)
                    resp.raise_for_status()
                    total = int(resp.headers.get("Content-Length", 0))
                    downloaded_bytes = 0
                    chunk_size = 8192
                    with open(dest_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=chunk_size):
                            if chunk:
                                f.write(chunk)
                                downloaded_bytes += len(chunk)
                                if total:
                                    percent = int(downloaded_bytes * 100 / total)
                                    yield f"Downloading {filename}: {percent}%\n"
                    yield f"Downloaded for {req.manufacturer} / {req.system}: {dest_path}\n"
                except Exception as e:
                    yield f"Failed to download {url}: {e}\n"
            elif entry.get("type") == "IA-COL":
                found = True
                url = entry.get("url")
                platform = entry.get("platform", "")
                print(f"Downloading IA-COL {url} to {base_path} for {req.manufacturer} / {req.system}")
                try:
                    for msg in download_ia_collection(url, base_path, platform, filetypes=filetypes):
                        yield msg
                    yield (
                        f"Downloaded IA-COL for {req.manufacturer} / "
                        f"{req.system}: {os.path.join(base_path, platform)}\n"
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    yield f"Failed to download IA-COL {url}: {exc}\n"
        if not found:
            yield "No DDL sources found for this system\n"
        else:
            yield f"Done downloading for {req.manufacturer} / {req.system}.\n"

    return StreamingResponse(run_and_stream(), media_type="text/plain")


def download_ia_collection(url, base_path, platform, filetypes=None):
    """
    Download all files from an Internet Archive collection to the correct platform directory.
    Optionally filter by file extension.

    Args:
        url (str): The Internet Archive collection URL.
        base_path (str): The base directory (from YAML).
        platform (str): The platform subdirectory (from YAML).
        filetypes (str or list, optional): Comma-separated string or list of file extensions.

    Yields:
        str: Progress messages for each item downloaded.
    """
    dest_dir = os.path.join(base_path, platform)
    os.makedirs(dest_dir, exist_ok=True)

    match = re.search(r'/details/([^/?#]+)', url)
    if not match:
        yield f"Could not extract collection name from URL: {url}\n"
        return

    if filetypes:
        if isinstance(filetypes, str):
            filetypes_set = set(ft.strip().lower() for ft in filetypes.split(","))
        else:
            filetypes_set = set(ft.strip().lower() for ft in filetypes)
    else:
        filetypes_set = None

    collection_name = match.group(1)
    yield f"Fetching Internet Archive collection: {collection_name}\n"

    for item in internetarchive.search_items(f'collection:{collection_name}'):
        item_id = item['identifier']
#        yield f"Processing item: {item_id}\n"
        ia_item = internetarchive.get_item(item_id)
        ia_files = ia_item.files
        files_to_download = []
        for f in ia_files:
            ext = f['name'].split('.')[-1].lower() if '.' in f['name'] else ''
            if not filetypes_set or ext in filetypes_set:
                files_to_download.append(f['name'])
        if files_to_download:
            yield f"Downloading {len(files_to_download)} file(s) from item: {item_id}\n"
            ia_item.download(
                destdir=dest_dir,
                files=files_to_download,
                verbose=False,
                checksum=True,
                no_directory=True
            )
 #           yield f"Downloaded item: {item_id}\n"
        else:
            yield f"No matching files in item: {item_id}\n"
