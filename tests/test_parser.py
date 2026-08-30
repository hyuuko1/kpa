from pathlib import Path
from kp.core.parser import MboxParser


def test_parse_single_patch(tmp_path: Path):
    mbox_file = tmp_path / "single.mbx"
    mbox_file.write_text(
        """From git@z Thu Jan  1 00:00:00 1970
From: Alice <alice@example.com>
Subject: [PATCH] mm: fix null pointer in alloc
Date: Sun, 30 Aug 2026 12:00:00 +0000
Message-Id: <patch1@example.com>
Content-Type: text/plain; charset="utf-8"

Fix a critical null pointer dereference when allocating page.

Signed-off-by: Alice <alice@example.com>
Reviewed-by: Bob <bob@example.com>
---
 mm/alloc.c | 2 ++
 1 file changed, 2 insertions(+)

diff --git a/mm/alloc.c b/mm/alloc.c
index 111..222 100644
--- a/mm/alloc.c
+++ b/mm/alloc.c
@@ -10,6 +10,8 @@ void *alloc(void) {
+    if (!ptr)
+        return NULL;
     return ptr;
 }
-- 
2.43.0
""",
        encoding="utf-8",
    )

    parser = MboxParser()
    parsed = parser.parse(mbox_file, patchset_id="patch1@example.com")

    assert parsed.id == "patch1@example.com"
    assert parsed.total_patches == 1
    assert parsed.cover_letter is None
    assert len(parsed.patches) == 1

    patch = parsed.patches[0]
    assert patch.index == 1
    assert patch.total == 1
    assert patch.author == "Alice <alice@example.com>"
    assert "Fix a critical null pointer" in patch.commit_message
    assert "Signed-off-by: Alice <alice@example.com>" in patch.trailers
    assert "Reviewed-by: Bob <bob@example.com>" in patch.trailers
    assert patch.diffstat is not None
    assert "mm/alloc.c | 2 ++" in patch.diffstat
    assert "diff --git a/mm/alloc.c" in patch.diff


def test_parse_series_with_cover_and_nested_comments(tmp_path: Path):
    mbox_file = tmp_path / "series.mbx"
    mbox_file.write_text(
        """From git@z Thu Jan  1 00:00:00 1970
From: Alice <alice@example.com>
Subject: [PATCH 0/2] mm: revamp page allocator
Date: Sun, 30 Aug 2026 12:00:00 +0000
Message-Id: <cover@example.com>

This series revamps page allocator to improve performance.

Alice (2):
  mm: step 1
  mm: step 2

 mm/alloc.c | 10 ++
 1 file changed, 10 insertions(+)

From git@z Thu Jan  1 00:00:00 1970
From: Alice <alice@example.com>
Subject: [PATCH 1/2] mm: step 1
Date: Sun, 30 Aug 2026 12:01:00 +0000
Message-Id: <p1@example.com>
In-Reply-To: <cover@example.com>

Step 1 description.

Signed-off-by: Alice <alice@example.com>
---
diff --git a/mm/alloc.c b/mm/alloc.c
--- a/mm/alloc.c
+++ b/mm/alloc.c
@@ -1 +1,5 @@
+step 1

From git@z Thu Jan  1 00:00:00 1970
From: Bob <bob@example.com>
Subject: Re: [PATCH 1/2] mm: step 1
Date: Sun, 30 Aug 2026 12:05:00 +0000
Message-Id: <comment1@example.com>
In-Reply-To: <p1@example.com>

Why not do this differently?

From git@z Thu Jan  1 00:00:00 1970
From: Alice <alice@example.com>
Subject: Re: [PATCH 1/2] mm: step 1
Date: Sun, 30 Aug 2026 12:10:00 +0000
Message-Id: <comment2@example.com>
In-Reply-To: <comment1@example.com>

Because of cache alignment.

From git@z Thu Jan  1 00:00:00 1970
From: Alice <alice@example.com>
Subject: [PATCH 2/2] mm: step 2
Date: Sun, 30 Aug 2026 12:02:00 +0000
Message-Id: <p2@example.com>
In-Reply-To: <cover@example.com>

Step 2 description.

Signed-off-by: Alice <alice@example.com>
---
diff --git a/mm/alloc.c b/mm/alloc.c
--- a/mm/alloc.c
+++ b/mm/alloc.c
@@ -2 +2,5 @@
+step 2
""",
        encoding="utf-8",
    )

    parser = MboxParser()
    parsed = parser.parse(mbox_file, patchset_id="cover@example.com")

    assert parsed.cover_letter is not None
    assert "revamp page allocator" in parsed.cover_letter.subject
    assert "This series revamps page allocator" in parsed.cover_letter.body
    assert len(parsed.patches) == 2

    # 验证 patch 1 的评论树
    p1 = parsed.patches[0]
    assert p1.index == 1
    assert p1.total == 2
    assert len(p1.comments) == 1
    c1 = p1.comments[0]
    assert c1.message_id == "comment1@example.com"
    assert "Why not do this differently?" in c1.body
    assert len(c1.replies) == 1
    assert c1.replies[0].message_id == "comment2@example.com"
    assert "Because of cache alignment." in c1.replies[0].body

    # 验证 patch 2
    p2 = parsed.patches[1]
    assert p2.index == 2
    assert p2.total == 2
    assert len(p2.comments) == 0


