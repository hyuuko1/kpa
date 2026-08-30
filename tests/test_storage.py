from pathlib import Path
import json
import re
from kp.config import StorageConfig
from kp.storage.session import SessionManager
from kp.models import RunManifest, RawMessage, Patchset


def test_session_manager_create_session_dir(tmp_path: Path):
    config = StorageConfig(data_dir=str(tmp_path))
    mgr = SessionManager(config)
    run_id, run_dir = mgr.create_session_dir()

    assert run_dir.exists()
    assert run_dir.is_dir()
    assert run_dir.parent == tmp_path
    assert re.match(r"^\d{8}_\d{6}_[0-9a-f]{6}$", run_id)
    assert run_dir.name == run_id


def test_session_manager_save_and_structure(tmp_path: Path):
    config = StorageConfig(data_dir=str(tmp_path))
    mgr = SessionManager(config)
    run_id, run_dir = mgr.create_session_dir()

    manifest = RunManifest(
        run_id=run_id,
        timestamp="2026-08-30T10:00:00Z",
        query="l:linux-mm",
        total_raw_messages=1,
        total_patchsets=1,
    )
    raw_msgs = [
        RawMessage(
            m="m1@kernel.org",
            s="[PATCH 1/1] mm: test patch with 中文",
            f=[["Author Name (作者)", "a@b.com"]],
        )
    ]
    patchsets = [
        Patchset(
            id="m1@kernel.org",
            title="[PATCH 1/1] mm: test patch with 中文",
            author_name="Author Name (作者)",
            author_email="a@b.com",
            patches=["[PATCH 1/1] mm: test patch with 中文"],
        )
    ]
    prompt_content = "# Test Prompt with 中文内容\n\n- item 1"

    mgr.save_run(run_dir, manifest, raw_msgs, patchsets, prompt_content)


    manifest_file = run_dir / "manifest.json"
    raw_file = run_dir / "raw_metadata.json"
    patchsets_file = run_dir / "patchsets.json"
    prompt_file = run_dir / "prompt.md"

    assert manifest_file.exists()
    assert raw_file.exists()
    assert patchsets_file.exists()
    assert prompt_file.exists()

    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)
        assert manifest_data["run_id"] == run_id
        assert manifest_data["total_patchsets"] == 1

    with open(raw_file, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
        assert len(raw_data) == 1
        assert raw_data[0]["m"] == "m1@kernel.org"
        assert "中文" in raw_data[0]["s"]

    with open(patchsets_file, "r", encoding="utf-8") as f:
        patchsets_data = json.load(f)
        assert len(patchsets_data) == 1
        assert patchsets_data[0]["id"] == "m1@kernel.org"
        assert patchsets_data[0]["author_name"] == "Author Name (作者)"
        assert len(patchsets_data[0]["patches"]) == 1

    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt_read = f.read()
        assert prompt_read == prompt_content
