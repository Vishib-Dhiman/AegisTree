import base64
import json

import pytest

from aegis.system2.images import MAX_IMAGE_BYTES, MAX_IMAGES, normalize_images, screenshot_note

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


# --- Validation ---------------------------------------------------------------

def test_data_url_prefix_and_whitespace_are_stripped():
    out = normalize_images([f"data:image/png;base64,{b64(PNG)}", b64(JPEG)[:10] + "\n" + b64(JPEG)[10:]])
    assert out == [b64(PNG), b64(JPEG)]


def test_empty_entries_are_ignored():
    assert normalize_images(["", "   ", None]) == []
    assert normalize_images(None) == []


def test_non_images_are_rejected():
    with pytest.raises(ValueError, match="not a PNG"):
        normalize_images([b64(b"just some text pretending to be an image")])


def test_bad_base64_is_rejected():
    with pytest.raises(ValueError, match="not valid base64"):
        normalize_images(["@@@not base64@@@"])


def test_too_many_images_are_rejected():
    with pytest.raises(ValueError, match=f"at most {MAX_IMAGES}"):
        normalize_images([b64(PNG)] * (MAX_IMAGES + 1))


def test_oversized_images_are_rejected():
    big = PNG + b"\x00" * MAX_IMAGE_BYTES
    with pytest.raises(ValueError, match="larger than"):
        normalize_images([b64(big)])


def test_screenshot_note():
    assert screenshot_note(0) == ""
    assert "1 screenshot;" in screenshot_note(1)
    assert "3 screenshots" in screenshot_note(3)


# --- Server wiring ------------------------------------------------------------

class RecordingGenerator:
    """Records what the server sends; optionally claims no vision support."""

    def __init__(self, vision=True, reply="ok"):
        self.vision = vision
        self.reply = reply
        self.chat_calls = []
        self.stream_calls = []

    def supports_vision(self, model_name=None):
        return self.vision

    def chat_stream(self, messages):
        self.chat_calls.append(messages)
        yield {"thinking": "", "response": self.reply, "done": True}

    def complete_stream(self, prompt, images=None):
        self.stream_calls.append((prompt, images))
        yield {"thinking": "", "response": "```python\ndef persist_session_token(token: str) -> str:\n    return token\n```", "done": True}


def _events(stream):
    return [json.loads(e[len("data: "):]) for e in stream]


def test_free_stream_attaches_images_to_the_last_user_message(monkeypatch):
    import aegis.ui.server as srv

    gen = RecordingGenerator()
    monkeypatch.setattr(srv, "generator", gen)
    events = _events(srv._free_stream("r1", "what is in this screenshot?", [], images=[b64(PNG)]))

    last = gen.chat_calls[0][-1]
    assert last["role"] == "user" and last["images"] == [b64(PNG)]
    assert events[0]["images"] == 1 and events[0]["vision_routed"] is False
    assert events[-1]["images"] == 1


def test_text_only_models_are_routed_to_the_vision_model(monkeypatch):
    import aegis.ui.server as srv

    blind = RecordingGenerator(vision=False)
    seeing = RecordingGenerator(vision=True, reply="a login form")
    monkeypatch.setattr(srv, "generator", blind)
    monkeypatch.setattr(srv, "OllamaGenerator", lambda config: seeing)
    events = _events(srv._free_stream("r2", "what is this?", [], images=[b64(PNG)]))

    assert not blind.chat_calls and seeing.chat_calls
    assert events[0]["vision_routed"] is True
    assert events[0]["model"] == srv.config_manager.config.vision_model
    assert events[-1]["aegis"]["text"] == "a login form"


def test_no_images_keeps_the_active_model(monkeypatch):
    import aegis.ui.server as srv

    blind = RecordingGenerator(vision=False)
    monkeypatch.setattr(srv, "generator", blind)
    events = _events(srv._free_stream("r3", "hello", []))
    assert blind.chat_calls and events[0]["vision_routed"] is False
    assert "images" not in blind.chat_calls[0][-1]


def test_governed_stream_sends_images_to_the_leaf_call(monkeypatch, test_vault, tmp_path):
    import aegis.ui.server as srv
    from aegis.core.ingestion import WorkspaceIngestor
    from aegis.system1.graph import MemoryGraph
    from aegis.system1.router import Router
    from starlette.requests import Request as StarletteRequest

    # Isolated graph over a fresh demo vault, so the shared .aegis store is untouched
    graph = MemoryGraph(storage_dir=tmp_path / "store")
    nodes, edges = WorkspaceIngestor.ingest_adrs(test_vault)
    graph.replace_corpus(nodes, edges)
    gen = RecordingGenerator()
    monkeypatch.setattr(srv, "generator", gen)
    monkeypatch.setattr(srv, "free_mode", False)
    monkeypatch.setattr(srv, "workspace_root", test_vault)
    monkeypatch.setattr(srv, "graph", graph)
    monkeypatch.setattr(srv, "router", Router(graph=graph, config=srv.config, engine=srv.router.engine))
    req = srv.RunRequest(
        prompt="Add a persist_session_token function that stores the session token using our current vault standard.",
        images=[f"data:image/png;base64,{b64(PNG)}"],
    )
    scope = {"type": "http", "client": ("127.0.0.1", 1), "headers": []}
    resp = srv.run_prompt_stream(req, StarletteRequest(scope))

    async def collect():
        return [chunk async for chunk in resp.body_iterator]

    import asyncio
    chunks = asyncio.run(collect())
    events = [json.loads(c[len("data: "):]) for c in chunks if isinstance(c, str) and c.startswith("data: ")]
    init = next(e for e in events if e["type"] == "init")
    assert init["images"] == 1
    prompt, images = gen.stream_calls[0]
    assert images == [b64(PNG)]
    assert "attached 1 screenshot" in prompt


def test_bad_images_are_rejected_with_400(monkeypatch):
    import aegis.ui.server as srv
    from fastapi import HTTPException
    from starlette.requests import Request as StarletteRequest

    req = srv.RunRequest(prompt="look", images=[b64(b"not an image at all")])
    scope = {"type": "http", "client": ("127.0.0.1", 1), "headers": []}
    with pytest.raises(HTTPException) as exc:
        srv.run_prompt_stream(req, StarletteRequest(scope))
    assert exc.value.status_code == 400
