#!/usr/bin/env python3
"""Offline unit tests for src/agent.py: Bundle-Protocol v1 cache-prefix splitter, SSE clients, and chat.json."""

from __future__ import annotations

import io
import json
import os
import urllib.error
from pathlib import Path

try:
    from tests.helpers import ROOT, SCRIPT, RunBlockTestCase
except ImportError:
    from helpers import ROOT, SCRIPT, RunBlockTestCase  # type: ignore[no-redef]


class _FakeSSEResponse:
    """In-memory file-like HTTP SSE response stub for offline urlopen tests."""

    def __init__(self, lines: list[str]) -> None:
        self._raw = [ln.encode("utf-8") for ln in lines]

    def __iter__(self):
        return iter(self._raw)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        pass

    def close(self) -> None:
        pass


def _build_boundary_bundle(
    *,
    nonce: str = "bnd777",
    role: str = "work",
    task: str = "F102",
    title: str = "Test API splitter",
    extra_rule: str = "- Core rule one.\n- Core rule two.",
    agents_md: str = "# Project Rules\n- Keep src/ modular.",
    sub_file: str = "x = 42",
    cmd_out: str = "## main...origin/main",
    prompt: str = "Implement the feature.",
) -> str:
    return (
        "Bundle-Protocol: 1\n"
        f"Bundle-Boundary: {nonce}\n"
        f"Role: {role}\n"
        f"Task: {task}\n"
        f"Title: {title}\n"
        "\n"
        "===== Rules =====\n"
        f'<!-- bundle:{nonce}:part {{"kind":"rule","id":"vitalio/agents-rules:core","chain":[".context.bundle"]}} -->\n'
        f"{extra_rule}\n"
        f"<!-- bundle:{nonce}:end -->\n"
        "\n"
        f'<!-- bundle:{nonce}:part {{"kind":"file","name":"AGENTS.md","chain":[".context.bundle"]}} -->\n'
        "===== $ cat AGENTS.md =====\n"
        f"{agents_md}\n"
        f"<!-- bundle:{nonce}:end -->\n"
        "\n"
        f'<!-- bundle:{nonce}:part {{"kind":"file","name":"sub/AGENTS.md","chain":["subproject"]}} -->\n'
        "===== $ cat sub/AGENTS.md =====\n"
        "# Subproject Rules\n"
        f"<!-- bundle:{nonce}:end -->\n"
        "\n"
        f'<!-- bundle:{nonce}:part {{"kind":"file","name":"src/app.py","chain":[".context.bundle"]}} -->\n'
        "===== $ cat src/app.py =====\n"
        f"{sub_file}\n"
        f"<!-- bundle:{nonce}:end -->\n"
        "\n"
        f'<!-- bundle:{nonce}:part {{"kind":"cmd","name":"git status -sb","rc":0,"ms":4}} -->\n'
        "===== $ git status -sb =====\n"
        f"{cmd_out}\n"
        f"<!-- bundle:{nonce}:end -->\n"
        "\n"
        f'<!-- bundle:{nonce}:part {{"kind":"prompt","name":"Prompt"}} -->\n'
        "===== Prompt =====\n"
        f"{prompt}\n"
        f"<!-- bundle:{nonce}:end -->\n"
    )


