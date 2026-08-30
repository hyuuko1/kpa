from pathlib import Path
from kp.core.prompt import PromptBuilder


def test_prompt_builder_contains_absolute_path(tmp_path: Path):
    builder = PromptBuilder()
    fake_path = tmp_path / "patchsets.json"
    fake_path.touch()
    prompt = builder.build_prompt(fake_path)
    assert str(fake_path.resolve()) in prompt
    assert "Linux 内核补丁评审" in prompt
    assert "期望输出格式" in prompt
    assert "```json" in prompt


def test_prompt_builder_relative_path_resolved():
    builder = PromptBuilder()
    rel_path = Path("data/runs/run1/patchsets.json")
    prompt = builder.build_prompt(rel_path)
    assert str(rel_path.resolve()) in prompt
    assert str(rel_path.resolve()).startswith("/")