def test_parse_empty_or_nonexistent_mbox(tmp_path: Path):
    mbox_file = tmp_path / "empty.mbx"
    mbox_file.write_text("", encoding="utf-8")

    parser = MboxParser()
    parsed = parser.parse(mbox_file, patchset_id="empty@example.com", title="Empty Title")

    assert parsed.id == "empty@example.com"
    assert parsed.title == "Empty Title"
    assert parsed.total_patches == 0
    assert parsed.cover_letter is None
    assert parsed.patches == []
    assert parsed.general_comments == []

    nonexistent = tmp_path / "does_not_exist.mbx"
    parsed_nonexistent = parser.parse(nonexistent, patchset_id="nonexistent@example.com")
    assert parsed_nonexistent.id == "nonexistent@example.com"
    assert parsed_nonexistent.total_patches == 0


def test_parse_encoded_headers_and_trailers(tmp_path: Path):
    mbox_file = tmp_path / "encoded.mbx"
    mbox_file.write_text(
        """From git@z Thu Jan  1 00:00:00 1970
From: =?utf-8?q?J=C3=A9r=C3=B4me_Dev?= <jerome@example.com>
Subject: =?utf-8?q?=5BPATCH=5D_fs=3A_fix_encoding_handling?=
Date: Sun, 30 Aug 2026 12:00:00 +0000
Message-Id: <encoded1@example.com>

Fix encoding issue in filesystem names.

Signed-off-by: Jérôme Dev <jerome@example.com>
Reviewed-by: Bob <bob@example.com>
Acked-by: Charlie <charlie@example.com>
Fixes: 1234abcd5678 ("fs: initial commit")
Link: https://lore.kernel.org/r/orig@example.com
---
 fs/name.c | 4 ++--
 1 file changed, 2 insertions(+), 2 deletions(-)

diff --git a/fs/name.c b/fs/name.c
--- a/fs/name.c
+++ b/fs/name.c
@@ -1,2 +1,2 @@
-old
+new
""",
        encoding="utf-8",
    )

    parser = MboxParser()
    parsed = parser.parse(mbox_file, patchset_id="encoded1@example.com")

    assert parsed.id == "encoded1@example.com"
    assert len(parsed.patches) == 1
    p = parsed.patches[0]
    assert "Jérôme Dev" in p.author
    assert "fs: fix encoding handling" in p.subject
    assert len(p.trailers) == 5
    assert "Signed-off-by: Jérôme Dev <jerome@example.com>" in p.trailers
    assert "Acked-by: Charlie <charlie@example.com>" in p.trailers
    assert 'Fixes: 1234abcd5678 ("fs: initial commit")' in p.trailers
    assert "Link: https://lore.kernel.org/r/orig@example.com" in p.trailers


def test_parse_general_and_orphan_comments(tmp_path: Path):
    mbox_file = tmp_path / "general.mbx"
    mbox_file.write_text(
        """From git@z Thu Jan  1 00:00:00 1970
From: Alice <alice@example.com>
Subject: [PATCH 0/1] mm: overview
Date: Sun, 30 Aug 2026 12:00:00 +0000
Message-Id: <cover@example.com>

Cover letter overview.

From git@z Thu Jan  1 00:00:00 1970
From: Alice <alice@example.com>
Subject: [PATCH 1/1] mm: implement thing
Date: Sun, 30 Aug 2026 12:01:00 +0000
Message-Id: <p1@example.com>
In-Reply-To: <cover@example.com>

Patch 1 body.

Signed-off-by: Alice <alice@example.com>
---
diff --git a/mm/thing.c b/mm/thing.c
--- a/mm/thing.c
+++ b/mm/thing.c
@@ -1 +1,2 @@
+thing

From git@z Thu Jan  1 00:00:00 1970
From: Reviewer <rev@example.com>
Subject: Re: [PATCH 0/1] mm: overview
Date: Sun, 30 Aug 2026 12:05:00 +0000
Message-Id: <general_comment@example.com>
In-Reply-To: <cover@example.com>

General feedback on the entire series architecture.

From git@z Thu Jan  1 00:00:00 1970
From: Orphan <orphan@example.com>
Subject: Re: [PATCH] old forgotten thread
Date: Sun, 30 Aug 2026 12:06:00 +0000
Message-Id: <orphan_comment@example.com>
In-Reply-To: <nonexistent@example.com>

Feedback referencing unknown message.
""",
        encoding="utf-8",
    )

    parser = MboxParser()
    parsed = parser.parse(mbox_file, patchset_id="cover@example.com")

    assert parsed.cover_letter is not None
    assert len(parsed.patches) == 1
    assert len(parsed.general_comments) == 2
    ids = [c.message_id for c in parsed.general_comments]
    assert "general_comment@example.com" in ids
    assert "orphan_comment@example.com" in ids


