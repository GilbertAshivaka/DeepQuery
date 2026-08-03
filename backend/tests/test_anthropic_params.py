"""
Deep Query — Unit Tests for Anthropic model parameter selection

Regression tests for the Claude 5 family switch in ``agents.models.slots``:

  - ``_is_anthropic_adaptive`` must classify the new-generation ids without
    misclassifying old ones (the ``-5``-suffix trap).
  - ``_anthropic_params`` must emit the right ``ChatAnthropic`` constructor kwargs per
    model generation × thinking flag, including the Claude 5 requirement that
    ``temperature`` be absent entirely (``None`` → dropped by the wrapper).
"""

from agents.models import slots

# (model id, expected _is_anthropic_adaptive result)
FAMILY_CASES = [
    ("claude-opus-5", True),
    ("claude-sonnet-5", True),
    ("claude-haiku-5", True),
    ("claude-fable-5", True),
    ("claude-mythos-5", True),
    ("claude-haiku-4-5", True),
    ("claude-haiku-4-5-20251001", True),
    # Old generations — the "-5" suffix trap: these must stay on the old path.
    ("claude-sonnet-4-5", False),
    ("claude-opus-4-5", False),
    ("claude-opus-4-1", False),
    ("claude-3-7-sonnet-latest", False),
    ("claude-3-5-haiku-latest", False),
    # Gateway-prefixed ids (Bedrock/Vertex) still carry the family marker, so they are
    # correctly recognized as new-generation.
    ("anthropic.claude-opus-5", True),
    ("anthropic.claude-opus-4-1", False),
    # Ids carrying no known family marker → old path, never switch contracts blindly.
    ("claude-x-1", False),
    ("some-custom-model", False),
]


class TestIsAnthropicAdaptive:
    def test_family_split(self):
        for model, expected in FAMILY_CASES:
            assert slots._is_anthropic_adaptive(model) is expected, (
                f"{model!r} classified wrong"
            )

    def test_case_and_whitespace_insensitive(self):
        assert slots._is_anthropic_adaptive("  CLAUDE-OPUS-5  ") is True
        assert slots._is_anthropic_adaptive("Claude-Opus-4-1") is False

    def test_substring_not_suffix(self):
        # "claude-opus-5" must not match via a bare "-5" scan of old ids.
        assert slots._is_anthropic_adaptive("claude-opus-4-5") is False
        assert slots._is_anthropic_adaptive("claude-sonnet-4-5") is False


class TestAnthropicParams:
    """Constructor-kwargs selection per generation × thinking flag.

    ``max_out`` is the resolved max_tokens ceiling; the budget clamps below it.
    """

    def test_old_off(self):
        p = slots._anthropic_params("claude-3-7-sonnet-latest", 0.2, False, 4096)
        assert p == {"temperature": 0.2}

    def test_old_on_sets_temperature_1_and_enabled_budget(self):
        p = slots._anthropic_params("claude-opus-4-1", 0.2, True, 4096)
        assert p["temperature"] == 1
        assert p["thinking"]["type"] == "enabled"
        assert p["thinking"]["budget_tokens"] < 4096
        assert p["thinking"]["budget_tokens"] >= 1024

    def test_new_off_omits_temperature_and_thinking(self):
        # Claude 5 rejects temperature entirely; None is how it is dropped from the
        # request. No thinking config → the model applies its own default.
        p = slots._anthropic_params("claude-opus-5", 0.2, False, 4096)
        assert p["temperature"] is None
        assert "thinking" not in p
        assert "model_kwargs" not in p

    def test_new_on_adaptive_with_effort(self):
        p = slots._anthropic_params("claude-opus-5", 0.2, True, 4096)
        assert p["temperature"] is None
        assert p["thinking"] == {"type": "adaptive"}
        assert "output_config" in p["model_kwargs"]
        assert p["model_kwargs"]["output_config"]["effort"] in slots.VALID_EFFORTS

    def test_new_haiku_4_5_treated_as_new(self):
        p = slots._anthropic_params("claude-haiku-4-5", 0.0, True, 4096)
        assert p["thinking"] == {"type": "adaptive"}
        assert p["temperature"] is None

    def test_old_ids_never_get_adaptive(self):
        for model in ("claude-opus-4-5", "claude-sonnet-4-5", "claude-3-5-haiku-latest"):
            p = slots._anthropic_params(model, 0.0, True, 4096)
            assert p["thinking"]["type"] == "enabled", model


class TestValidEfforts:
    def test_effort_set(self):
        assert slots.VALID_EFFORTS == ("low", "medium", "high", "xhigh", "max")
        assert slots.DEFAULT_EFFORT in slots.VALID_EFFORTS

    @staticmethod
    def _no_db_flag(monkeypatch):
        """Stub get_flag so it behaves like 'no DB row' — i.e. returns the env default it
        was handed, exercising the env-fallback path in _resolve_effort."""
        import agents.models.config_store as config_store

        monkeypatch.setattr(
            config_store, "get_flag", lambda key, default=None: default
        )

    def test_resolve_effort_falls_back_on_unknown(self, monkeypatch):
        monkeypatch.setattr(slots.settings, "agent_anthropic_thinking_effort", "bogus")
        self._no_db_flag(monkeypatch)
        assert slots._resolve_effort() == slots.DEFAULT_EFFORT

    def test_resolve_effort_honors_valid(self, monkeypatch):
        monkeypatch.setattr(slots.settings, "agent_anthropic_thinking_effort", "high")
        self._no_db_flag(monkeypatch)
        assert slots._resolve_effort() == "high"

    def test_resolve_effort_db_flag_wins(self, monkeypatch):
        monkeypatch.setattr(slots.settings, "agent_anthropic_thinking_effort", "low")

        import agents.models.config_store as config_store

        monkeypatch.setattr(config_store, "get_flag", lambda key, default=None: "max")
        assert slots._resolve_effort() == "max"
