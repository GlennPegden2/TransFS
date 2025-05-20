from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
import yaml
import os
import requests
import subprocess
import math
import asyncio
from config import get_clients, get_systems_for_client, get_manufacturers_and_canonical_names

app = FastAPI()

class DownloadRequest(BaseModel):
    manufacturer: str
    system: str

class BuildRequest(BaseModel):
    builds: list  # List of dicts: {"manufacturer": ..., "system": ...}
    clients: list # List of client names

@app.get("/clients")
def api_get_clients():
    return get_clients()

@app.get("/clients/{client_name}/systems")
def api_get_systems(client_name: str):
    return get_systems_for_client(client_name)

@app.get("/systems/meta")
def api_get_manufacturers_and_canonical_names():
    return get_manufacturers_and_canonical_names()

def estimate_download_time(url, speed_mbps=10):
    """Estimate download time in seconds for a given URL and speed in Mbps."""
    try:
        head = requests.head(url, allow_redirects=True, timeout=10)
        size = int(head.headers.get("Content-Length", 0))
        if size == 0:
            return None
        speed_bps = speed_mbps * 1024 * 1024 / 8  # Convert Mbps to bytes/sec
        seconds = math.ceil(size / speed_bps)
        return seconds
    except Exception:
        return None

@app.post("/download")
async def api_download(req: DownloadRequest):
    # Load config
    with open("transfs.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    archive_sources = config.get("archive_sources", {})
    filestore = config.get("filestore", "filestore")

    # Find the correct archive source
    manufacturer_sources = archive_sources.get(req.manufacturer)
    if not manufacturer_sources:
        raise HTTPException(status_code=404, detail="Manufacturer not found")
    system_sources = manufacturer_sources.get(req.system)
    if not system_sources:
        raise HTTPException(status_code=404, detail="System not found")

    # Download all DDL type sources for this system
    downloaded = []
    estimates = []
    for entry in system_sources:
        if entry.get("type") == "ddl":
            url = entry.get("url")
            platform = entry.get("platform", "")
            filename = os.path.basename(url)
            dest_dir = os.path.join(filestore, platform)
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, filename)
            # Estimate download time
            est_sec = estimate_download_time(url)
            if est_sec is not None:
                est_msg = f"Estimated download time for {filename}: ~{est_sec//60}m {est_sec%60}s at 10Mbps"
            else:
                est_msg = f"Could not estimate download time for {filename}"
            estimates.append(est_msg)
            try:
                resp = requests.get(url, stream=True)
                resp.raise_for_status()
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                downloaded.append({"url": url, "dest": dest_path})
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to download {url}: {e}")

    if not downloaded:
        raise HTTPException(status_code=404, detail="No DDL sources found for this system")

    return {
        "status": "success",
        "downloaded": downloaded,
        "estimates": estimates
    }

@app.post("/build")
async def api_build(req: BuildRequest):
    results = []
    for build in req.builds:
        manufacturer = build.get("manufacturer")
        system = build.get("system")
        for client in req.clients:
            script_path = os.path.join(
                "build_scripts", client, manufacturer, system, "build.sh"
            )
            if os.path.isfile(script_path):
                try:
                    # Run the script and capture output
                    completed = subprocess.run(
                        ["bash", script_path],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    results.append({
                        "client": client,
                        "manufacturer": manufacturer,
                        "system": system,
                        "script": script_path,
                        "status": "success",
                        "stdout": completed.stdout,
                        "stderr": completed.stderr
                    })
                except subprocess.CalledProcessError as e:
                    results.append({
                        "client": client,
                        "manufacturer": manufacturer,
                        "system": system,
                        "script": script_path,
                        "status": "error",
                        "stdout": e.stdout,
                        "stderr": e.stderr,
                        "returncode": e.returncode
                    })
            else:
                results.append({
                    "client": client,
                    "manufacturer": manufacturer,
                    "system": system,
                    "script": script_path,
                    "status": "not found"
                })
    return {"results": results}

@app.post("/build/stream")
async def api_build_stream(req: BuildRequest):
    # Load config
    with open("transfs.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    filestore = config.get("filestore", "filestore")
    archive_sources = config.get("archive_sources", {})

    async def run_and_stream():
        for build in req.builds:
            manufacturer = build.get("manufacturer")
            system = build.get("system")
            manufacturer_sources = archive_sources.get(manufacturer, {})
            system_entry = manufacturer_sources.get(system, {})
            base_path_rel = system_entry.get("base_path", "")
            base_path = os.path.join(filestore, base_path_rel)
            for client in req.clients:
                script_path = os.path.join(
                    "build_scripts", client, manufacturer, system, "build.sh"
                )
                if os.path.isfile(script_path):
                    yield f"Running {script_path} with BASE_PATH={base_path}...\n"
                    process = await asyncio.create_subprocess_exec(
                        "bash", script_path,
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
                    yield f"Completed {script_path} (exit code {process.returncode})\n"
                else:
                    yield f"Script not found: {script_path}\n"
    return StreamingResponse(run_and_stream(), media_type="text/plain")

@app.post("/download/stream")
async def api_download_stream(req: DownloadRequest):
    import time

    # Load config
    with open("transfs.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    archive_sources = config.get("archive_sources", {})
    filestore = config.get("filestore", "filestore")

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
        base_path = os.path.join(filestore, base_path_rel)
        sources = system_entry.get("sources", [])

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
                    resp = requests.get(url, stream=True)
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
        if not found:
            yield "No DDL sources found for this system\n"
        else:
            yield f"Done downloading for {req.manufacturer} / {req.system}.\n"

    return StreamingResponse(run_and_stream(), media_type="text/plain")