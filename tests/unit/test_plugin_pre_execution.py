"""Tests for pre-execution safety plugins and registry hooks."""

import pytest

from kerno import HardGuardrailPlugin, SecretRedactionPlugin, powerful_pack
from kerno.plugins.pack.safety import BlockedExecution
from kerno.plugins.registry import BasePlugin, PluginRegistry


def test_hard_guardrail_blocks_shell_and_eval():
    plugin = HardGuardrailPlugin()
    with pytest.raises(BlockedExecution):
        plugin.on_before_cell("import os\nos.system('rm -rf /')")
    with pytest.raises(BlockedExecution):
        plugin.on_before_cell("eval('2 + 2')")


def test_hard_guardrail_allows_analysis_code():
    plugin = HardGuardrailPlugin()
    assert plugin.on_before_cell("df = pd.read_csv('x.csv')\ndf.groupby('a').sum()") is None


def test_secret_redaction_rewrites_literals():
    plugin = SecretRedactionPlugin()
    code = "headers = {'Authorization': 'sk-abcdefghijklmnopqrstuvwxyz1234567890'}"
    redacted = plugin.on_before_cell(code)
    assert "sk-abc" not in redacted
    assert "REDACTED" in redacted
    assert plugin.redactions == 1


def test_registry_chains_on_before_cell():
    class Append(BasePlugin):
        name = "append"
        def on_before_cell(self, code):
            return code + "\nprint('hooked')"

    reg = PluginRegistry().register(Append())
    result = reg.on_before_cell("x = 1")
    assert result.endswith("print('hooked')")


def test_powerful_pack_redacts_secrets_by_default():
    pack = powerful_pack()
    result = pack.on_before_cell("api_key = 'abcdefghijklmnopqrstuvwxyz123456'")
    assert "abcdefghij" not in result
    assert "REDACTED" in result


def test_powerful_pack_hard_guardrails_when_enabled():
    pack = powerful_pack(hard_guardrails=True)
    with pytest.raises(BlockedExecution):
        pack.on_before_cell("import subprocess\nsubprocess.run(['ls'])")