class TestAgentProtocolAndClients(RunBlockTestCase):
    def _init_session_from_bundle(self, session_name: str, bundle_input: str) -> Path:
        r = self._run(
            [str(SCRIPT), "--start", "--session", session_name],
            input=bundle_input,
        )
        self._assert_ok(r)
        return self.tmp / session_name

    def test_embedded_api_rule_contract(self) -> None:
        rule_path = ROOT / "agents" / "run-api.md"
        self.assertTrue(rule_path.is_file())
        raw_md = rule_path.read_text(encoding="utf-8")
        self.assertTrue(raw_md.startswith("# Description:"))

        rule_id, rendered = self.mod.get_embedded_api_rule()
        self.assertEqual(rule_id, "vitalio/run-block:run")
        self.assertNotEqual(self.mod.EMBEDDED_RULE_API, "__EMBEDDED_RULE_API__")
        self.assertNotIn("{cmd:run}", rendered)
        self.assertNotIn("# Description:", rendered)

        for forbidden in ("-rc", "--run", "--clipboard", "--bundle-plan", "| run", "| {cmd:run}"):
            with self.subTest(forbidden=forbidden):
                self.assertEqual(raw_md.count(forbidden), 0)

        for required in ("fix_target", "--done", "Workdir", "START", "END", "script"):
            with self.subTest(required=required):
                self.assertGreaterEqual(rendered.count(required), 1)

    def test_bundle_prefix_splitter_lossless_and_cross_session_immutable(self) -> None:
        s1_dir = self._init_session_from_bundle(
            "s1",
            _build_boundary_bundle(
                nonce="n1",
                task="F101",
                title="First task",
                cmd_out="## main",
                prompt="Solve F101.",
            ),
        )
        s2_dir = self._init_session_from_bundle(
            "s2",
            _build_boundary_bundle(
                nonce="n2",
                task="F102",
                title="Second task",
                cmd_out="## main...origin/main\n M src/agent.py",
                prompt="Solve F102.",
            ),
        )

        b1_before = (s1_dir / "0").read_text(encoding="utf-8")
        split1 = self.mod.split_bundle_for_api(s1_dir)
        split2 = self.mod.split_bundle_for_api(s2_dir)
        b1_after = (s1_dir / "0").read_text(encoding="utf-8")

        # <session>/0 on disk must stay untouched with EMBEDDED_RULE_BASH for clipboard fallback
        self.assertEqual(b1_before, b1_after)
        _, bash_rule = self.mod.get_embedded_block_rule()
        self.assertEqual(b1_after.count(bash_rule), 1)
        self.assertTrue(split1["swapped_embedded_rule"])

        # Cross-session system prefix must be byte-identical across sessions for the same repo & role
        self.assertEqual(split1["system"], split2["system"])
        self.assertEqual(split1["system_blocks"], split2["system_blocks"])
        self.assertEqual(len(split1["system_blocks"]), 2)
        self.assertEqual(split1["system_blocks"][0]["kind"], "rule")
        self.assertEqual(split1["system_blocks"][1]["kind"], "agents_md")

        # Per-session headers are excluded from system and placed in user[0]
        for hdr in ("Session: s1", "Next-Block: s1/1", "Workdir:", "Date:", "Role: work", "Task: F101", "Title: First task"):
            with self.subTest(header=hdr):
                self.assertEqual(split1["system"].count(hdr), 0)
                self.assertEqual(split1["user"].count(hdr), 1)

        # System has EMBEDDED_RULE_API once, all rule parts, and root AGENTS.md (not sub/AGENTS.md)
        _, api_rule = self.mod.get_embedded_api_rule()
        self.assertEqual(split1["system"].count(api_rule), 1)
        self.assertEqual(split1["system"].count("<<'RUN_BLOCK'"), 0)
        self.assertEqual(split1["system"].count("===== Rules ====="), 1)
        self.assertEqual(split1["system"].count("- Core rule one."), 1)
        self.assertEqual(split1["system"].count("===== $ cat AGENTS.md ====="), 1)
        self.assertEqual(split1["system"].count("# Project Rules"), 1)
        self.assertEqual(split1["system"].count("sub/AGENTS.md"), 0)

        # User[0] has session headers, non-root files, commands, and prompt
        self.assertIn("Session: s1\nNext-Block: s1/1", split1["user"])
        self.assertIn("===== $ cat sub/AGENTS.md =====\n# Subproject Rules", split1["user"])
        self.assertIn("===== $ cat src/app.py =====\nx = 42", split1["user"])
        self.assertIn("===== $ git status -sb =====\n## main", split1["user"])
        self.assertIn("===== Prompt =====\nSolve F101.", split1["user"])

        # One-time swap persisted in <session>/chat.json
        chat1 = self.mod.init_session_chat(s1_dir)
        self.assertTrue((s1_dir / "chat.json").is_file())
        self.assertEqual(chat1["system"], split1["system"])
        self.assertEqual(chat1["messages"], [{"role": "user", "content": split1["user"]}])

        # Subsequent ensure_session_chat calls return existing chat.json without re-splitting
        (s1_dir / "0").write_text("Session: s1\nNext-Block: s1/1\n\nMutated on disk\n", encoding="utf-8")
        chat1_again = self.mod.ensure_session_chat(s1_dir)
        self.assertEqual(chat1_again["system"], split1["system"])
        self.assertEqual(chat1_again["messages"][0]["content"], split1["user"])

    def test_fallback_sections_bundle_splitter(self) -> None:
        plain_input = (
            "Role: work\nTask: F102\n\n"
            "===== File: AGENTS.md =====\n# Fallback Agents\n\n"
            "===== $ git status -sb =====\n## main\n\n"
            "===== Prompt =====\nFallback prompt\n"
        )
        sdir = self._init_session_from_bundle("s1", plain_input)
        split = self.mod.split_bundle_for_api(sdir)
        self.assertTrue(split["swapped_embedded_rule"])
        self.assertEqual(split["system"].count("<<'RUN_BLOCK'"), 0)
        self.assertIn("# Fallback Agents", split["agents_md_text"])
        self.assertIn("Session: s1", split["user"])
        self.assertIn("Fallback prompt", split["user"])

    def test_run_tool_schema_normalization_and_multi_call_guard(self) -> None:
        anth_tool = self.mod.build_run_tool_schema("anthropic")
        self.assertEqual(anth_tool["name"], "run")
        anth_props = anth_tool["input_schema"]["properties"]
        self.assertEqual(set(anth_props.keys()), {"script", "fix_target"})
        self.assertEqual(anth_tool["input_schema"]["required"], ["script"])
        self.assertFalse(anth_tool["input_schema"]["additionalProperties"])

        oai_tool = self.mod.build_run_tool_schema("openai")
        self.assertEqual(oai_tool["type"], "function")
        oai_params = oai_tool["function"]["parameters"]
        self.assertEqual(set(oai_params["properties"].keys()), {"script", "fix_target"})
        self.assertEqual(oai_params["properties"]["fix_target"]["type"], ["string", "null"])
        for forbidden_field in ("edits", "done", "done_note"):
            self.assertNotIn(forbidden_field, anth_props)
            self.assertNotIn(forbidden_field, oai_params["properties"])

        # fix_target: null / "" / "null" normalized to omitted
        for raw_ft in (None, "", "   ", "null", "NULL"):
            with self.subTest(raw_fix_target=raw_ft):
                norm = self.mod.normalize_run_tool_call({"script": "git status -sb", "fix_target": raw_ft})
                self.assertIsNone(norm["fix_target"])
                self.assertEqual(norm["input"], {"script": "git status -sb\n"})
                self.assertEqual(norm["kind"], "normal")

        # Valid Python --fix patch preserves fix_target
        fix_norm = self.mod.normalize_run_tool_call({
            "script": "old = 'a'\nnew = 'b'\nassert text.count(old) == 1\ntext = text.replace(old, new, 1)\n",
            "fix_target": "s1/1",
        })
        self.assertEqual(fix_norm["fix_target"], "s1/1")
        self.assertEqual(fix_norm["kind"], "fix")
        self.assertEqual(fix_norm["input"]["fix_target"], "s1/1")

        # Accidental heredoc wrapper in script is stripped and flagged
        wrapped_norm = self.mod.normalize_run_tool_call({
            "script": "```bash\nrun s1/1 <<'RUN_BLOCK'\necho hi\nRUN_BLOCK\n```",
        }, session="s1")
        self.assertEqual(wrapped_norm["script"], "echo hi\n")
        self.assertTrue(wrapped_norm["had_wrapper"])

        # Multi-call guard accepts only tool_calls[0] and emits synthetic error tool_results for tool_calls[1:]
        guarded = self.mod.process_assistant_tool_calls([
            {"id": "call_1", "name": "run", "input": {"script": "echo step1", "fix_target": None}},
            {"id": "call_2", "name": "run", "input": {"script": "echo step2"}},
            {"id": "call_3", "name": "run", "arguments": '{"script": "echo step3", "fix_target": ""}'},
        ], session="s1")
        self.assertEqual(guarded["primary_call"]["id"], "call_1")
        self.assertEqual(guarded["primary_call"]["input"], {"script": "echo step1\n"})
        self.assertEqual(len(guarded["rejected_calls"]), 2)
        self.assertEqual(
            guarded["synthetic_tool_results"],
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_2",
                    "content": self.mod.PARALLEL_TOOL_CALL_ERROR,
                    "is_error": True,
                },
                {
                    "type": "tool_result",
                    "tool_use_id": "call_3",
                    "content": self.mod.PARALLEL_TOOL_CALL_ERROR,
                    "is_error": True,
                },
            ],
        )

    def test_anthropic_cache_control_breakpoints_auto_system_off(self) -> None:
        big_rules = "- Rule line with plenty of characters for token threshold.\n" * 90
        big_agents = "# AGENTS.md\n" + ("Project architecture detail line.\n" * 130)
        big_prompt = "Task description line with context.\n" * 130
        sdir = self._init_session_from_bundle(
            "s1",
            _build_boundary_bundle(
                extra_rule=big_rules,
                agents_md=big_agents,
                prompt=big_prompt,
            ),
        )
        profile = {"provider": "anthropic", "model": "claude-sonnet-4-5"}
        chat = self.mod.init_session_chat(sdir, profile=profile)

        # Append two completed step turns with >= 1024-token outputs
        big_out_1 = "[s1/1] START\n" + ("output line from step 1\n" * 200) + "[s1/1] END (10ms)\n"
        big_out_2 = "[s1/2] START\n" + ("output line from step 2\n" * 200) + "[s1/2] END (12ms)\n"
        self.mod.append_assistant_turn(
            sdir,
            {"content": "Run step 1", "tool_calls": [{"id": "t1", "name": "run", "input": {"script": "echo 1"}}]},
            step="1",
        )
        self.mod.append_tool_result_turn(sdir, tool_use_id="t1", content=big_out_1, step="1")
        self.mod.append_assistant_turn(
            sdir,
            {"content": "Run step 2", "tool_calls": [{"id": "t2", "name": "run", "input": {"script": "echo 2"}}]},
            step="2",
        )
        chat = self.mod.append_tool_result_turn(sdir, tool_use_id="t2", content=big_out_2, step="2")

        # 1. auto mode: 4 breakpoints (system[0] rules, system[1] AGENTS.md, user[0], latest user tool_result)
        req_auto = self.mod.build_anthropic_request(chat, profile, cache_mode="auto")
        self.assertEqual(req_auto["tool_choice"], {"type": "auto", "disable_parallel_tool_use": True})
        self.assertEqual(req_auto["system"][0].get("cache_control"), {"type": "ephemeral"})
        self.assertEqual(req_auto["system"][1].get("cache_control"), {"type": "ephemeral"})
        self.assertEqual(req_auto["messages"][0]["content"][-1].get("cache_control"), {"type": "ephemeral"})
        self.assertIsNone(req_auto["messages"][2]["content"][-1].get("cache_control"))
        self.assertEqual(req_auto["messages"][4]["content"][-1].get("cache_control"), {"type": "ephemeral"})

        # 2. system mode: breakpoints only on system blocks, none on messages
        req_sys = self.mod.build_anthropic_request(chat, profile, cache_mode="system")
        self.assertEqual(req_sys["system"][0].get("cache_control"), {"type": "ephemeral"})
        self.assertEqual(req_sys["system"][1].get("cache_control"), {"type": "ephemeral"})
        for msg in req_sys["messages"]:
            for blk in msg["content"]:
                self.assertNotIn("cache_control", blk)

        # 3. off mode: zero breakpoints anywhere
        req_off = self.mod.build_anthropic_request(chat, profile, cache_mode="off")
        for blk in req_off["system"]:
            self.assertNotIn("cache_control", blk)
        for msg in req_off["messages"]:
            for blk in msg["content"]:
                self.assertNotIn("cache_control", blk)

        # 4. Blocks below 1024 tokens never receive cache_control even in auto mode
        small_sdir = self._init_session_from_bundle(
            "s2",
            _build_boundary_bundle(
                extra_rule="- short rule",
                agents_md="# short agents",
                prompt="short prompt",
            ),
        )
        small_chat = self.mod.init_session_chat(small_sdir, profile=profile)
        req_small = self.mod.build_anthropic_request(small_chat, profile, cache_mode="auto")
        self.assertEqual(req_small["system"][0].get("cache_control"), {"type": "ephemeral"})
        self.assertNotIn("cache_control", req_small["system"][1])
        self.assertNotIn("cache_control", req_small["messages"][0]["content"][-1])

    def test_anthropic_sse_client_and_usage_persistence(self) -> None:
        sdir = self._init_session_from_bundle("s1", _build_boundary_bundle())
        step1_dir = sdir / "1"
        step1_dir.mkdir(parents=True, exist_ok=True)
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"
        profile = {"name": "claude-work", "provider": "anthropic", "model": "claude-sonnet-4-5"}

        sse_lines = [
            "event: message_start\n",
            'data: {"type":"message_start","message":{"id":"msg_1","usage":{"input_tokens":450,"output_tokens":1,"cache_read_input_tokens":1200,"cache_creation_input_tokens":300}}}\n',
            "\n",
            "event: content_block_start\n",
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":"","signature":"sig_1"}}\n',
            "\n",
            "event: content_block_delta\n",
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"Checking status."}}\n',
            "\n",
            "event: content_block_start\n",
            'data: {"type":"content_block_start","index":1,"content_block":{"type":"text","text":""}}\n',
            "\n",
            "event: content_block_delta\n",
            'data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"Inspecting repo."}}\n',
            "\n",
            "event: content_block_start\n",
            'data: {"type":"content_block_start","index":2,"content_block":{"type":"tool_use","id":"toolu_01","name":"run","input":{}}}\n',
            "\n",
            "event: content_block_delta\n",
            'data: {"type":"content_block_delta","index":2,"delta":{"type":"input_json_delta","partial_json":"{\\"script\\": \\"git status -sb\\", "}}\n',
            "\n",
            "event: content_block_delta\n",
            'data: {"type":"content_block_delta","index":2,"delta":{"type":"input_json_delta","partial_json":"\\"fix_target\\": null}"}}\n',
            "\n",
            "event: message_delta\n",
            'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":64}}\n',
            "\n",
            "event: message_stop\n",
            'data: {"type":"message_stop"}\n',
            "\n",
        ]

        captured_reqs: list[object] = []
        streamed_text: list[str] = []

        def fake_urlopen(req, timeout=300.0):
            captured_reqs.append((req, timeout))
            return _FakeSSEResponse(sse_lines)

        turn = self.mod.request_model_turn(
            sdir,
            profile=profile,
            step="1",
            on_text=streamed_text.append,
            urlopen=fake_urlopen,
        )

        self.assertEqual(len(captured_reqs), 1)
        sent_req, _ = captured_reqs[0]
        self.assertEqual(sent_req.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(sent_req.headers.get("X-api-key"), "sk-ant-test-key")
        self.assertEqual(sent_req.headers.get("Anthropic-version"), "2023-06-01")
        self.assertEqual(streamed_text, ["Inspecting repo."])
        self.assertEqual(turn["content"], "Inspecting repo.")
        self.assertEqual(turn["thinking"], {"thinking": "Checking status.", "signature": "sig_1"})
        self.assertEqual(turn["primary_call"]["id"], "toolu_01")
        self.assertEqual(turn["primary_call"]["input"], {"script": "git status -sb\n"})
        self.assertIsNone(turn["primary_call"]["fix_target"])

        # Verify usage persisted in chat.json, <step>/meta.json, and <session>/meta.json
        expected_usage = {
            "input_tokens": 450,
            "output_tokens": 64,
            "cache_read_input_tokens": 1200,
            "cache_creation_input_tokens": 300,
            "cached_tokens": 1200,
        }
        chat_disk = self.mod.read_session_chat(sdir)
        step_meta = self.mod.read_step_meta(step1_dir)
        sess_meta = self.mod.read_session_meta(sdir)

        for k, v in expected_usage.items():
            self.assertEqual(turn["usage"][k], v)
            self.assertEqual(chat_disk["messages"][-1]["usage"][k], v)
            self.assertEqual(chat_disk["usage"][k], v)
            self.assertEqual(step_meta["usage"][k], v)
            self.assertEqual(sess_meta["usage"][k], v)
            self.assertEqual(sess_meta["stats"][k], v)
        self.assertTrue(turn["usage"]["response_at"].endswith("Z"))

        # Verify write_step_meta preserves step usage when step executes later
        self.mod.write_step_meta(step1_dir, duration_ms=25, exit_code=0, outcome="ok")
        step_meta_after = self.mod.read_step_meta(step1_dir)
        self.assertEqual(step_meta_after["usage"]["input_tokens"], 450)
        self.assertEqual(step_meta_after["usage"]["cached_tokens"], 1200)

    def test_openai_compatible_sse_client_multi_call_guard_and_providers(self) -> None:
        sdir = self._init_session_from_bundle("s1", _build_boundary_bundle())
        os.environ["DEEPSEEK_API_KEY"] = "sk-ds-test"
        profile = {"name": "ds-work", "provider": "deepseek", "model": "deepseek-chat"}

        sse_lines = [
            'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"role":"assistant","reasoning_content":"First thought.","content":"Running check."}}]}\n\n',
            'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_a","type":"function","function":{"name":"run","arguments":"{\\"script\\":\\"git status -sb\\",\\"fix_target\\":\\"\\"}"}},{"index":1,"id":"call_b","type":"function","function":{"name":"run","arguments":"{\\"script\\":\\"git diff\\"}"}}]}}]}\n\n',
            'data: {"id":"chatcmpl-1","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":2000,"completion_tokens":55,"prompt_cache_hit_tokens":1600}}\n\n',
            "data: [DONE]\n\n",
        ]

        captured_reqs: list[object] = []

        def fake_urlopen(req, timeout=300.0):
            captured_reqs.append(req)
            return _FakeSSEResponse(sse_lines)

        turn = self.mod.request_model_turn(sdir, profile=profile, step="1", urlopen=fake_urlopen)
        self.assertEqual(len(captured_reqs), 1)
        sent_req = captured_reqs[0]
        self.assertEqual(sent_req.full_url, "https://api.deepseek.com/v1/chat/completions")
        self.assertEqual(sent_req.headers.get("Authorization"), "Bearer sk-ds-test")
        sent_body = json.loads(sent_req.data.decode("utf-8"))
        self.assertFalse(sent_body["parallel_tool_calls"])
        self.assertEqual(sent_body["stream_options"], {"include_usage": True})

        # Primary call is call_a; call_b was rejected with synthetic tool_result persisted in chat.json
        self.assertEqual(turn["primary_call"]["id"], "call_a")
        self.assertEqual(turn["primary_call"]["input"], {"script": "git status -sb\n"})
        self.assertEqual(len(turn["rejected_calls"]), 1)
        self.assertEqual(turn["rejected_calls"][0]["id"], "call_b")
        self.assertEqual(turn["usage"]["input_tokens"], 2000)
        self.assertEqual(turn["usage"]["output_tokens"], 55)
        self.assertEqual(turn["usage"]["cached_tokens"], 1600)
        self.assertEqual(turn["usage"]["cache_read_input_tokens"], 1600)

        chat_disk = self.mod.read_session_chat(sdir)
        self.assertEqual(len(chat_disk["messages"]), 3)
        self.assertEqual(chat_disk["messages"][2]["role"], "user")
        self.assertEqual(
            chat_disk["messages"][2]["tool_results"],
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_b",
                    "content": self.mod.PARALLEL_TOOL_CALL_ERROR,
                    "is_error": True,
                }
            ],
        )

        # Appending call_a's result merges into the same user turn so both call_a and call_b are answered
        updated_chat = self.mod.append_tool_result_turn(
            sdir,
            tool_use_id="call_a",
            content="[s1/1] START\n## main\n[s1/1] END (5ms)\n",
            step="1",
        )
        self.assertEqual(len(updated_chat["messages"]), 3)
        self.assertEqual(
            [tr["tool_use_id"] for tr in updated_chat["messages"][2]["tool_results"]],
            ["call_a", "call_b"],
        )

        # Building next OpenAI request expands both tool results into role='tool' messages
        next_oai = self.mod.build_openai_request(updated_chat, profile)
        tool_msgs = [m for m in next_oai["messages"] if m["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in tool_msgs], ["call_a", "call_b"])

        # Verify endpoint resolution across Gemini, OpenRouter, OpenAI, and custom local servers
        self.assertEqual(
            self.mod.resolve_provider_endpoint({"provider": "gemini"}),
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )
        self.assertEqual(
            self.mod.resolve_provider_endpoint({"provider": "openrouter"}),
            "https://openrouter.ai/api/v1/chat/completions",
        )
        self.assertEqual(
            self.mod.resolve_provider_endpoint({"provider": "openai", "base_url": "http://127.0.0.1:8080"}),
            "http://127.0.0.1:8080/v1/chat/completions",
        )

    def test_threshold_context_compaction_preserves_append_only_below_threshold(self) -> None:
        sdir = self._init_session_from_bundle("s1", _build_boundary_bundle())
        self.mod.init_session_chat(sdir)

        out1 = "[s1/1] START\n" + ("step 1 verbose log line\n" * 120) + "[s1/1] END (15ms)\n"
        out2 = "[s1/2] START\n" + ("step 2 verbose log line\n" * 120) + "[s1/2] END (18ms)\n"
        out3 = "[s1/3] START\n" + ("step 3 latest log line\n" * 120) + "[s1/3] END (20ms)\n"

        # With default threshold (120000), history stays strictly append-only without mutating old outputs
        for idx, out_text in enumerate((out1, out2, out3), 1):
            self.mod.append_assistant_turn(
                sdir,
                {
                    "content": f"Step {idx}",
                    "tool_calls": [{"id": f"c{idx}", "name": "run", "input": {"script": f"echo {idx}"}}],
                    "usage": {"input_tokens": 2000 * idx, "output_tokens": 30},
                },
                step=str(idx),
            )
            self.mod.append_tool_result_turn(sdir, tool_use_id=f"c{idx}", content=out_text, step=str(idx))

        chat_before = self.mod.read_session_chat(sdir)
        self.assertEqual(chat_before["messages"][2]["tool_results"][0]["content"], out1)
        self.assertEqual(chat_before["messages"][4]["tool_results"][0]["content"], out2)
        self.assertEqual(chat_before["messages"][6]["tool_results"][0]["content"], out3)

        # Lower RUN_BLOCK_COMPACT_TOKENS threshold so batch compaction triggers
        os.environ["RUN_BLOCK_COMPACT_TOKENS"] = "1500"
        compacted = self.mod.compact_chat_history(chat_before)
        self.assertTrue(compacted)
        self.assertEqual(chat_before.get("compactions"), 1)

        # Older tool_results (steps 1 and 2) are compacted in one batch, keeping START/END markers;
        # system, user[0], and the latest tool_result (step 3) remain untouched.
        tr1 = chat_before["messages"][2]["tool_results"][0]
        tr2 = chat_before["messages"][4]["tool_results"][0]
        tr3 = chat_before["messages"][6]["tool_results"][0]
        self.assertTrue(tr1.get("compacted"))
        self.assertTrue(tr2.get("compacted"))
        self.assertFalse(tr3.get("compacted"))
        self.assertTrue(tr1["content"].startswith("[s1/1] START\n"))
        self.assertIn("compacted", tr1["content"])
        self.assertTrue(tr1["content"].strip().endswith("[s1/1] END (15ms)"))
        self.assertEqual(tr3["content"], out3)

    def test_http_error_wrapped_in_agent_api_error(self) -> None:
        sdir = self._init_session_from_bundle("s1", _build_boundary_bundle())
        chat = self.mod.init_session_chat(sdir)
        profile = {"provider": "anthropic", "model": "claude-sonnet-4-5"}

        def failing_urlopen(req, timeout=300.0):
            err_fp = io.BytesIO(b'{"error":{"message":"invalid x-api-key"}}')
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, err_fp)

        with self.assertRaises(self.mod.AgentAPIError) as ctx:
            self.mod.stream_anthropic_messages(chat, profile, api_key="bad", urlopen=failing_urlopen)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.provider, "anthropic")
        self.assertIn("invalid x-api-key", str(ctx.exception))


if __name__ == "__main__":
    import unittest
    unittest.main()
