from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from api import app as api_app
from config import get_web_api_config

app = FastAPI()
app.mount("/api", api_app)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def web_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/browse/native/{path:path}", response_class=HTMLResponse)
async def browse_native(request: Request, path: str):
    """Serve the main page for native filesystem browsing with URL routing."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/browse/virtual/{path:path}", response_class=HTMLResponse)
async def browse_virtual(request: Request, path: str):
    """Serve the main page for virtual filesystem browsing with URL routing."""
    return templates.TemplateResponse("index.html", {"request": request})

# For running directly with: python -m uvicorn main:app
if __name__ == "__main__":
    import uvicorn
    web_config = get_web_api_config()
    print(f"Starting TransFS Web UI on {web_config['host']}:{web_config['port']}")
    uvicorn.run(app, host=web_config["host"], port=web_config["port"])

