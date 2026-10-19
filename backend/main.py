from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

try:
    from backend.graph import graph, GRAPH_CONFIG
except ImportError:
    from graph import graph, GRAPH_CONFIG

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class GenerateRequest(BaseModel):
    topic: str = ""

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/generate")
async def generate(req: GenerateRequest):
    async def event_generator():
        try:
            topic = req.topic.strip()
            if not topic:
                yield "event: error\ndata: Topic cannot be empty.\n\n"
                return

            final_blog = ""
            async for chunk in graph.astream({"topic": topic, "sections": []}, config=GRAPH_CONFIG, stream_mode="updates"):
                for node_name, node_output in chunk.items():
                    if isinstance(node_output, dict) and "blog" in node_output:
                        final_blog = node_output["blog"]
                    yield f"data: {node_name}\n\n"

            if final_blog:
                lines = final_blog.splitlines()
                yield "\n".join(f"data: {line}" for line in lines) + "\n\n"
        except Exception as e:
            err_msg = str(e).strip() or "An unexpected error occurred during generation."
            readable_msg = " ".join(err_msg.splitlines())
            yield f"event: error\ndata: {readable_msg}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Mount frontend directory to serve UI at root (/)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)


