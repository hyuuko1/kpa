from pathlib import Path


def test_skill_files_exist():
    skill_dir = Path(".agents/skills/kernel-patch-analyzer")
    assert skill_dir.is_dir(), f"Skill directory {skill_dir} does not exist"

    skill_main = skill_dir / "SKILL.md"
    assert skill_main.is_file(), f"{skill_main} does not exist"
    content = skill_main.read_text(encoding="utf-8")
    assert "name: kernel-patch-analyzer" in content
    assert "references/screening.md" in content
    assert "references/deep-analysis.md" in content
    assert "data/reports/" in content

    screening_ref = skill_dir / "references" / "screening.md"
    assert screening_ref.is_file(), f"{screening_ref} does not exist"
    screening_content = screening_ref.read_text(encoding="utf-8")
    assert "reviews.json" in screening_content

    analysis_ref = skill_dir / "references" / "deep-analysis.md"
    assert analysis_ref.is_file(), f"{analysis_ref} does not exist"
    analysis_content = analysis_ref.read_text(encoding="utf-8")
    assert "Architecture & Context" in analysis_content
    assert "Concurrency & Locking" in analysis_content
    assert "Memory & Lifecycle" in analysis_content
    assert "Regressions & Impact" in analysis_content
    assert "Community Discussion & Key Debates" in analysis_content
    assert "https://lore.kernel.org/all/<id>" in analysis_content
