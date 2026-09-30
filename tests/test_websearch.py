import httpx

from aegis.system2.prompt import build_free_messages
from aegis.system2.websearch import SearchOutcome, SearchResult, WebSearcher, format_for_prompt, parse_duckduckgo

DDG_PAGE = """
<div class="result results_links results_links_deep result--ad ">
  <a class="result__a" href="https://ads.example.com/">Sponsored</a>
</div>
<div class="result results_links results_links_deep web-result ">
  <h2 class="result__title"><a rel="nofollow" class="result__a" href="https://fastapi.tiangolo.com/advanced/stream-data/">Stream Data - FastAPI</a></h2>
  <a class="result__snippet" href="https://fastapi.tiangolo.com/">Use <b>StreamingResponse</b> &amp; friends.</a>
</div>
<div class="result results_links web-result ">
  <a class="result__a" href="javascript:alert(1)">Bad link</a>
</div>
<div class="result results_links web-result ">
  <a class="result__a" href="//example.org/page">Protocol-relative</a>
</div>
"""

WIKI_JSON = {"query": {"search": [{"title": "FastAPI", "snippet": "a <span>web</span> framework"}]}}


def searcher(handler, **kw) -> WebSearcher:
    return WebSearcher(client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


def test_parse_duckduckgo_skips_ads_and_unsafe_links():
    results = parse_duckduckgo(DDG_PAGE, 5)
    assert [r.title for r in results] == ["Stream Data - FastAPI", "Protocol-relative"]
    assert results[0].snippet == "Use StreamingResponse & friends."
    assert results[1].url == "https://example.org/page"


def test_uses_duckduckgo_when_it_answers():
    out = searcher(lambda req: httpx.Response(200, text=DDG_PAGE)).search("fastapi streaming")
    assert out.status == "ok" and out.provider == "duckduckgo" and len(out.results) == 2


def test_offline_stops_at_first_network_error():
    calls = []

    def handler(req):
        calls.append(req.url.host)
        raise httpx.ConnectError("nodename nor servname provided", request=req)

    out = searcher(handler).search("anything")
    assert out.status == "offline"
    assert calls == ["html.duckduckgo.com"]  # no pointless retries against other providers


def test_falls_back_to_wikipedia_when_duckduckgo_blocks():
    def handler(req):
        if req.url.host == "html.duckduckgo.com":
            return httpx.Response(403, text="blocked")
        return httpx.Response(200, json=WIKI_JSON)

    out = searcher(handler).search("fastapi")
    assert out.status == "ok" and out.provider == "wikipedia"
    assert out.results[0].url == "https://en.wikipedia.org/wiki/FastAPI"
    assert out.results[0].snippet == "a web framework"


def test_unavailable_when_every_provider_fails_without_network_error():
    out = searcher(lambda req: httpx.Response(500)).search("x")
    assert out.status == "unavailable" and "duckduckgo" in out.error and "wikipedia" in out.error


def test_searxng_is_tried_first_when_configured():
    def handler(req):
        if req.url.host == "searx.local":
            return httpx.Response(200, json={"results": [{"title": "Own index", "url": "https://docs.local/x", "content": "c"}]})
        raise AssertionError("public providers must not be called")

    out = searcher(handler, searxng_url="http://searx.local/").search("x")
    assert out.provider == "searxng" and out.results[0].title == "Own index"


def test_prompt_carries_numbered_untrusted_sources():
    outcome = SearchOutcome("ok", "duckduckgo", [SearchResult("T", "https://a.b", "snippet")])
    text = format_for_prompt(outcome)
    assert "[1] T" in text and "https://a.b" in text and "untrusted" in text
    assert format_for_prompt(SearchOutcome("offline")) is None

    msgs = build_free_messages("latest?", [{"role": "user", "content": "hi"}], web_context=text)
    assert [m["role"] for m in msgs] == ["system", "user", "system", "user"]
    assert msgs[-2]["content"] == text and msgs[-1]["content"] == "latest?"
