"""
LAYER 2 — Memory.

Two responsibilities, kept separate on purpose:

1. RECALL  — load the facts we know about the user, to inject into the system
             prompt so every conversation starts already knowing who they are.

2. EXTRACT — after an exchange, ask the model itself whether anything is worth
             remembering long-term, and if so, save it.

The interesting design question this module answers is *what* to remember. We
don't dump whole conversations into long-term memory — that bloats fast and
makes recall noisy. Instead we store short, durable FACTS ("name is Praneeth",
"works at Cisco", "is building a local chatbot"), distilled by the model.

Storage is a plain JSON file on disk. No database needed at this scale, and you
can open the file and read exactly what it knows about you — which is the whole
privacy point.
"""

import json
import os
import httpx

MODEL = "qwen2.5:7b"            # keep in sync with server.py
OLLAMA_URL = "http://localhost:11434/api/chat"

# Memory lives next to this file, so it's easy to find and inspect.
MEMORY_FILE = os.path.join(os.path.dirname(__file__), "memory.json")


def _load() -> list[str]:
    """Read the list of remembered facts from disk. Empty list if none yet."""
    if not os.path.exists(MEMORY_FILE):
        return []
    try:
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save(facts: list[str]) -> None:
    with open(MEMORY_FILE, "w") as f:
        json.dump(facts, f, indent=2)


def recall() -> str:
    """
    Return remembered facts as a string for the system prompt, or "" if none.
    Called on every chat request (see the MEMORY HOOK in build_system_prompt).
    """
    facts = _load()
    if not facts:
        return ""
    return "\n".join(f"- {fact}" for fact in facts)


def list_facts() -> list[str]:
    """Raw list, for the /memory endpoint so the UI can show + clear them."""
    return _load()


def forget_all() -> None:
    """Wipe long-term memory. Wired to a 'forget me' button in the UI."""
    _save([])


# The prompt that turns the model into a memory-extractor. We force it to reply
# with strict JSON so we can parse it reliably — no prose, no markdown.
_EXTRACT_PROMPT = """You are a memory extraction system. Read the exchange below \
and decide if it contains any durable facts worth remembering about the user \
long-term — their name, job, location, preferences, ongoing projects, or stable \
personal details.

Do NOT remember: one-off questions, trivia, things the assistant said, or \
anything transient. Only durable facts ABOUT THE USER.

Reply with ONLY a JSON array of short fact strings. If nothing is worth \
remembering, reply with an empty array [].

Examples:
  User: "My name is Sam and I work at Acme" -> ["User's name is Sam", "User works at Acme"]
  User: "What's the capital of France?" -> []

Exchange:
User: {user}
Assistant: {assistant}

JSON array:"""


async def extract_and_store(user_msg: str, assistant_msg: str) -> list[str]:
    """
    After a reply finishes, ask the model if anything is worth remembering.
    Runs as a quick, separate, non-streaming call. New facts are de-duplicated
    against what we already know (case-insensitive) before saving.

    Returns the list of newly-added facts (for logging / debugging).
    """
    prompt = _EXTRACT_PROMPT.format(user=user_msg, assistant=assistant_msg)
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(OLLAMA_URL, json=payload)
            content = resp.json().get("message", {}).get("content", "").strip()
    except (httpx.HTTPError, json.JSONDecodeError):
        return []   # extraction failing should never break the chat

    # The model sometimes wraps JSON in ```json fences — strip them.
    content = content.replace("```json", "").replace("```", "").strip()

    try:
        new_facts = json.loads(content)
        if not isinstance(new_facts, list):
            return []
    except json.JSONDecodeError:
        return []

    existing = _load()
    existing_lower = {f.lower() for f in existing}
    added = []
    for fact in new_facts:
        if isinstance(fact, str) and fact.strip() and fact.lower() not in existing_lower:
            existing.append(fact.strip())
            existing_lower.add(fact.lower())
            added.append(fact.strip())

    if added:
        _save(existing)
    return added
