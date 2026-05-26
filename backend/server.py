"""
Local chatbot backend — the foundation.

This is LAYER 1: a clean chat loop between your frontend and a local Ollama model.
It is deliberately structured so the next three layers bolt on without rewrites:

    LAYER 2 (memory) -> see the `# === MEMORY HOOK ===` markers
    LAYER 3 (RAG)    -> see the `# === RAG HOOK ===` markers
    LAYER 4 (tools)  -> see the `# === TOOLS HOOK ===` markers

Run it:
    pip install fastapi uvicorn httpx
    uvicorn server:app --reload --port 8000

Talks to Ollama at localhost:11434 (Ollama's default). Make sure you've run:
    ollama pull qwen2.5:7b        # or whatever current tag you picked
    ollama serve                  # usually already running
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import json

import memory   # LAYER 2 — long-term memory module

# Change this to the model tag you actually pulled in Ollama.
MODEL = "qwen2.5:7b"
OLLAMA_URL = "http://localhost:11434/api/chat"

app = FastAPI()

# CORS so the browser frontend (different port) can call this backend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # fine for local dev; tighten later
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    role: str       # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


def build_system_prompt() -> str:
    """
    The system prompt is where every later layer leaves its mark.
    Right now it's just a personality. Later layers will INJECT into it.
    """
    base = "You are a helpful, concise local AI assistant running entirely on the user's machine."

    # === MEMORY HOOK ===  (LAYER 2 — now wired up)
    # Pull the durable facts we've learned about the user and tell the model.
    remembered = memory.recall()
    if remembered:
        base += (
            "\n\nThings you remember about the user from past conversations. "
            "Use these naturally; don't recite them back unprompted:\n"
            + remembered
        )

    # === RAG HOOK ===
    # LAYER 3: when the user's question matches indexed docs, retrieve and inject:
    #   chunks = rag.search(latest_user_message)
    #   base += f"\n\nRelevant context from the user's documents:\n{chunks}"

    return base


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    Streams the model's reply token-by-token back to the frontend.
    Streaming is what makes it feel like a real chatbot instead of a long pause.
    """
    # Assemble the full message list: system prompt + conversation history.
    messages = [{"role": "system", "content": build_system_prompt()}]
    messages += [{"role": m.role, "content": m.content} for m in req.messages]

    # Grab the latest user message now — we'll use it for memory extraction
    # after the assistant's reply finishes streaming.
    latest_user = req.messages[-1].content if req.messages else ""

    # === TOOLS HOOK ===
    # LAYER 4: this single request becomes a LOOP. Instead of streaming straight
    # to the user, you check whether the model asked to call a tool, run it,
    # append the result, and call the model again — repeating until it answers.
    # That loop is the "agentic" upgrade. For now, one call, straight through.

    async def event_stream():
        full_reply = ""   # accumulate the assistant's reply for memory extraction
        payload = {"model": MODEL, "messages": messages, "stream": True}
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", OLLAMA_URL, json=payload) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    token = data.get("message", {}).get("content", "")
                    if token:
                        full_reply += token
                        # Server-Sent-Events style: one token per chunk.
                        yield f"data: {json.dumps({'token': token})}\n\n"
                    if data.get("done"):
                        yield "data: [DONE]\n\n"

        # === MEMORY HOOK ===  (LAYER 2 — now wired up)
        # The reply is done streaming. Ask the model whether this exchange held
        # anything worth remembering long-term, and save it if so. This runs
        # after [DONE] so it never slows down the user-visible response.
        await memory.extract_and_store(latest_user, full_reply)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL}


@app.get("/memory")
async def get_memory():
    """Return the durable facts the assistant currently remembers."""
    return {"facts": memory.list_facts()}


@app.post("/memory/forget")
async def forget_memory():
    """Wipe long-term memory entirely."""
    memory.forget_all()
    return {"status": "cleared"}
