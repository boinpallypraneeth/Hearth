# Project rules for Cursor

This is a local-first AI chatbot. The whole point is privacy: nothing leaves the
user's machine. Keep that principle in every suggestion.

## Hard constraints
- The model runs via Ollama at http://localhost:11434. NEVER suggest the cloud
  `openai` SDK, Anthropic SDK, or any hosted API. If a feature seems to need the
  cloud, flag it and propose a local alternative instead.
- Backend is FastAPI + httpx. Frontend is a single static HTML file (no build
  step, no framework) for now. Do not introduce React/Vite/webpack unless asked.
- On Apple Silicon: use `faiss-cpu`, not `faiss-gpu`. Sentence-transformers run on
  CPU/MPS fine.

## Style
- Prefer small, targeted edits over rewriting whole files. Show a diff.
- Plain-English comments that explain *why*, not just *what*.
- Keep the layered structure: the codebase grows by adding memory, then RAG, then
  tools — each behind the `# === X HOOK ===` markers already in server.py. Don't
  collapse the layers together.

## When extending
- New capability the agent can use? It should hang off the agent loop, not be
  wired ad-hoc into the route handler.
- Anything touching the user's files or the web is a "tool" — keep tools isolated
  and individually testable.
