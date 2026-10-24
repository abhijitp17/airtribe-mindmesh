"""AnthropicProvider request shapes per model, refusal/truncation handling (no network calls)."""
from types import SimpleNamespace

import anthropic
import pytest

from app.ai.gateway import (SERVER_FALLBACK_BETA, AnthropicProvider, Gateway, ModelError, ModelRefused,
                            Request)

REQ = Request(task="tutor", system="sys", user="question", tier="main", max_tokens=1500)


class FakeClient:
    def __init__(self, response):
        self.calls: list[tuple[str, dict]] = []
        self.messages = SimpleNamespace(create=self._make("messages"))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._make("beta")))
        self.response = response

    def _make(self, path):
        def create(**kwargs):
            self.calls.append((path, kwargs))
            return self.response
        return create


def resp(stop="end_turn", blocks=None, category=None):
    blocks = blocks if blocks is not None else [SimpleNamespace(type="text", text='{"answer": "ok"}')]
    return SimpleNamespace(stop_reason=stop, content=blocks, model="m", usage=SimpleNamespace(input_tokens=3, output_tokens=4),
                           stop_details=SimpleNamespace(category=category) if category else None)


@pytest.mark.parametrize("model, path, fallback", [
    ("claude-sonnet-4-5", "messages", False),
    ("claude-haiku-4-5", "messages", False),
    ("claude-haiku-5-5", "messages", False),   # no server-side fallback for Haiku 5.5
    ("claude-sonnet-5-5", "beta", True),
    ("claude-opus-5-5", "beta", True),
])
def test_request_shape_per_model(model, path, fallback):
    fake = FakeClient(resp())
    out = AnthropicProvider("k", client=fake, effort={"main": "medium", "fast": "low"}).complete(REQ, model)
    assert out.text == '{"answer": "ok"}'
    called, kw = fake.calls[0]
    assert called == path
    assert "temperature" not in kw and "top_p" not in kw, "no sampling parameters on any model"
    assert kw["max_tokens"] >= 16_000, "thinking can't starve the answer"
    assert (kw.get("fallbacks") == "default") is fallback and (kw.get("betas") == [SERVER_FALLBACK_BETA]) is fallback
    is_v5 = "-5-" in model
    assert (kw.get("output_config") == {"effort": "medium"}) is is_v5, "effort only where the model accepts it"


def test_no_effort_unless_configured():
    fake = FakeClient(resp())
    AnthropicProvider("k", client=fake, effort={"main": None, "fast": None}).complete(REQ, "claude-sonnet-5-5")
    assert "output_config" not in fake.calls[0][1]


def test_only_text_blocks_are_returned():
    blocks = [SimpleNamespace(type="thinking", thinking="private reasoning", text=None),
              SimpleNamespace(type="fallback"), SimpleNamespace(type="text", text="visible")]
    out = AnthropicProvider("k", client=FakeClient(resp(blocks=blocks))).complete(REQ, "claude-sonnet-5-5")
    assert out.text == "visible"


def test_refusal_is_raised_once_not_retried():
    fake = FakeClient(resp(stop="refusal", blocks=[], category="cyber"))
    gw = Gateway(AnthropicProvider("k", client=fake), "claude-sonnet-5-5", "claude-haiku-5-5", max_retries=2)
    with pytest.raises(ModelRefused, match="cyber"):
        gw.complete(REQ)
    assert len(fake.calls) == 1


def test_truncation_is_an_error_not_half_a_json():
    with pytest.raises(ModelError, match="max_tokens"):
        AnthropicProvider("k", client=FakeClient(resp(stop="max_tokens"))).complete(REQ, "claude-haiku-5-5")


@pytest.mark.parametrize("model", ["claude-sonnet-4-5", "claude-haiku-4-5", "claude-sonnet-5-5", "claude-haiku-5-5"])
def test_installed_sdk_accepts_our_request_shapes(model):
    """Regression: `temperature=` made every real call raise TypeError before reaching the network.
    The real SDK is pointed at a closed port: a TypeError means a bad parameter, a connection error
    means the request shape was accepted."""
    client = anthropic.Anthropic(api_key="sk-test", base_url="http://127.0.0.1:9", max_retries=0, timeout=2)
    provider = AnthropicProvider("k", client=client, effort={"main": "low", "fast": "low"})
    with pytest.raises(anthropic.APIConnectionError):
        provider.complete(REQ, model)
