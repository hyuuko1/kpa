from kp.models import (
    RawMessage,
    Patchset,
    RunManifest,
    PatchReview,
    ParsedComment,
    ParsedCoverLetter,
    ParsedPatch,
    ParsedPatchset,
)


def test_raw_message_parsing():
    raw_dict = {
        "m": "test@msgid.1",
        "s": "[PATCH 1/2] mm: sample fix",
        "f": [["John Doe", "john@example.com"]],
        "refs": ["root@msgid.0"],
        "dt": "2026-08-30T10:00:00Z",
    }
    msg = RawMessage.model_validate(raw_dict)
    assert msg.m == "test@msgid.1"
    assert msg.s == "[PATCH 1/2] mm: sample fix"
    assert msg.f[0][0] == "John Doe"
    assert msg.f[0][1] == "john@example.com"
    assert msg.refs == ["root@msgid.0"]
    assert msg.dt == "2026-08-30T10:00:00Z"
    assert msg.blob is None
    assert msg.t is None
    assert msg.c is None
    assert msg.rt is None


def test_raw_message_optional_fields():
    raw_dict = {
        "blob": "abcdef123456",
        "m": "test2@msgid",
        "s": "[PATCH] standalone",
        "f": [[None, "author@example.com"]],
        "t": [["Recipient", "to@example.com"]],
        "c": [["Reviewer", "cc@example.com"]],
        "rt": "2026-08-30T10:05:00Z",
    }
    msg = RawMessage.model_validate(raw_dict)
    assert msg.blob == "abcdef123456"
    assert msg.m == "test2@msgid"
    assert msg.f == [[None, "author@example.com"]]
    assert msg.t == [["Recipient", "to@example.com"]]
    assert msg.c == [["Reviewer", "cc@example.com"]]
    assert msg.refs == []


def test_patchset_structure():
    patchset = Patchset(
        id="cover@msgid",
        title="[PATCH 0/2] mm: sample series",
        author_name="John Doe",
        author_email="john@example.com",
        date="2026-08-30T10:00:00Z",
        patches=[
            "[PATCH 1/2] mm: sample fix 1",
            "[PATCH 2/2] mm: sample fix 2",
        ],
    )
    assert patchset.id == "cover@msgid"
    assert patchset.title == "[PATCH 0/2] mm: sample series"
    assert patchset.author_name == "John Doe"
    assert patchset.author_email == "john@example.com"
    assert len(patchset.patches) == 2
    assert patchset.patches[0] == "[PATCH 1/2] mm: sample fix 1"


def test_patchset_defaults():
    patchset = Patchset(
        id="patch1@msgid",
        title="[PATCH] single fix",
        author_name="Jane Doe",
        author_email="jane@example.com",
    )
    assert patchset.patches == []
    assert patchset.date is None


def test_run_manifest():
    manifest = RunManifest(
        run_id="20260830_175000_3a8f1b",
        timestamp="2026-08-30T17:50:00Z",
        query="l:linux-mm.kvack.org AND d:15.minutes.ago..",
        total_raw_messages=5,
        total_patchsets=2,
    )
    assert manifest.run_id == "20260830_175000_3a8f1b"
    assert manifest.timestamp == "2026-08-30T17:50:00Z"
    assert manifest.query == "l:linux-mm.kvack.org AND d:15.minutes.ago.."
    assert manifest.total_raw_messages == 5
    assert manifest.total_patchsets == 2

    # Check serialization
    dumped = manifest.model_dump()
    assert dumped["total_raw_messages"] == 5
    restored = RunManifest.model_validate(dumped)
    assert restored == manifest


def test_patch_review_model():
    review = PatchReview(id="msg123", score=85, recommend=True, reason="Important fix")
    assert review.id == "msg123"
    assert review.title is None
    assert review.score == 85
    assert review.recommend is True
    assert review.reason == "Important fix"

    review_with_title = PatchReview(
        id="msg456", title="[PATCH] Fix mm", score=90, recommend=True, reason="Critical"
    )
    assert review_with_title.title == "[PATCH] Fix mm"


