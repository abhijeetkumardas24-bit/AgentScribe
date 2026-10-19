# AI Blog Generator

An end-to-end multi-agent AI blog generation system powered by **LangGraph**, **FastAPI**, **Groq (Llama 3 / GPT-OSS)**, and **Tavily Web Search**, paired with a responsive modern frontend.

---

## What It Does

- **Intent & Research Routing**: Analyzes the submitted topic to decide whether real-time web research is required.
- **Autonomous Web Research**: Retrieves factual sources and snippets using the Tavily API if research is necessary, automatically skipping research if Tavily fails or is unconfigured.
- **Structured Blog Planning**: Creates a coherent outline with section briefs using Groq with Pydantic structured output, automatically retrying once if schema parsing fails.
- **Parallel Section Drafting**: Fans out section generation across concurrent LangGraph workers bounded to a maximum of 3 concurrent requests to respect rate limits.
- **Markdown Compilation & References**: Assembles the completed markdown article with structured headings and appended source citations.
- **Real-Time SSE Streaming**: Emits live progress events for each pipeline node (router, research, orchestrator, worker, reducer) and streams the final article or readable error alerts via Server-Sent Events.

---

## Architecture

`mermaid
graph TD
    User([User / Browser UI]) -->|POST /generate| API[FastAPI Server]
    API -->|astream| Graph[LangGraph Pipeline]

    subgraph LangGraph Multi-Agent Workflow
        START((START)) --> Router[Topic Router]
        Router -->|needs_research = true| Research[Tavily Web Research]
        Router -->|needs_research = false| Orchestrator[Outline Orchestrator]
        Research -->|injects facts| Orchestrator

        Orchestrator -->|Send worker 1..N| Workers[Parallel Workers<br/>max_concurrency: 3]
        Workers -->|drafted sections| Reducer[Blog Reducer]
        Reducer --> END((END))
    end

    Graph -.->|SSE node updates & final markdown| API
    API -.->|SSE stream: data / event: error| User
`

---

## Why Router and Orchestrator-Worker

1. **Router eliminates redundant search latency**: It selectively triggers external research only for queries that require factual or up-to-date data, conserving search API quota and cutting response times for self-contained topics.
2. **Decoupled research resilience**: By isolating web research in its own node with graceful fallbacks, search outages or missing API keys never break generation--the workflow simply continues with foundational knowledge.
3. **Orchestrator establishes narrative coherence**: Generating a comprehensive section outline upfront guarantees consistent narrative flow and prevents overlap between individual sections before writing starts.
4. **Worker parallelism maximizes throughput safely**: Drafting sections concurrently drastically cuts total generation time, while capping execution with max_concurrency: 3 and built-in retries prevents Groq rate limit exhaustion.

---

## How to Run Locally

### 1. Prerequisites
- Python 3.10+
- Groq API Key ([https://console.groq.com](https://console.groq.com))
- Tavily API Key ([https://tavily.com](https://tavily.com), optional but recommended for live web research)

### 2. Clone and Setup Environment
`ash
git clone https://github.com/your-username/blog-project.git
cd blog-project

# Create and activate a virtual environment
python -m venv venv

# Windows:
venv\Scripts\activate

# macOS / Linux:
source venv/bin/activate
`

### 3. Install Dependencies
`ash
pip install -r backend/requirements.txt
`

### 4. Configure Environment Variables
Copy .env.example to .env in the project root:
`ash
cp .env.example .env
`
Edit .env and insert your API keys:
`env
GROQ_API_KEY=gsk_your_groq_api_key_here
TAVILY_API_KEY=tvly_your_tavily_api_key_here
GROQ_MODEL=openai/gpt-oss-120b
`

### 5. Start the Application
Run the backend server from inside the ackend directory:
`ash
cd backend
uvicorn main:app --reload
`
Open your browser and navigate to **http://localhost:8000** to access the UI.

---

## Deployment

### Production Start Command
On production platforms (Render, Railway, Fly.io, Heroku, AWS):
`ash
uvicorn main:app --host 0.0.0.0 --port 
`
*(Run from inside the ackend directory, or use Procfile: cd backend && uvicorn main:app --host 0.0.0.0 --port )*

### Environment Variables for Production
Set the following environment variables in your deployment dashboard:
- GROQ_API_KEY: Your Groq API key
- TAVILY_API_KEY: Your Tavily API key
- GROQ_MODEL: Model name (default: openai/gpt-oss-120b)
- PORT: Server port (assigned automatically by most hosting providers)
