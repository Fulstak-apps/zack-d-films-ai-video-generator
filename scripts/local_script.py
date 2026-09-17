#!/usr/bin/env python3
"""Create a beats.json outline with a local Ollama model; no hosted LLM key needed."""
import argparse
import json
import os
import re
import urllib.request
from pathlib import Path


def generate(topic, model, endpoint):
    prompt = f"""Write a fact-conscious, curiosity-driven YouTube Short plan about: {topic}
Return ONLY JSON with this shape:
{{"project_name":"slug","topic":"...","aspect_ratio":"9:16","beats":[
{{"beat_id":"beat_1","narration":"...","shots":[
{{"shot_id":"beat_1_a","duration_sec":4,"scene_description":"visual scene","camera_move":"push_in","zoom_impact":false}}]}}]}}
Use 5-8 shots total, 30-50 seconds of spoken narration, short clear sentences, one shot per beat, and do not invent medical claims."""
    body = json.dumps({
        "model": model,
        "stream": False,
        "format": "json",
        "think": False,
        "options": {"num_predict": 1400, "temperature": 0.2},
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/api/chat", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = json.load(response)
    data = json.loads(payload.get("message", {}).get("content", ""))
    data["topic"] = topic
    data.setdefault("project_name", re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")[:48] or "short")
    data.setdefault("aspect_ratio", "9:16")
    if not data.get("beats"):
        raise ValueError("Ollama returned no beats")
    for beat in data["beats"]:
        if not beat.get("shots"):
            raise ValueError(f"beat {beat.get('beat_id')} has no shots")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "llama3.2"))
    parser.add_argument("--endpoint", default=os.getenv("OLLAMA_URL", "http://localhost:11434"))
    args = parser.parse_args()
    data = generate(args.topic, args.model, args.endpoint)
    target = Path(args.project_dir) / "beats.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {target}; review facts and visuals before paid generation.")


if __name__ == "__main__":
    main()
