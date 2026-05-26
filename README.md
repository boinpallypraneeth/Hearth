# Hearth — a local-first AI chatbot

Your own private ChatGPT. Runs entirely on your machine via Ollama — no cloud, no
per-message cost, nothing leaves your computer. Built to grow in four layers:
chat → memory → documents (RAG) → tools (agentic).

This repo is **Layer 1: the foundation** — a clean, streaming chat loop between a
web UI and a local model. The next three layers bolt on at the marked hooks
without rewrites.

---

## Run it (5 minutes)

### 1. Get Ollama and a model
Install Ollama from ollama.com, then pull a model that does tool-calling well
(you'll need that in Layer 4). Check ollama.com/library for the current tag —
something in the Qwen-Coder / Qwen 7B family is a good 16GB-friendly pick:

```bash
ollama pull qwen2.5:7b      # confirm the current tag on ollama.com/library
```

Set the same tag in `backend/server.py` (the `MODEL` variable).

### 2. Start the backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --reload --port 8000
```

### 3. Open the frontend
Just open `frontend/index.html` in your browser. That's it — it'll connect to the
backend and the status dot turns green.

(For a "real" local server instead of file://, run `python -m http.server 5500`
inside `frontend/` and visit http://localhost:5500.)

---

## The roadmap — build it in layers

Each layer is independently useful and independently demoable. Don't skip ahead;
each one stands on the last.

**Layer 1 — Chat (this repo).** UI ⇄ backend ⇄ Ollama, streaming. Done.

**Layer 2 — Memory.** Persist conversations and facts about the user across
sessions. Look for `# === MEMORY HOOK ===` in `server.py`. Start dead simple: a
JSON file or SQLite storing past messages + a short "things I know about you"
list that gets injected into the system prompt. The hard/interesting question is
*when* to remember and *when* to recall — that's the real lesson here.

**Layer 3 — Documents (RAG).** Let it answer from files you give it. Add an
indexer (chunk files → embed with sentence-transformers → store in FAISS) and a
`search` step at `# === RAG HOOK ===`. The upgrade that makes it *agentic* RAG:
the model decides whether it needs to retrieve, and can retrieve again if the
first pass was thin — rather than blindly stuffing chunks every time.

**Layer 4 — Tools (the agentic jump).** Turn the single model call into a LOOP at
`# === TOOLS HOOK ===`. Give the model tools (web search, a calculator, file
read). Each turn: model either answers or asks to call a tool; you run it, feed
the result back, call again, until it answers. This is the leap from "chatbot" to
"assistant," and writing the loop yourself is the whole point.

---

## Shipping as both browser and desktop

You do NOT build it twice. The frontend is a web app; "desktop" is a packaging
step that wraps the same web app in its own window.

- **Browser:** already works — open `index.html`.
- **Desktop:** wrap it with **Tauri** (Rust-based, tiny binaries, recommended) or
  **Electron** (heavier, more familiar if you know Node). The web UI is unchanged;
  the wrapper just gives it a native window, an app icon, and the ability to launch
  the Python backend alongside it. Add this at the very end, after Layer 4 — it's
  a delivery concern, not an architecture one.

---

## Project shape
```
local-chatbot/
├── backend/
│   ├── server.py          # the chat loop + hooks for every later layer
│   └── requirements.txt
├── frontend/
│   └── index.html         # the whole UI, one file, no build step
├── .cursor/rules/
│   └── project.md          # keeps Cursor's agent on-task while you extend this
└── README.md
```
