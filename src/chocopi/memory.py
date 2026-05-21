"""Session memory storage and formatting"""
import copy
import json
import os
import urllib.request
from pathlib import Path
import yaml
from loguru import logger
from chocopi.config import PROJECT_ROOT, CONFIG

MEMORY_TYPES = ("joke", "vocab", "story", "fact", "topic")
MAX_ITEMS_PER_TYPE = {
    "joke": 10,
    "vocab": 20,
    "story": 10,
    "fact": 15,
    "topic": 15,
}


def _memory_path(profile_name):
    data_dir = PROJECT_ROOT / "data"
    return data_dir / f"memory_{profile_name}.yml"


def _default_memory():
    return {
        "summary": "",
        "progress": {
            "new_vocab": [],
            "mistakes": [],
            "strengths": [],
            "next_focus": "",
        },
        "recent_items": [],
        "recent_user_requests": [],
    }


def normalize_memory(memory):
    if not isinstance(memory, dict):
        return _default_memory()

    memory.setdefault("summary", "")
    memory.setdefault("progress", {})
    memory["progress"].setdefault("new_vocab", [])
    memory["progress"].setdefault("mistakes", [])
    memory["progress"].setdefault("strengths", [])
    memory["progress"].setdefault("next_focus", "")
    memory.setdefault("recent_items", [])
    memory.setdefault("recent_user_requests", [])
    return memory


def load_memory(profile_name):
    path = _memory_path(profile_name)
    if not path.exists():
        return _default_memory()
    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or _default_memory()
    return normalize_memory(loaded)


