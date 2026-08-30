from pathlib import Path
from kp.core.stage3_prompt import Stage3PromptBuilder


def test_stage3_prompt_builder_with_files(tmp_path: Path):
    p1 = tmp_path / "patchset1" / "parsed_series.json"
    p2 = tmp_path / "patchset2" / "parsed_series.json"
    p1.parent.mkdir(parents=True)
    p2.parent.mkdir(parents=True)
    p1.write_text("{}", encoding="utf-8")
    p2.write_text("{}", encoding="utf-8")

    builder = Stage3PromptBuilder()
    prompt = builder.build_prompt(run_id="20260830_120000_abcdef", parsed_patchsets_paths=[p1, p2])

    assert "20260830_120000_abcdef" in prompt
    assert str(p1.resolve()) in prompt
    assert str(p2.resolve()) in prompt
    # 验证核心分析维度在提示词中
    assert "架构" in prompt or "设计" in prompt
    assert "并发" in prompt or "锁" in prompt or "竞争" in prompt
    assert "内存" in prompt or "资源" in prompt
    assert "回归" in prompt or "风险" in prompt


def test_stage3_prompt_builder_empty_list():
    builder = Stage3PromptBuilder()
    prompt = builder.build_prompt(run_id="20260830_empty_run", parsed_patchsets_paths=[])

    assert "20260830_empty_run" in prompt
    assert "无" in prompt or "未" in prompt or "empty" in prompt.lower()


def test_stage3_prompt_builder_relative_path_resolved(tmp_path: Path):
    p1 = tmp_path / "parsed_series.json"
    p1.write_text("{}", encoding="utf-8")

    builder = Stage3PromptBuilder()
    prompt = builder.build_prompt(run_id="run_rel", parsed_patchsets_paths=[p1])

    assert str(p1.resolve()) in prompt
    assert prompt.startswith("#")
