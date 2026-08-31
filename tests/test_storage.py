from pathlib import Path
import json
import re
import pytest
from kp.config import StorageConfig
from kp.storage.session import SessionManager
from kp.models import (
    RunManifest,
    RawMessage,
    Patchset,
    PatchReview,
    ParsedPatchset,
    ParsedPatch,
    ParsedComment,
    ParsedCoverLetter,
)


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


def test_session_manager_get_run_dir(tmp_path: Path):
    config = StorageConfig(data_dir=str(tmp_path))
    mgr = SessionManager(config)
    run_dir = mgr.get_run_dir("20260830_120000_123456")
    assert run_dir == tmp_path / "20260830_120000_123456"


def test_session_manager_load_patchsets(tmp_path: Path):
    config = StorageConfig(data_dir=str(tmp_path))
    mgr = SessionManager(config)
    run_dir = tmp_path / "test_run"
    run_dir.mkdir(parents=True)

    patchsets_data = [
        {
            "id": "patch1@kernel.org",
            "title": "[PATCH] mm: fix bug",
            "author_name": "Alice",
            "author_email": "alice@kernel.org",
            "patches": ["[PATCH] mm: fix bug"],
        }
    ]
    (run_dir / "patchsets.json").write_text(
        json.dumps(patchsets_data), encoding="utf-8"
    )

    loaded = mgr.load_patchsets(run_dir)
    assert len(loaded) == 1
    assert loaded[0].id == "patch1@kernel.org"
    assert loaded[0].title == "[PATCH] mm: fix bug"
    assert loaded[0].author_name == "Alice"


def test_session_manager_load_patchsets_not_found(tmp_path: Path):
    config = StorageConfig(data_dir=str(tmp_path))
    mgr = SessionManager(config)
    empty_dir = tmp_path / "empty_run"
    empty_dir.mkdir(parents=True)

    with pytest.raises(FileNotFoundError):
        mgr.load_patchsets(empty_dir)


def test_session_manager_save_reviews(tmp_path: Path):
    config = StorageConfig(data_dir=str(tmp_path))
    mgr = SessionManager(config)
    run_dir = tmp_path / "run_rev"
    run_dir.mkdir(parents=True)

    reviews = [
        PatchReview(
            id="msg1", title="title1", score=90, recommend=True, reason="Great patch"
        ),
        PatchReview(
            id="msg2", title="title2", score=50, recommend=False, reason="Minor tweak"
        ),
    ]
    filtered_patchsets = [
        Patchset(
            id="msg1",
            title="title1",
            author_name="Alice",
            author_email="a@b.c",
            patches=["[PATCH] title1"],
        )
    ]

    mgr.save_reviews(run_dir, reviews, filtered_patchsets)

    reviews_file = run_dir / "reviews.json"
    filtered_file = run_dir / "filtered_patchsets.json"

    assert reviews_file.exists()
    assert filtered_file.exists()

    loaded_reviews = json.loads(reviews_file.read_text(encoding="utf-8"))
    assert len(loaded_reviews) == 2
    assert loaded_reviews[0]["score"] == 90

    loaded_filtered = json.loads(filtered_file.read_text(encoding="utf-8"))
    assert len(loaded_filtered) == 1
    assert loaded_filtered[0]["id"] == "msg1"


def test_session_manager_save_parsed_patchset(tmp_path: Path):
    config = StorageConfig(data_dir=str(tmp_path))
    mgr = SessionManager(config)
    run_dir = tmp_path / "run_parsed"
    run_dir.mkdir(parents=True)

    c1 = ParsedComment(
        author="Reviewer <rev@kernel.org>",
        message_id="c1",
        body="Nice fix, but check locking.",
    )

    parsed = ParsedPatchset(
        id="patch1@domain.org",
        title="[PATCH] fix memory leak",
        total_patches=1,
        cover_letter=ParsedCoverLetter(
            subject="[PATCH 0/1] fix memory leak",
            author="Bob <bob@kernel.org>",
            message_id="cover1",
            body="Cover letter description.",
            diffstat="drv.c | 2 +-\n 1 file changed",
        ),
        patches=[
            ParsedPatch(
                index=1,
                total=1,
                subject="[PATCH] fix memory leak",
                author="Bob <bob@kernel.org>",
                message_id="patch1@domain.org",
                commit_message="Fix memory leak in driver",
                trailers=["Signed-off-by: Bob <bob@kernel.org>"],
                diff="--- a/drv.c\n+++ b/drv.c",
                comments=[c1],
            )
        ],
    )

    saved_path = mgr.save_parsed_patchset(run_dir, "patch1_domain_org", parsed)

    expected_path = run_dir / "patchsets" / "patch1_domain_org" / "parsed_series.json"
    assert saved_path == expected_path
    assert expected_path.exists()

    content = json.loads(expected_path.read_text(encoding="utf-8"))
    assert content["id"] == "patch1@domain.org"
    assert len(content["patches"]) == 1
    assert content["patches"][0]["author"] == "Bob <bob@kernel.org>"

    # 验证 AI 直读友好型文件
    meta_file = run_dir / "patchsets" / "patch1_domain_org" / "meta.json"
    cover_file = run_dir / "patchsets" / "patch1_domain_org" / "00-cover-letter.md"
    disc_file = run_dir / "patchsets" / "patch1_domain_org" / "discussions.md"
    patches_dir = run_dir / "patchsets" / "patch1_domain_org" / "patches"

    assert meta_file.exists()
    assert cover_file.exists()
    assert disc_file.exists()
    assert patches_dir.exists()

    patch_files = list(patches_dir.glob("*.patch"))
    assert len(patch_files) == 1
    assert "0001" in patch_files[0].name


def test_session_manager_save_stage3_prompt(tmp_path: Path):
    config = StorageConfig(data_dir=str(tmp_path))
    mgr = SessionManager(config)
    run_dir = tmp_path / "run_prompt3"
    run_dir.mkdir(parents=True)

    prompt_text = "# Stage 3 Deep Analysis\n\nPlease analyze the patches."
    saved_path = mgr.save_stage3_prompt(run_dir, prompt_text)

    expected_path = run_dir / "stage3_prompt.md"
    assert saved_path == expected_path
    assert expected_path.exists()
    assert expected_path.read_text(encoding="utf-8") == prompt_text


def test_session_manager_reports_helpers(tmp_path: Path):
    sm = SessionManager(tmp_path)
    run_id = "test-run-123"
    sm.create_session(run_id)

    reports_dir = sm.get_reports_dir(run_id)
    assert reports_dir.is_dir()
    assert reports_dir == tmp_path / run_id / "reports"

    report_path = sm.get_report_path(run_id, "patchset_1_msgid")
    assert report_path == tmp_path / run_id / "reports" / "patchset_1_msgid.md"

    assert sm.list_reports(run_id) == []
    report_path.write_text("# Report", encoding="utf-8")
    assert sm.list_reports(run_id) == [report_path]


def test_session_manager_get_downloaded_patchset_dirs(tmp_path: Path):
    sm = SessionManager(tmp_path)
    run_id = "test-run-456"
    sm.create_session(run_id)

    assert sm.get_downloaded_patchset_dirs(run_id) == []

    p1_dir = tmp_path / run_id / "patchsets" / "msg_1"
    p1_dir.mkdir(parents=True)
    (p1_dir / "meta.json").write_text("{}", encoding="utf-8")

    dirs = sm.get_downloaded_patchset_dirs(run_id)
    assert len(dirs) == 1
    assert dirs[0] == p1_dir