def save_memory(profile_name, memory):
    path = _memory_path(profile_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(memory, file, allow_unicode=True, sort_keys=False)


def build_memory_block(memory):
    summary = memory.get("summary", "").strip()
    requests = memory.get("recent_user_requests", [])
    items = memory.get("recent_items", [])
    progress = memory.get("progress", {})

    parts = []
    if summary:
        parts.append(f"Summary: {summary}")
    if requests:
        recent_requests = "; ".join(requests[-5:])
        parts.append(f"Recent user requests: {recent_requests}")
    if progress:
        new_vocab = ", ".join(progress.get("new_vocab", [])[:5])
        mistakes = ", ".join(progress.get("mistakes", [])[:5])
        strengths = ", ".join(progress.get("strengths", [])[:5])
        next_focus = progress.get("next_focus", "")
        progress_lines = []
        if new_vocab:
            progress_lines.append(f"New vocab: {new_vocab}")
        if mistakes:
            progress_lines.append(f"Mistakes: {mistakes}")
        if strengths:
            progress_lines.append(f"Strengths: {strengths}")
        if next_focus:
            progress_lines.append(f"Next focus: {next_focus}")
        if progress_lines:
            parts.append("Progress: " + " | ".join(progress_lines))

    for item_type in MEMORY_TYPES:
        entries = [item["text"] for item in items if item.get("type") == item_type]
        if entries:
            parts.append(f"Recent {item_type}s (avoid repeating): " + " | ".join(entries[-5:]))

    if not parts:
        return "None"
    return "\n".join(parts)


def _append_item(memory, item_type, text, max_items):
    memory.setdefault("recent_items", [])
    memory["recent_items"].append({"type": item_type, "text": text})
    # Keep only the last max_items for that type
    filtered = [item for item in memory["recent_items"] if item.get("type") == item_type]
    if len(filtered) > max_items:
        to_remove = len(filtered) - max_items
        kept = []
        for item in memory["recent_items"]:
            if item.get("type") == item_type and to_remove > 0:
                to_remove -= 1
                continue
            kept.append(item)
        memory["recent_items"] = kept


def update_memory(memory, user_text, assistant_text):
    if not memory:
        return

    memory.setdefault("recent_user_requests", [])

    if user_text:
        memory["recent_user_requests"].append(user_text.strip())
        memory["recent_user_requests"] = memory["recent_user_requests"][-10:]

    if memory["recent_user_requests"]:
        memory["summary"] = "Recent topics: " + "; ".join(memory["recent_user_requests"][-3:])


def merge_summary(memory, summary_data):
    if not summary_data:
        return memory
    memory = normalize_memory(memory)

    if summary := summary_data.get("summary"):
        memory["summary"] = summary.strip()

    recent_requests = summary_data.get("recent_user_requests", [])
    if recent_requests:
        memory.setdefault("recent_user_requests", [])
        for request in recent_requests:
            if request:
                normalized = str(request).strip()
                if normalized and normalized not in memory["recent_user_requests"]:
                    memory["recent_user_requests"].append(normalized)
        memory["recent_user_requests"] = memory["recent_user_requests"][-10:]

    progress = summary_data.get("progress", {})
    if progress:
        memory["progress"] = {
            "new_vocab": [str(item).strip() for item in progress.get("new_vocab", []) if str(item).strip()],
            "mistakes": [str(item).strip() for item in progress.get("mistakes", []) if str(item).strip()],
            "strengths": [str(item).strip() for item in progress.get("strengths", []) if str(item).strip()],
            "next_focus": str(progress.get("next_focus", "")).strip(),
        }

    for item in summary_data.get("recent_items", []) or []:
        item_type = (item.get("type") or "").strip().lower()
        text = (item.get("text") or "").strip()
        if not item_type or not text or item_type not in MEMORY_TYPES:
            continue
        _append_item(memory, item_type, text, MAX_ITEMS_PER_TYPE[item_type])

    return memory


def _extract_output_text(response_data):
    output_text = response_data.get("output_text")
    if output_text:
        return output_text
    for item in response_data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                return content.get("text", "")
    return ""


def _format_transcript_line(entry):
    role = entry.get("role", "user")
    label = "User" if role == "user" else "Choco"
    text = entry.get("text", "").strip()
    if not text:
        return ""
    return f"{label}: {text}"


def _format_transcript(transcript_log):
    lines = []
    for entry in transcript_log:
        line = _format_transcript_line(entry)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _format_transcript_tail(transcript_log, max_chars):
    lines = []
    total = 0
    for entry in reversed(transcript_log):
        line = _format_transcript_line(entry)
        if not line:
            continue
        line_len = len(line) + (1 if lines else 0)
        if total + line_len > max_chars:
            break
        lines.append(line)
        total += line_len
    return "\n".join(reversed(lines))


def _build_summary_payload(profile, transcript_text, memory):
    native_language = CONFIG.languages[profile["native_language"]].language_name
    instructions = CONFIG.prompts.summary.format(
        native_language=native_language
    )
    summary = memory.get("summary", "").strip()
    if summary:
        transcript_text = f"Existing summary: {summary}\n\n{transcript_text}"

    payload = copy.deepcopy(CONFIG.summary_model)
    payload["instructions"] = instructions
    payload["input"] = [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": transcript_text}],
        },
    ]
    return payload


def summarize_session(profile_name, profile, transcript_log, memory):
    if not transcript_log:
        return memory

    transcript_text = _format_transcript(transcript_log)
    max_chars = CONFIG.summary.max_chars
    if len(transcript_text) > max_chars:
        transcript_text = _format_transcript_tail(transcript_log, max_chars)

    payload = _build_summary_payload(profile, transcript_text, memory)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set; skipping memory summarization")
        return memory

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8")
        except Exception:
            error_body = ""
        logger.warning("Memory summarization failed: {} {}", exc, error_body)
        return memory
    except Exception as exc:
        logger.warning("Memory summarization failed: {}", exc)
        return memory

    output_text = _extract_output_text(response_data)
    if not output_text:
        logger.warning("Memory summarization returned no text")
        return memory

    try:
        summary_data = json.loads(output_text)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse memory summary JSON: {}", exc)
        return memory

    return merge_summary(memory, summary_data or {})
