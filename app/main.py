from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from api import app as api_app
from config import get_web_api_config, read_app_config

app = FastAPI()
app.mount("/api", api_app)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def _template_context(request: Request) -> dict:
    """Build common Jinja2 template context with runtime paths from app config."""
    try:
        app_cfg = read_app_config()
        filestore = app_cfg.get("filestore", "/data/retronas")
        mountpoint = app_cfg.get("mountpoint", "/mnt/transfs")
    except Exception:  # pylint: disable=broad-except
        filestore = "/data/retronas"
        mountpoint = "/mnt/transfs"
    return {
        "request": request,
        "filestore": filestore,
        "native_path": filestore + "/Native",
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

# For running directly with: python -m uvicorn main:app
if __name__ == "__main__":
    import uvicorn
    web_config = get_web_api_config()
    print(f"Starting TransFS Web UI on {web_config['host']}:{web_config['port']}")
    uvicorn.run(app, host=web_config["host"], port=web_config["port"])

