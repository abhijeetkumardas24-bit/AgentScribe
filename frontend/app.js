// frontend/app.js

const STEPS = [
  { id: "router", label: "Topic Router (analyzing intent & research need)" },
  { id: "research", label: "Web Research (gathering factual sources via Tavily)" },
  { id: "orchestrator", label: "Outline Orchestrator (generating section plan)" },
  { id: "worker", label: "Section Workers (drafting section content from facts)" },
  { id: "reducer", label: "Blog Reducer (compiling markdown & references)" },
];

const form = document.getElementById("generator-form");
const topicInput = document.getElementById("topic");
const startBtn = document.getElementById("startBtn");
const progressContainer = document.getElementById("progress-container");
const progressList = document.getElementById("progress-list");
const outputContainer = document.getElementById("output-container");
const outputDiv = document.getElementById("output");
const copyBtn = document.getElementById("copyBtn");

let currentMarkdown = "";

// Initialize or reset progress items
function initProgressList() {
  progressList.innerHTML = "";
  STEPS.forEach((step, idx) => {
    const item = document.createElement("div");
    item.id = `step-${step.id}`;
    item.className = `progress-item ${idx === 0 ? "active" : "pending"}`;
    item.innerHTML = `
      <div class="progress-icon">${idx === 0 ? "" : idx + 1}</div>
      <div class="progress-label">${step.label}</div>
      <div class="progress-status">${idx === 0 ? "Working..." : "Pending"}</div>
    `;
    progressList.appendChild(item);
  });
  progressContainer.classList.remove("hidden");
}

// Tick off a completed progress step
function markStepCompleted(nodeId) {
  const stepIdx = STEPS.findIndex((s) => s.id === nodeId);
  if (stepIdx === -1) return;

  // If a step was skipped (e.g. research skipped by router), mark prior steps done/skipped
  for (let i = 0; i < stepIdx; i++) {
    const prev = STEPS[i];
    const prevEl = document.getElementById(`step-${prev.id}`);
    if (prevEl && prevEl.classList.contains("pending")) {
      prevEl.className = "progress-item completed";
      prevEl.querySelector(".progress-icon").innerHTML = "✓";
      prevEl.querySelector(".progress-status").textContent = "Skipped";
    }
  }

  // Mark current step completed
  const currentEl = document.getElementById(`step-${nodeId}`);
  if (currentEl) {
    currentEl.className = "progress-item completed";
    currentEl.querySelector(".progress-icon").innerHTML = "✓";
    currentEl.querySelector(".progress-status").textContent = "Completed";
  }

  // Activate next step
  if (stepIdx + 1 < STEPS.length) {
    const next = STEPS[stepIdx + 1];
    const nextEl = document.getElementById(`step-${next.id}`);
    if (nextEl && !nextEl.classList.contains("completed")) {
      nextEl.className = "progress-item active";
      nextEl.querySelector(".progress-icon").innerHTML = "";
      nextEl.querySelector(".progress-status").textContent = "Working...";
    }
  }
}

// Display error in the UI
function showError(message) {
  // Mark active step as failed if any
  const activeStep = progressList.querySelector(".progress-item.active");
  if (activeStep) {
    activeStep.className = "progress-item error";
    const icon = activeStep.querySelector(".progress-icon");
    if (icon) icon.innerHTML = "✕";
    const status = activeStep.querySelector(".progress-status");
    if (status) status.textContent = "Failed";
  }

  outputContainer.classList.remove("hidden");
  const cleanMsg = window.DOMPurify ? DOMPurify.sanitize(message) : message;
  outputDiv.innerHTML = `
    <div class="error-banner">
      <div class="error-banner-header">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="12" y1="8" x2="12" y2="12"></line>
          <line x1="12" y1="16" x2="12.01" y2="16"></line>
        </svg>
        <span>Generation Error</span>
      </div>
      <p class="error-banner-text">${cleanMsg}</p>
    </div>
  `;
  outputContainer.scrollIntoView({ behavior: "smooth", block: "start" });
}

// Render final markdown using marked + DOMPurify
function renderMarkdown(rawMd) {
  currentMarkdown = rawMd;

  // Mark all steps complete
  STEPS.forEach((step) => {
    const el = document.getElementById(`step-${step.id}`);
    if (el && !el.classList.contains("completed")) {
      el.className = "progress-item completed";
      el.querySelector(".progress-icon").innerHTML = "✓";
      el.querySelector(".progress-status").textContent = "Completed";
    }
  });

  if (window.marked && window.DOMPurify) {
    outputDiv.innerHTML = DOMPurify.sanitize(marked.parse(rawMd));
  } else {
    outputDiv.textContent = rawMd;
  }

  outputContainer.classList.remove("hidden");
  outputContainer.scrollIntoView({ behavior: "smooth", block: "start" });
}

// Copy button handler
if (copyBtn) {
  copyBtn.addEventListener("click", async () => {
    if (!currentMarkdown) return;
    try {
      await navigator.clipboard.writeText(currentMarkdown);
      const span = copyBtn.querySelector("span");
      const originalText = span.textContent;
      span.textContent = "Copied!";
      setTimeout(() => {
        span.textContent = originalText;
      }, 2000);
    } catch (err) {
      console.error("Failed to copy markdown: ", err);
    }
  });
}

// Form submit / generation handler
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const topic = topicInput.value.trim();
  if (!topic) return;

  // UI state for loading
  startBtn.disabled = true;
  startBtn.classList.add("loading");
  startBtn.querySelector(".btn-text").textContent = "Generating...";
  outputContainer.classList.add("hidden");
  outputDiv.innerHTML = "";
  currentMarkdown = "";

  initProgressList();

  const nodeIds = new Set(STEPS.map((s) => s.id));
  const apiUrl = window.location.port === "8000" ? "/generate" : "http://localhost:8000/generate";

  let hasError = false;

  try {
    const response = await fetch(apiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic }),
    });

    if (!response.ok) {
      throw new Error(`Server returned HTTP ${response.status}`);
    }

    if (!response.body) {
      throw new Error("Streaming is not supported by the response.");
    }

    // Read the stream with ReadableStream (not EventSource)
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const processEvent = (eventBlock) => {
      if (!eventBlock.trim() || hasError) return;
      let eventType = "message";
      const dataLines = [];
      const lines = eventBlock.split(/\r?\n/);
      for (const line of lines) {
        if (line.startsWith("event:")) {
          eventType = line.replace(/^event:\s?/, "").trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.replace(/^data:\s?/, ""));
        }
      }
      if (dataLines.length === 0) return;
      const eventData = dataLines.join("\n");

      // Handle SSE "error" event
      if (eventType === "error") {
        hasError = true;
        showError(eventData || "An error occurred during blog generation.");
        return;
      }

      const trimmed = eventData.trim();
      if (nodeIds.has(trimmed)) {
        markStepCompleted(trimmed);
      } else {
        renderMarkdown(eventData);
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      // SSE events are separated by double newlines (\n\n)
      const parts = buffer.split(/\r?\n\r?\n/);
      buffer = parts.pop() || "";

      for (const part of parts) {
        processEvent(part);
        if (hasError) {
          await reader.cancel();
          break;
        }
      }
      if (hasError) break;
    }

    if (!hasError && buffer.trim()) {
      processEvent(buffer);
    }
  } catch (error) {
    if (!hasError) {
      showError(error.message || "Failed to generate blog.");
    }
  } finally {
    startBtn.disabled = false;
    startBtn.classList.remove("loading");
    startBtn.querySelector(".btn-text").textContent = "Generate";
  }
});
