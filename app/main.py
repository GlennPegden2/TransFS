import os
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from api import app as api_app
from config import get_web_api_config, read_app_config

app = FastAPI()
app.mount("/api", api_app)
app.mount("/static", StaticFiles(directory="webui/static"), name="static")
templates = Jinja2Templates(directory="webui/templates")


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:  # pylint: disable=broad-except
        return {}


def _ensure_retronas_native_bridge() -> None:
    """Bridge RetroNAS Native data into filestore when layouts differ.

    In some RetroNAS runtime profiles, `retronas_path` (e.g. `/data/retronas`)
    differs from TransFS `filestore` (e.g. `/mnt/filestorefs`).
    To keep Browse Native behavior consistent, create `filestore/Native` as a
    symlink to `{retronas_path}/Native` when safe.
    """
    retronas_vars = Path("/opt/retronas/ansible/retronas_vars.yml")
    if not retronas_vars.is_file():
        return

    try:
        app_cfg = read_app_config() or {}
    except Exception:  # pylint: disable=broad-except
        app_cfg = {}

    filestore = Path(str(app_cfg.get("filestore") or "/mnt/filestorefs")).resolve()
    rn_cfg = _read_yaml(retronas_vars)
    retronas_path = Path(str(rn_cfg.get("retronas_path") or "/data/retronas")).resolve()

    target_native = retronas_path / "Native"
    link_native = filestore / "Native"

    try:
        filestore.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[startup] Native bridge skipped: cannot create filestore root {filestore}: {exc}")
        return

    if not target_native.is_dir():
        return

    if link_native.exists() or link_native.is_symlink():
        return

    try:
        os.symlink(str(target_native), str(link_native), target_is_directory=True)
        print(f"[startup] Created Native bridge symlink: {link_native} -> {target_native}")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[startup] Native bridge creation failed for {link_native} -> {target_native}: {exc}")


def _template_context(request: Request) -> dict:
    """Build common Jinja2 template context with runtime paths from app config."""
    try:
        app_cfg = read_app_config()
        filestore = app_cfg.get("filestore", "/mnt/filestorefs")
        mountpoint = app_cfg.get("mountpoint", "/mnt/transfs")
    except Exception:  # pylint: disable=broad-except
        filestore = "/mnt/filestorefs"
        mountpoint = "/mnt/transfs"
    return {
        "request": request,
        "filestore": filestore,
        "native_path": filestore,
        "mountpoint": mountpoint,
    }


@app.get("/", response_class=HTMLResponse)
async def web_index(request: Request):
    return templates.TemplateResponse(request, "index_complete.html", _template_context(request))

@app.get("/browse/native/{path:path}", response_class=HTMLResponse)
async def browse_native(request: Request, path: str):
    """Serve the main page for native filesystem browsing with URL routing."""
    return templates.TemplateResponse(request, "index_complete.html", _template_context(request))

@app.get("/browse/virtual/{path:path}", response_class=HTMLResponse)
async def browse_virtual(request: Request, path: str):
    """Serve the main page for virtual filesystem browsing with URL routing."""
    return templates.TemplateResponse(request, "index_complete.html", _template_context(request))

@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    """Serve the Setup Clients configuration page."""
    return templates.TemplateResponse(request, "index_complete.html", _template_context(request))


@app.get("/metadata/{path:path}", response_class=HTMLResponse)
async def metadata_page(request: Request, path: str):
    """Serve the Metadata tab page with folder deep-link routing."""
    return templates.TemplateResponse(request, "index_complete.html", _template_context(request))


@app.get("/metadata", response_class=HTMLResponse)
async def metadata_root_page(request: Request):
    """Serve Metadata tab root route."""
    return templates.TemplateResponse(request, "index_complete.html", _template_context(request))


@app.on_event("startup")
async def _startup_tasks():
    _ensure_retronas_native_bridge()

# For running directly with: python -m uvicorn main:app
if __name__ == "__main__":
    import uvicorn
    web_config = get_web_api_config()
    print(f"Starting TransFS Web UI on {web_config['host']}:{web_config['port']}")
    uvicorn.run(app, host=web_config["host"], port=web_config["port"])