def test_parse_deep_and_branching_comments(tmp_path: Path):
    mbox_file = tmp_path / "deep.mbx"
    mbox_file.write_text(
        """From git@z Thu Jan  1 00:00:00 1970
From: Alice <alice@example.com>
Subject: [PATCH] net: fix sock refcount
Date: Sun, 30 Aug 2026 12:00:00 +0000
Message-Id: <net1@example.com>

Fix sock refcounting leak.

Signed-off-by: Alice <alice@example.com>
---
diff --git a/net/sock.c b/net/sock.c
--- a/net/sock.c
+++ b/net/sock.c
@@ -1 +1,2 @@
+refcount_inc();

From git@z Thu Jan  1 00:00:00 1970
From: ReviewerA <reva@example.com>
Subject: Re: [PATCH] net: fix sock refcount
Date: Sun, 30 Aug 2026 12:01:00 +0000
Message-Id: <commentA@example.com>
In-Reply-To: <net1@example.com>

Is this lock held here?

From git@z Thu Jan  1 00:00:00 1970
From: Alice <alice@example.com>
Subject: Re: [PATCH] net: fix sock refcount
Date: Sun, 30 Aug 2026 12:02:00 +0000
Message-Id: <commentAlice1@example.com>
In-Reply-To: <commentA@example.com>

Yes, lock is acquired in caller.

From git@z Thu Jan  1 00:00:00 1970
From: ReviewerB <revb@example.com>
Subject: Re: [PATCH] net: fix sock refcount
Date: Sun, 30 Aug 2026 12:03:00 +0000
Message-Id: <commentB@example.com>
In-Reply-To: <commentAlice1@example.com>

I checked caller and agree.

From git@z Thu Jan  1 00:00:00 1970
From: ReviewerC <revc@example.com>
Subject: Re: [PATCH] net: fix sock refcount
Date: Sun, 30 Aug 2026 12:04:00 +0000
Message-Id: <commentC@example.com>
In-Reply-To: <commentA@example.com>

Also consider socket shutdown path.
""",
        encoding="utf-8",
    )

    parser = MboxParser()
    parsed = parser.parse(mbox_file, patchset_id="net1@example.com")

    patch = parsed.patches[0]
    assert len(patch.comments) == 1
    cA = patch.comments[0]
    assert cA.message_id == "commentA@example.com"
    # cA has two branching replies: commentAlice1 and commentC
    assert len(cA.replies) == 2
    reply_ids = [r.message_id for r in cA.replies]
    assert "commentAlice1@example.com" in reply_ids
    assert "commentC@example.com" in reply_ids

    # commentAlice1 has child commentB
    alice_reply = next(r for r in cA.replies if r.message_id == "commentAlice1@example.com")
    assert len(alice_reply.replies) == 1
    assert alice_reply.replies[0].message_id == "commentB@example.com"


def test_parse_cyclic_comments_graceful_handling(tmp_path: Path):
    mbox_file = tmp_path / "cyclic.mbx"
    mbox_file.write_text(
        """From git@z Thu Jan  1 00:00:00 1970
From: Alice <alice@example.com>
Subject: [PATCH] sched: fix balance
Date: Sun, 30 Aug 2026 12:00:00 +0000
Message-Id: <p1@example.com>

Sched balance fix.

Signed-off-by: Alice <alice@example.com>
---
diff --git a/kernel/sched.c b/kernel/sched.c
--- a/kernel/sched.c
+++ b/kernel/sched.c
@@ -1 +1,2 @@
+balance();

From git@z Thu Jan  1 00:00:00 1970
From: Bob <bob@example.com>
Subject: Re: [PATCH] sched: fix balance
Date: Sun, 30 Aug 2026 12:01:00 +0000
Message-Id: <cA@example.com>
In-Reply-To: <cB@example.com>

Comment A pointing to B.

From git@z Thu Jan  1 00:00:00 1970
From: Charlie <charlie@example.com>
Subject: Re: [PATCH] sched: fix balance
Date: Sun, 30 Aug 2026 12:02:00 +0000
Message-Id: <cB@example.com>
In-Reply-To: <cA@example.com>

Comment B pointing to A.
""",
        encoding="utf-8",
    )

    parser = MboxParser()
    # Cyclic comments should not cause infinite loop or crash
    parsed = parser.parse(mbox_file, patchset_id="p1@example.com")
    assert parsed.total_patches == 1
    # Since neither points to p1, they get mounted safely
    total_comments = len(parsed.patches[0].comments) + len(parsed.general_comments)
    assert total_comments >= 1
