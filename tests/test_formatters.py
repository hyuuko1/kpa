from kp.models import ParsedPatchset, ParsedPatch, ParsedCoverLetter, ParsedComment
from kp.core.formatters import (
    render_cover_letter_md,
    render_discussions_md,
    render_patch_file,
    render_meta_json,
    sanitize_filename,
)


def test_sanitize_filename():
    assert (
        sanitize_filename("[PATCH 1/3] mm/zswap: fix bug") == "PATCH_13_mmzswap_fix_bug"
    )
    assert sanitize_filename("") == "patch"


def test_render_cover_letter_md():
    cover = ParsedCoverLetter(
        subject="[PATCH 0/2] mm: overhaul",
        author="Alice <alice@kernel.org>",
        date="2026-08-30 12:00:00",
        message_id="cover123",
        body="This series overhauls mm.\n\nv2 changes:\n- Fixed bug",
        diffstat="mm/memory.c | 10 ++\n1 file changed",
    )
    md = render_cover_letter_md(cover)
    assert "# Cover Letter: [PATCH 0/2] mm: overhaul" in md
    assert "**Author**: Alice <alice@kernel.org>" in md
    assert "This series overhauls mm." in md
    assert "```text\nmm/memory.c | 10 ++\n1 file changed\n```" in md


def test_render_discussions_md_with_nested_replies():
    c2 = ParsedComment(
        author="Alice <alice@kernel.org>",
        date="2026-08-30 12:10:00",
        message_id="c2",
        in_reply_to="c1",
        body="Because we need locking.",
    )
    c1 = ParsedComment(
        author="Bob <bob@kernel.org>",
        date="2026-08-30 12:05:00",
        message_id="c1",
        body="Why do this?",
        replies=[c2],
    )
    patch = ParsedPatch(
        index=1,
        total=1,
        subject="[PATCH 1/1] mm: fix lock",
        author="Alice <alice@kernel.org>",
        message_id="p1",
        commit_message="Fix lock issue",
        diff="--- a/mm.c\n+++ b/mm.c",
        comments=[c1],
    )
    patchset = ParsedPatchset(
        id="p1",
        title="[PATCH 1/1] mm: fix lock",
        total_patches=1,
        patches=[patch],
    )

    md = render_discussions_md(patchset)
    assert "# 社区审阅与技术讨论" in md
    assert "### [PATCH 1/1] [PATCH 1/1] mm: fix lock" in md
    assert "> **Bob <bob@kernel.org>**" in md
    assert "> Why do this?" in md
    assert ">> **Alice <alice@kernel.org>**" in md
    assert ">> Because we need locking." in md


def test_render_patch_file():
    patch = ParsedPatch(
        index=1,
        total=1,
        subject="[PATCH 1/1] mm: fix lock",
        author="Alice <alice@kernel.org>",
        date="2026-08-30 12:00:00",
        message_id="p1",
        commit_message="Fix lock issue\n\nDetailed explanation here.",
        trailers=[
            "Signed-off-by: Alice <alice@kernel.org>",
            "Reviewed-by: Bob <bob@kernel.org>",
        ],
        diffstat="mm/file.c | 2 +-\n 1 file changed",
        diff="--- a/mm/file.c\n+++ b/mm/file.c\n@@ -1 +1 @@\n-old\n+new",
    )
    patch_text = render_patch_file(patch)
    assert "From: Alice <alice@kernel.org>" in patch_text
    assert "Subject: [PATCH 1/1] mm: fix lock" in patch_text
    assert "Detailed explanation here." in patch_text
    assert "Signed-off-by: Alice <alice@kernel.org>" in patch_text
    assert "---" in patch_text
    assert "mm/file.c | 2 +-" in patch_text
    assert "+new" in patch_text


def test_render_meta_json():
    patchset = ParsedPatchset(
        id="p1",
        title="[PATCH] mm: test",
        total_patches=1,
        patches=[
            ParsedPatch(
                index=1,
                total=1,
                subject="[PATCH] mm: test",
                author="Alice <a@b.c>",
                message_id="p1",
                commit_message="test",
                diff="diff",
            )
        ],
    )
    meta = render_meta_json(patchset)
    assert meta["id"] == "p1"
    assert meta["total_patches"] == 1
    assert len(meta["patches"]) == 1
    assert "diff" not in meta["patches"][0]  # 没有庞大的 diff
