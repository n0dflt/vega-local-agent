import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.terminal_tools import (
    get_allowed_command,
    list_allowed_commands,
    run_allowed_command,
)


class TerminalToolsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def write_policy(self, commands=None, max_output_chars=50000):
        policy = {
            "schema_version": 1,
            "default_timeout_seconds": 10,
            "max_output_chars": max_output_chars,
            "commands": commands if commands is not None else [self.command("sample", "sample.py")],
        }
        (self.root / "config" / "allowed_commands.json").write_text(
            json.dumps(policy), encoding="utf-8"
        )
        return policy

    @staticmethod
    def command(command_id, script, timeout=10, executable="python"):
        return {
            "id": command_id,
            "description": f"Run {command_id}.",
            "argv": [executable, script],
            "timeout_seconds": timeout,
            "enabled": True,
        }

    def run_script(self, command_id, source, timeout=10, max_output_chars=50000):
        script = f"{command_id}.py"
        self.write_policy([self.command(command_id, script, timeout)], max_output_chars)
        (self.root / script).write_text(source, encoding="utf-8")
        return run_allowed_command(command_id, self.root)

    def test_valid_policy_loads(self):
        self.write_policy()
        result = list_allowed_commands(self.root)
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(result["data"][0]["id"], "sample")

    def test_missing_policy_is_controlled(self):
        result = list_allowed_commands(self.root)
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"])

    def test_corrupt_json_is_rejected(self):
        (self.root / "config" / "allowed_commands.json").write_text("{", encoding="utf-8")
        result = list_allowed_commands(self.root)
        self.assertFalse(result["ok"])
        self.assertIn("invalid", result["error"])

    def test_unknown_command_id_is_rejected(self):
        self.write_policy()
        result = get_allowed_command("unknown", self.root)
        self.assertFalse(result["ok"])
        self.assertIn("Unknown command id", result["error"])

    def test_dangerous_executable_is_rejected(self):
        self.write_policy([self.command("dangerous", "script.ps1", executable="powershell")])
        result = list_allowed_commands(self.root)
        self.assertFalse(result["ok"])
        self.assertIn("not allowed", result["error"])

    def test_parent_path_escape_is_rejected(self):
        self.write_policy([self.command("escape", "../escape.py")])
        result = list_allowed_commands(self.root)
        self.assertFalse(result["ok"])
        self.assertIn("escapes", result["error"])

    def test_absolute_path_is_rejected(self):
        outside = Path(tempfile.gettempdir()) / "outside.py"
        self.write_policy([self.command("absolute", str(outside))])
        result = list_allowed_commands(self.root)
        self.assertFalse(result["ok"])
        self.assertIn("project-relative", result["error"])

    def test_symlink_escape_is_rejected_when_supported(self):
        outside = Path(self.temporary.name).parent / "vega-terminal-outside.py"
        outside.write_text("print('outside')", encoding="utf-8")
        link = self.root / "linked.py"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            outside.unlink(missing_ok=True)
            self.skipTest(f"symlinks unavailable: {exc}")
        try:
            self.write_policy([self.command("linked", "linked.py")])
            result = list_allowed_commands(self.root)
            self.assertFalse(result["ok"])
            self.assertIn("escapes", result["error"])
        finally:
            outside.unlink(missing_ok=True)

    def test_successful_execution(self):
        result = self.run_script("success", "print('terminal tool test')")
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(result["reason_code"], "")
        self.assertEqual(result["data"]["returncode"], 0)
        self.assertIn("terminal tool test", result["data"]["stdout"])
        self.assertEqual(result["data"]["diagnostics"]["cwd"], str(self.root.resolve()))
        self.assertEqual(
            result["data"]["diagnostics"]["resolved_executable"],
            sys.executable,
        )

    def test_nonzero_exit_preserves_output(self):
        result = self.run_script(
            "failure",
            "import sys\nprint('failure output')\nprint('failure error', file=sys.stderr)\nraise SystemExit(3)",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason_code"], "command_failed")
        self.assertEqual(result["data"]["returncode"], 3)
        self.assertIn("failure output", result["data"]["stdout"])
        self.assertIn("failure error", result["data"]["stderr"])

    def test_timeout_is_reported(self):
        result = self.run_script("timeout", "import time\ntime.sleep(2)", timeout=1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason_code"], "timeout")
        self.assertTrue(result["data"]["timed_out"])
        self.assertEqual(result["data"]["returncode"], -1)
        self.assertIn("timed out", result["data"]["stderr"])

    def test_stdout_is_bounded(self):
        result = self.run_script("stdout", "print('x' * 1000)", max_output_chars=40)
        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["truncated"])
        self.assertIn("[output truncated]", result["data"]["stdout"])

    def test_stderr_is_bounded(self):
        result = self.run_script(
            "stderr", "import sys\nprint('x' * 1000, file=sys.stderr)", max_output_chars=40
        )
        self.assertTrue(result["data"]["truncated"])
        self.assertIn("[output truncated]", result["data"]["stderr"])

    def test_runtime_unavailable_has_specific_reason(self):
        self.write_policy([self.command("missing", "missing.py")])
        with patch(
            "tools.terminal_tools.subprocess.run",
            side_effect=FileNotFoundError("runtime missing"),
        ):
            result = run_allowed_command("missing", self.root)

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason_code"], "runtime_unavailable")
        self.assertIsNone(result["data"])
        self.assertEqual(
            result["diagnostics"]["resolved_executable"],
            sys.executable,
        )

    def test_managed_run_path_is_unique_and_cleaned(self):
        command = self.command("managed", "managed.py")
        command["argv"].append(".tmp/pytest-release-{run_id}")
        self.write_policy([command])
        (self.root / "managed.py").write_text(
            "import pathlib, stat, sys\n"
            "path = pathlib.Path(sys.argv[1])\n"
            "path.mkdir(parents=True)\n"
            "readonly = path / 'readonly.txt'\n"
            "readonly.write_text('managed', encoding='utf-8')\n"
            "readonly.chmod(stat.S_IREAD)\n"
            "print(path)\n",
            encoding="utf-8",
        )

        result = run_allowed_command("managed", self.root)

        self.assertTrue(result["ok"], result["error"])
        expanded = result["data"]["argv"][-1]
        self.assertNotIn("{run_id}", expanded)
        self.assertRegex(expanded, r"^\.tmp/pytest-release-[0-9a-f]{32}$")
        self.assertFalse((self.root / expanded).exists())

    def test_audit_excludes_output_and_environment(self):
        result = self.run_script("audit", "print('secret output')")
        self.assertTrue(result["ok"])
        audit_path = self.root / "logs" / "terminal" / "terminal_commands.jsonl"
        record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertNotIn("stdout", record)
        self.assertNotIn("stderr", record)
        self.assertNotIn("environment", record)
        self.assertNotIn("secret output", json.dumps(record))
        self.assertEqual(record["command_id"], "audit")
        self.assertIn("stdout_summary", record)
        self.assertEqual(record["reason_code"], "")

    def test_subprocess_security_options_and_environment(self):
        self.write_policy([self.command("secure", "secure.py")])
        (self.root / "secure.py").write_text("print('ok')", encoding="utf-8")
        completed = type("Completed", (), {"stdout": "ok", "stderr": "", "returncode": 0})()
        with patch.dict(os.environ, {
            "PYTHONSTARTUP": "bad", "PYTHONINSPECT": "1", "PYTHONPATH": "bad", "PYTHONHOME": "bad"
        }), patch("tools.terminal_tools.subprocess.run", return_value=completed) as mocked:
            result = run_allowed_command("secure", self.root)
        self.assertTrue(result["ok"])
        kwargs = mocked.call_args.kwargs
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["cwd"], self.root.resolve())
        self.assertEqual(mocked.call_args.args[0][0], sys.executable)
        for name in ("PYTHONSTARTUP", "PYTHONINSPECT", "PYTHONPATH", "PYTHONHOME"):
            self.assertNotIn(name, kwargs["env"])
        self.assertEqual(kwargs["env"]["PYTHONNOUSERSITE"], "1")


if __name__ == "__main__":
    unittest.main()
