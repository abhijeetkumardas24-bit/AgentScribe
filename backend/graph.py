# backend/graph.py
"""LangGraph implementation for blog generation.

State fields:
- topic: the blog topic (str)
- plan: list of SectionSpec objects (title and brief)
- sections: list of (index, markdown) tuples produced by workers
- blog: final markdown document (str)
"""

import os
import sys
import operator
from typing import TypedDict, List, Tuple, Dict, Any, Annotated
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
try:
    from langgraph.types import Send
except ImportError:
    from langgraph.graph import Send
from tavily import TavilyClient

from dotenv import load_dotenv
load_dotenv()

# ---------------------------------------------------------------------------
# Pydantic models for structured output from Groq
# ---------------------------------------------------------------------------
class RouterOutput(BaseModel):
    """Router decision whether research is needed."""
    needs_research: bool = Field(..., description="Whether the topic requires web research")

class SectionSpec(BaseModel):
    """Specification for a single blog section."""
    title: str = Field(..., description="Title of the section")
    brief: str = Field(..., description="One‑line summary of the section")

class SectionsOutput(BaseModel):
    """Structured output containing section specifications."""
    sections: List[SectionSpec] = Field(..., description="List of section specifications")

class BlogState(TypedDict):
    topic: str
    plan: List[SectionSpec]
    sections: Annotated[List[Tuple[int, str]], operator.add]
    blog: str
    research: List[Dict[str, Any]]
    needs_research: bool


def get_model_name() -> str:
    """Return configured model or fallback to available Groq model."""
    configured = os.getenv("GROQ_MODEL", "").strip()
    if configured and configured != "gemma2-9b-it":
        return configured
    return "openai/gpt-oss-120b"

# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------
def router(state: Dict[str, Any]) -> Dict[str, Any]:
    """Determine if research is needed for the given topic."""
    topic = state.get("topic", "")
    model_name = get_model_name()
    llm = ChatGroq(model=model_name, temperature=0.1, max_retries=2).with_structured_output(RouterOutput)
    prompt = f"Does the topic '{topic}' require web research to write a factual blog? Output structured response."
    try:
        res = llm.invoke(prompt)
        if res is None or not hasattr(res, "needs_research"):
            raise ValueError("Invalid structured output from router")
        return {"needs_research": res.needs_research}
    except Exception:
        # Invalid structured output -> retry once
        try:
            res = llm.invoke(prompt)
            if res is None or not hasattr(res, "needs_research"):
                raise ValueError("Invalid structured output from router after retry")
            return {"needs_research": res.needs_research}
        except Exception:
            return {"needs_research": bool(topic.strip())}