def test_parsed_comment_tree_model():
    child = ParsedComment(
        author="Reviewer <rev@kernel.org>",
        message_id="msg2",
        in_reply_to="msg1",
        body="Looks good, thanks.",
    )
    parent = ParsedComment(
        author="Author <auth@kernel.org>",
        message_id="msg1",
        body="Please review this patch.",
        replies=[child],
    )
    assert len(parent.replies) == 1
    assert parent.replies[0].message_id == "msg2"
    assert parent.replies[0].in_reply_to == "msg1"
    assert parent.date is None
    assert parent.in_reply_to is None

    # JSON 往返测试
    json_data = parent.model_dump_json()
    loaded = ParsedComment.model_validate_json(json_data)
    assert loaded.replies[0].author == "Reviewer <rev@kernel.org>"
    assert loaded.replies[0].body == "Looks good, thanks."


def test_parsed_cover_letter_model():
    cover = ParsedCoverLetter(
        subject="[PATCH 0/2] series introduction",
        author="Dev <dev@test.org>",
        message_id="cover1",
        body="Series details",
        diffstat="mm/page_alloc.c | 10 ++\n 1 file changed",
    )
    assert cover.subject == "[PATCH 0/2] series introduction"
    assert cover.author == "Dev <dev@test.org>"
    assert cover.date is None
    assert cover.diffstat == "mm/page_alloc.c | 10 ++\n 1 file changed"


def test_parsed_patchset_model():
    patch = ParsedPatch(
        index=1,
        total=1,
        subject="[PATCH] fix something",
        author="Dev <dev@test.org>",
        message_id="patch1",
        commit_message="Fix a bug in mm",
        trailers=["Signed-off-by: Dev <dev@test.org>"],
        diff="--- a/mm.c\n+++ b/mm.c\n@@ ...",
    )
    assert patch.date is None
    assert patch.diffstat is None
    assert patch.comments == []

    patchset = ParsedPatchset(
        id="patch1",
        title="[PATCH] fix something",
        total_patches=1,
        patches=[patch],
    )
    assert patchset.total_patches == 1
    assert patchset.cover_letter is None
    assert patchset.general_comments == []
    assert len(patchset.patches) == 1


def test_patchset_analysis_model():
    from pathlib import Path
    from kp.models import PatchsetAnalysis, AnalyzeRunResult

    analysis = PatchsetAnalysis(
        msgid="<test@example.com>",
        sanitized_id="test_example_com",
        status="success",
        report_path=Path("data/runs/123/reports/test_example_com.md"),
        duration_seconds=12.5,
    )
    assert analysis.msgid == "<test@example.com>"
    assert analysis.sanitized_id == "test_example_com"
    assert analysis.status == "success"
    assert analysis.report_path == Path("data/runs/123/reports/test_example_com.md")
    assert analysis.error_message is None
    assert analysis.duration_seconds == 12.5

    # Test defaults
    analysis_default = PatchsetAnalysis(
        msgid="<test2@example.com>",
        sanitized_id="test2_example_com",
        status="failed",
        error_message="Agent execution timeout",
    )
    assert analysis_default.report_path is None
    assert analysis_default.error_message == "Agent execution timeout"
    assert analysis_default.duration_seconds == 0.0

    run_result = AnalyzeRunResult(
        run_id="run-1",
        analyses=[analysis, analysis_default],
        total_count=2,
        success_count=1,
        failed_count=1,
    )
    assert run_result.run_id == "run-1"
    assert len(run_result.analyses) == 2
    assert run_result.total_count == 2
    assert run_result.success_count == 1
    assert run_result.failed_count == 1

    # Check defaults and serialization
    empty_result = AnalyzeRunResult(run_id="run-empty")
    assert empty_result.analyses == []
    assert empty_result.total_count == 0
    assert empty_result.success_count == 0
    assert empty_result.failed_count == 0

    dumped = run_result.model_dump()
    loaded = AnalyzeRunResult.model_validate(dumped)
    assert loaded == run_result
