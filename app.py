import asyncio
import sys
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import json
import logging
from pathlib import Path
import tempfile
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi.responses import FileResponse
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from orchestrator import orchestrate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

app = FastAPI(title="A11yAgents API")

class ScanRequest(BaseModel):
    url: str

@app.post("/api/scan")
def scan_url(req: ScanRequest):
    logger.info(f"Received scan request for {req.url}")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "report.json"
        
        # Run orchestrator in a completely isolated event loop
        # This completely avoids Uvicorn's SelectorEventLoop issues on Windows
        def run_in_isolated_loop():
            if sys.platform == "win32":
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(orchestrate(req.url, str(output_file)))
            finally:
                loop.close()
                
        try:
            run_in_isolated_loop()
            
            # Read the generated files
            if not output_file.exists():
                raise HTTPException(status_code=500, detail="Main report.json was not generated")
                
            report_data = json.loads(output_file.read_text(encoding="utf-8"))
            
            comp_path = output_file.parent / "report_with_axe_comparison.json"
            comparison_data = {}
            if comp_path.exists():
                comparison_data = json.loads(comp_path.read_text(encoding="utf-8"))
                
            return {
                "report": report_data,
                "comparison": comparison_data
            }
            
        except Exception as e:
            logger.error(f"Scan failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

# Mount the static UI (report_ui directory) to serve at the root
# The html argument serves index.html at /
app.mount("/", StaticFiles(directory="report_ui", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
