"""Only AI models that keep nothing (#584): OpenRouter's endpoint list, once a day, offline-safe."""

import json

import pytest
from nicegui.testing import User, user_simulation

from yaptracker import ai_models, config, runtime
from yaptracker.ai_models import BUILT_IN, Models, keeps_nothing
from yaptracker.ai_translate import DEFAULT_MODEL
from yaptracker.ui import shell

CHAT = ["max_tokens", "temperature"]


def endpoint(model, tag, retention=False, params=CHAT, prompt="0.0000001", out="0.0000005"):
    return {"model_id": model, "model_name": model.title(), "tag": tag,
            "safety_retention": retention, "supported_parameters": params,
            "pricing": {"prompt": prompt, "completion": out}}  # fmt: skip


LIST = {"data": [
    endpoint(DEFAULT_MODEL, "amazon-bedrock"),
    endpoint(DEFAULT_MODEL, "google-vertex"),  # clean, but the request skips Vertex
    endpoint("google/gemini-3.1-flash-lite", "google-vertex", retention=True),
    endpoint("google/gemini-3.1-flash-lite", "google-vertex/global", retention=True),
    endpoint("openai/gpt-oss-120b", "google-vertex", retention=True),
    endpoint("openai/gpt-oss-120b", "deepinfra", prompt="0.00000004", out="0.0000002"),
    endpoint("openai/gpt-oss-120b", "groq", prompt="0.00000015"),
    endpoint("google/gemini-embedding-2", "openai", params=[]),  # no chat
    endpoint("odd/model", "x", retention=None),  # the list doesn't say: left out
]}  # fmt: skip


def test_only_chat_models_with_an_endpoint_that_keeps_nothing_and_isnt_vertex():
    found = keeps_nothing(LIST["data"])
    assert list(found) == [DEFAULT_MODEL, "openai/gpt-oss-120b"]
    assert found["openai/gpt-oss-120b"].endswith("$0.04 / $0.20 per million tokens in / out.")


def test_fetched_once_a_day_and_the_evals_words_win(tmp_path):
    now, calls = [1000.0], []
    models = Models(tmp_path / "ai_models.json", fetch=lambda: calls.append(1) or LIST,
                    clock=lambda: now[0])  # fmt: skip
    assert models.hints() == BUILT_IN and not models.checked()  # before the first fetch
    assert models.problem("google/gemini-3.1-flash-lite") is None  # can't tell yet
    assert models.refresh(allowed=False) is False and calls == []  # AI off / no key / a match
    assert models.refresh(allowed=True) is True and calls == [1]
    assert models.hints()[DEFAULT_MODEL] == BUILT_IN[DEFAULT_MODEL]
    assert "Gemini" not in json.dumps(models.hints())
    assert "No provider that keeps nothing" in models.problem("google/gemini-3.1-flash-lite")
    assert models.problem(DEFAULT_MODEL) is None
    now[0] += 3600
    assert models.refresh(allowed=True) is False and calls == [1]  # a day at most
    now[0] += 86400
    assert models.refresh(allowed=True) is True and calls == [1, 1]


def test_offline_or_an_empty_answer_keeps_what_was_there(tmp_path):
    def offline():
        raise OSError("offline")

    path = tmp_path / "ai_models.json"
    assert Models(path, fetch=offline).refresh(True) is False
    assert Models(path).hints() == BUILT_IN  # conftest: no network in tests
    Models(path, fetch=lambda: LIST, clock=lambda: 0.0).refresh(True)
    assert Models(path, fetch=lambda: {"data": []}, clock=lambda: 1e9).refresh(True) is False
    assert "openai/gpt-oss-120b" in Models(path).hints()


@pytest.fixture
async def user():
    async with user_simulation(root=shell.root) as user:
        yield user


async def test_settings_lists_checked_models_and_explains_one_that_keeps_prompts(
    user: User, monkeypatch
):
    monkeypatch.setattr(ai_models, "fetch_list", lambda: LIST)
    config.save_setup_state("done")
    config.save_translate_engine("ai")
    config.save_openrouter_key("sk-or-test")
    config.save_ai_model("google/gemini-3.1-flash-lite")  # saved before #583
    monkeypatch.setattr(runtime, "matches", None)
    await user.open("/")
    user.find(marker="nav-settings").click()
    await user.should_see(
        "No provider that keeps nothing offers google/gemini-3.1-flash-lite", retries=50
    )  # the list comes in the background
    assert config.ai_model() == "google/gemini-3.1-flash-lite"  # explained, never overwritten
    (select,) = user.find(marker="ai-model").elements
    assert DEFAULT_MODEL in select.options and "openai/gpt-oss-120b" in select.options
    select.set_value(DEFAULT_MODEL)
    assert config.ai_model() == DEFAULT_MODEL
    await user.should_see(BUILT_IN[DEFAULT_MODEL])


def test_the_list_is_only_asked_for_with_ai_on_a_key_and_no_match(monkeypatch):
    from types import SimpleNamespace

    from yaptracker.ui.ai_settings import may_check

    monkeypatch.setattr(runtime, "matches", None)
    assert not may_check()  # DeepL, the default
    config.save_translate_engine("ai")
    assert not may_check()  # no key
    config.save_openrouter_key("sk-or-test")
    assert may_check()
    monkeypatch.setattr(runtime, "matches", SimpleNamespace(running=True))
    assert not may_check()  # never during a match