def research(state: Dict[str, Any]) -> Dict[str, Any]:
    """Search the web using Tavily and store up to 5 results in state.
    
    If Tavily fails (network error, rate limit, invalid key, etc.),
    skip research and continue the workflow.
    """
    topic = state.get("topic", "")
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return {"research": []}
    try:
        client = TavilyClient(api_key=api_key)
        response = client.search(query=topic, max_results=5)
        raw_results = response.get("results", []) if isinstance(response, dict) else response
        filtered = [
            {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
            for r in raw_results if isinstance(r, dict)
        ]
        return {"research": filtered}
    except Exception:
        # Tavily fails -> skip research and continue
        return {"research": []}

def orchestrator(state: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a short plan (titles + brief) for the blog.

    Uses Groq's Chat model with structured output (via Pydantic) to ensure
    we always get a predictable list of sections. Retries once if structured output fails.
    """
    topic = state.get("topic", "Untitled")
    model_name = get_model_name()
    llm = ChatGroq(model=model_name, temperature=0.1, max_retries=2)

    # Build system prompt with optional research sources
    system_prompt = (
        "You are a concise blog planner. Given a topic, produce a short plan consisting "
        "of 4‑6 sections. For each section return a title and a one‑sentence brief. "
        "Do NOT write any Markdown or extra commentary – just the structured data."
    )
    # Include research facts if available
    research_items = state.get("research", [])
    sources = "\n".join([f"- {r['title']} ({r['url']})" for r in research_items])
    if sources:
        system_prompt = f"{system_prompt}\nUse only facts from the following sources:\n{sources}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Topic: {topic}"},
    ]

    structured_llm = llm.with_structured_output(SectionsOutput)
    try:
        response = structured_llm.invoke(messages)
        if not response or not getattr(response, "sections", None) or len(response.sections) == 0:
            raise ValueError("Invalid structured output: outline contains no sections.")
    except Exception:
        # Invalid structured output -> retry once
        response = structured_llm.invoke(messages)
        if not response or not getattr(response, "sections", None) or len(response.sections) == 0:
            raise ValueError("Failed to generate a valid blog outline after retry.")

    # Store full spec for workers
    return {"plan": response.sections, "topic": topic}

def map_workers(state: Dict[str, Any]) -> List[Send]:
    """Fan out parallel worker jobs for each section in the plan."""
    plan = state.get("plan", [])
    research_items = state.get("research", [])
    return [
        Send("worker", {
            "index": i,
            "spec": spec,
            "research": research_items,
        })
        for i, spec in enumerate(plan)
    ]

def worker(state: Dict[str, Any]) -> Dict[str, Any]:
    """Generate markdown for a single section."""
    index: int = state["index"]
    spec = state.get("spec")
    if spec is None and "plan" in state and "index" in state:
        spec = state["plan"][index]

    title = getattr(spec, "title", None) or (spec.get("title") if isinstance(spec, dict) else "")
    brief = getattr(spec, "brief", None) or (spec.get("brief") if isinstance(spec, dict) else "")

    model_name = get_model_name()
    llm = ChatGroq(model=model_name, temperature=0.2, max_retries=2)
    system_prompt = (
        "You are a helpful writer. Expand the given brief into a short markdown "
        "section (max 150 words). Include a heading with the provided title."
    )
    research_items = state.get("research", [])
    sources = "\n".join([f"- {r['title']} ({r['url']})" for r in research_items])
    if sources:
        system_prompt = f"{system_prompt}\nTake facts only from the given sources:\n{sources}"
    user_msg = f"Title: {title}\nBrief: {brief}"
    md = llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]).content
    return {"sections": [(index, md)]}

def reducer(state: Dict[str, Any]) -> Dict[str, Any]:
    """Sort sections by index and concatenate them into a full blog markdown."""
    sections: List[Tuple[int, str]] = list(state.get("sections", []))
    sections.sort(key=lambda pair: pair[0])
    body = "\n\n".join(md for _, md in sections)
    title = f"# Blog on {state.get('topic', 'Untitled')}"
    blog = f"{title}\n\n{body}"
    # Append references if research results exist
    research_items = state.get("research", [])
    if research_items:
        refs = "\n".join([f"- [{r['title']}]({r['url']})" for r in research_items])
        blog = f"{blog}\n\n## References\n{refs}"
    return {"blog": blog}

# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------
builder = StateGraph(BlogState)

builder.add_node("router", router)
builder.add_node("research", research)
builder.add_node("orchestrator", orchestrator)
builder.add_node("worker", worker)
builder.add_node("reducer", reducer)

# Wiring
builder.add_edge(START, "router")
builder.add_conditional_edges("router", lambda state: "research" if state.get("needs_research", False) else "orchestrator")
builder.add_edge("research", "orchestrator")
builder.add_conditional_edges("orchestrator", map_workers, ["worker"])
builder.add_edge("worker", "reducer")
builder.add_edge("reducer", END)

graph = builder.compile()

GRAPH_CONFIG = {"max_concurrency": 3}

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m backend.graph <topic>")
        sys.exit(1)
    topic = sys.argv[1]
    final_state = graph.invoke({"topic": topic, "sections": []}, config=GRAPH_CONFIG)
    print(final_state.get("blog", ""))

