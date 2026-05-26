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
import tools     # LAYER 4 — tools the agent can call

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
    base =  "You are Hearth, a private AI assistant created by Praneeth Boinpally." "You run entirely locally on the user's machine — nothing leaves their computer. ""If asked who made you, who created you, or what you are, say you are Hearth, ""a local assistant built by Praneeth Boinpally. Do not claim to be created by ""Anthropic, Alibaba, OpenAI, or any other company — those did not build you."

    # === TOOLS HOOK ===  (LAYER 4 — guidance)
    # Tell the model the tools exist and when to use them. The actual loop that
    # executes the calls lives in the /chat handler below.
    base += (
        "\n\nYou have tools available: web_search (for current/real-world facts you "
        "don't know or that may have changed) and calculate (for math). Prefer using "
        "a tool over guessing. After getting tool results, answer the user directly."
    )

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

    # === TOOLS HOOK ===  (LAYER 4 — the agentic loop)
    # The single call is now a LOOP. While the model wants to use tools, we run
    # them (non-streaming, because tool-calling and streaming don't mix), feed
    # results back, and ask again. Once the model stops calling tools, we stream
    # its final answer to the user. Status lines ("Searching…") are sent during
    # tool calls so the UI never looks frozen.
    MAX_STEPS = 5

    async def event_stream():
        full_reply = ""

        async with httpx.AsyncClient(timeout=None) as client:
            # ---- agentic phase: let the model call tools until it's ready ----
            for step in range(MAX_STEPS):
                payload = {
                    "model": MODEL,
                    "messages": messages,
                    "tools": tools.TOOL_SCHEMAS,
                    "stream": False,
                }
                resp = await client.post(OLLAMA_URL, json=payload)
                msg = resp.json().get("message", {})
                tool_calls = msg.get("tool_calls")

                if not tool_calls:
                    # No tool wanted — this message IS the answer. Keep it to
                    # stream below (re-ask with stream=True for the typewriter feel).
                    break

                # Record the assistant's tool-call turn, then run each tool.
                messages.append(msg)
                for call in tool_calls:
                    fn = call.get("function", {})
                    name = fn.get("name", "")
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try: args = json.loads(args)
                        except json.JSONDecodeError: args = {}

                    # Tell the UI what's happening (shown as a status line).
                    label = args.get("query") or args.get("expression") or ""
                    yield f"data: {json.dumps({'status': f'Using {name}: {label}'})}\n\n"

                    result = await tools.run_tool(name, args)
                    messages.append({"role": "tool", "content": result})

            # ---- answer phase: stream the final response token by token ----
            yield f"data: {json.dumps({'status': ''})}\n\n"   # clear status
            payload = {"model": MODEL, "messages": messages, "stream": True}
            async with client.stream("POST", OLLAMA_URL, json=payload) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    token = data.get("message", {}).get("content", "")
                    if token:
                        full_reply += token
                        yield f"data: {json.dumps({'token': token})}\n\n"
                    if data.get("done"):
                        yield "data: [DONE]\n\n"

        # === MEMORY HOOK ===  (LAYER 2)
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
