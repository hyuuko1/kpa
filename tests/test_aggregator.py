import pytest
from kp.models import RawMessage
from kp.core.aggregator import PatchsetAggregator

def test_parse_subject_patterns():
    aggregator = PatchsetAggregator()
    # Cover letter
    is_cov, idx, tot = aggregator.parse_subject_meta("[PATCH 0/4] mm/damon: improve monitoring")
    assert is_cov is True
    assert idx == 0
    assert tot == 4

    # Subpatch
    is_cov, idx, tot = aggregator.parse_subject_meta("[PATCH v2 3/4] mm/damon: add tests")
    assert is_cov is False
    assert idx == 3
    assert tot == 4

    # Standalone patch
    is_cov, idx, tot = aggregator.parse_subject_meta("[PATCH] mm: fix leak")
    assert is_cov is False
    assert idx == 1
    assert tot == 1

    # RFC with version
    is_cov, idx, tot = aggregator.parse_subject_meta("[RFC PATCH v3 0/2] mm: series")
    assert is_cov is True
    assert idx == 0
    assert tot == 2

    # Subsystem tag
    is_cov, idx, tot = aggregator.parse_subject_meta("[PATCH net-next 2/5] net: fix")
    assert is_cov is False
    assert idx == 2
    assert tot == 5

    # 1/1 patch
    is_cov, idx, tot = aggregator.parse_subject_meta("[PATCH 1/1] doc: fix typo")
    assert is_cov is False
    assert idx == 1
    assert tot == 1

    # Non-patch subject
    is_cov, idx, tot = aggregator.parse_subject_meta("Question about slab")
    assert is_cov is False
    assert idx == 1
    assert tot == 1

    # Test parse_subject interface (returning 4-tuple: is_cover, index, total, title)
    is_cov, idx, tot, title = aggregator.parse_subject("[PATCH 1/2] mm/test: part 1")
    assert is_cov is False
    assert idx == 1
    assert tot == 2
    assert title == "[PATCH 1/2] mm/test: part 1"

def test_aggregate_series_with_cover_letter():
    aggregator = PatchsetAggregator()
    raw_msgs = [
        RawMessage(
            m="cover@1",
            s="[PATCH 0/2] mm/test: series cover",
            f=[["Dev", "dev@kernel.org"]],
            dt="2026-08-30T10:00:00Z",
            refs=[]
        ),
        RawMessage(
            m="patch1@1",
            s="[PATCH 1/2] mm/test: part 1",
            f=[["Dev", "dev@kernel.org"]],
            dt="2026-08-30T10:01:00Z",
            refs=["cover@1"]
        ),
        RawMessage(
            m="patch2@1",
            s="[PATCH 2/2] mm/test: part 2",
            f=[["Dev", "dev@kernel.org"]],
            dt="2026-08-30T10:02:00Z",
            refs=["cover@1"]
        ),
    ]

    patchsets = aggregator.aggregate(raw_msgs)
    assert len(patchsets) == 1
    ps = patchsets[0]
    assert ps.id == "cover@1"
    assert ps.title == "[PATCH 0/2] mm/test: series cover"
    assert ps.author_name == "Dev"
    assert ps.author_email == "dev@kernel.org"
    assert ps.date == "2026-08-30T10:00:00Z"
    assert ps.is_cover_letter is True
    assert ps.total_patches == 2
    assert len(ps.patches) == 2
    assert ps.patches[0].index == 1
    assert ps.patches[0].title == "[PATCH 1/2] mm/test: part 1"
    assert ps.patches[0].message_id == "patch1@1"
    assert ps.patches[1].index == 2
    assert ps.patches[1].title == "[PATCH 2/2] mm/test: part 2"
    assert ps.patches[1].message_id == "patch2@1"

def test_aggregate_standalone_patches():
    aggregator = PatchsetAggregator()
    raw_msgs = [
        RawMessage(
            m="standalone@1",
            s="[PATCH] mm/slab: fix typo",
            f=[["Alice", "alice@kernel.org"]],
            dt="2026-08-30T11:00:00Z",
            refs=[]
        )
    ]
    patchsets = aggregator.aggregate(raw_msgs)
    assert len(patchsets) == 1
    ps = patchsets[0]
    assert ps.id == "standalone@1"
    assert ps.title == "[PATCH] mm/slab: fix typo"
    assert ps.author_name == "Alice"
    assert ps.author_email == "alice@kernel.org"
    assert ps.date == "2026-08-30T11:00:00Z"
    assert ps.is_cover_letter is False
    assert ps.total_patches == 1
    assert len(ps.patches) == 1
    assert ps.patches[0].title == "[PATCH] mm/slab: fix typo"
    assert ps.patches[0].index == 1
    assert ps.patches[0].total == 1

def test_aggregate_series_without_cover_letter_out_of_order():
    aggregator = PatchsetAggregator()
    # Out of order delivery: patch 2 first, then patch 1
    raw_msgs = [
        RawMessage(
            m="patch2@1",
            s="[PATCH 2/2] mm/test: part 2",
            f=[["Bob", "bob@kernel.org"]],
            dt="2026-08-30T12:02:00Z",
            refs=["patch1@1"]
        ),
        RawMessage(
            m="patch1@1",
            s="[PATCH 1/2] mm/test: part 1",
            f=[["Bob", "bob@kernel.org"]],
            dt="2026-08-30T12:01:00Z",
            refs=[]
        ),
    ]
    patchsets = aggregator.aggregate(raw_msgs)
    assert len(patchsets) == 1
    ps = patchsets[0]
    assert ps.id == "patch1@1"
    assert ps.title == "[PATCH 1/2] mm/test: part 1"
    assert ps.author_name == "Bob"
    assert ps.author_email == "bob@kernel.org"
    assert ps.is_cover_letter is False
    assert ps.total_patches == 2
    assert len(ps.patches) == 2
    # Ensure patches are sorted by index
    assert ps.patches[0].index == 1
    assert ps.patches[0].title == "[PATCH 1/2] mm/test: part 1"
    assert ps.patches[1].index == 2
    assert ps.patches[1].title == "[PATCH 2/2] mm/test: part 2"

def test_aggregate_empty_messages():
    aggregator = PatchsetAggregator()
    assert aggregator.aggregate([]) == []

def test_aggregate_sorting_by_date():
    aggregator = PatchsetAggregator()
    raw_msgs = [
        RawMessage(
            m="old@1",
            s="[PATCH] old patch",
            f=[["Dev", "dev@kernel.org"]],
            dt="2026-08-30T09:00:00Z",
            refs=[]
        ),
        RawMessage(
            m="new@1",
            s="[PATCH] new patch",
            f=[["Dev", "dev@kernel.org"]],
            dt="2026-08-30T14:00:00Z",
            refs=[]
        ),
        RawMessage(
            m="mid@1",
            s="[PATCH] mid patch",
            f=[["Dev", "dev@kernel.org"]],
            dt="2026-08-30T11:00:00Z",
            refs=[]
        ),
    ]
    patchsets = aggregator.aggregate(raw_msgs)
    assert len(patchsets) == 3
    assert patchsets[0].id == "new@1"
    assert patchsets[1].id == "mid@1"
    assert patchsets[2].id == "old@1"

def test_aggregate_chained_threading():
    aggregator = PatchsetAggregator()
    raw_msgs = [
        RawMessage(
            m="cover@chain",
            s="[PATCH 0/3] chained series",
            f=[["Carol", "carol@kernel.org"]],
            dt="2026-08-30T08:00:00Z",
            refs=[]
        ),
        RawMessage(
            m="patch1@chain",
            s="[PATCH 1/3] part 1",
            f=[["Carol", "carol@kernel.org"]],
            dt="2026-08-30T08:01:00Z",
            refs=["cover@chain"]
        ),
        RawMessage(
            m="patch2@chain",
            s="[PATCH 2/3] part 2",
            f=[["Carol", "carol@kernel.org"]],
            dt="2026-08-30T08:02:00Z",
            refs=["patch1@chain"]
        ),
        RawMessage(
            m="patch3@chain",
            s="[PATCH 3/3] part 3",
            f=[["Carol", "carol@kernel.org"]],
            dt="2026-08-30T08:03:00Z",
            refs=["patch2@chain"]
        ),
    ]
    patchsets = aggregator.aggregate(raw_msgs)
    assert len(patchsets) == 1
    ps = patchsets[0]
    assert ps.id == "cover@chain"
    assert ps.total_patches == 3
    assert len(ps.patches) == 3
    assert [p.index for p in ps.patches] == [1, 2, 3]

def test_aggregate_author_fallbacks():
    aggregator = PatchsetAggregator()
    # Missing/empty from field
    raw_msgs = [
        RawMessage(
            m="msg1@test",
            s="[PATCH] test fallback",
            f=[],
            dt="2026-08-30T10:00:00Z"
        )
    ]
    patchsets = aggregator.aggregate(raw_msgs)
    assert len(patchsets) == 1
    assert patchsets[0].author_name == "Unknown"
    assert patchsets[0].author_email == "unknown@kernel.org"

    # From with None values
    raw_msgs_none = [
        RawMessage(
            m="msg2@test",
            s="[PATCH] test none from",
            f=[[None, None]],
            dt="2026-08-30T10:00:00Z"
        )
    ]
    patchsets2 = aggregator.aggregate(raw_msgs_none)
    assert len(patchsets2) == 1
    assert patchsets2[0].author_name == "Unknown"
    assert patchsets2[0].author_email == "unknown@kernel.org"

def test_aggregate_partial_series():
    aggregator = PatchsetAggregator()
    # Received only patch 2 of 4, no cover letter
    raw_msgs = [
        RawMessage(
            m="patch2@test",
            s="[PATCH 2/4] part 2",
            f=[["Author", "author@kernel.org"]],
            dt="2026-08-30T10:00:00Z",
            refs=[]
        )
    ]
    patchsets = aggregator.aggregate(raw_msgs)
    assert len(patchsets) == 1
    ps = patchsets[0]
    assert ps.total_patches == 4
    assert len(ps.patches) == 1
    assert ps.patches[0].index == 2
    assert ps.patches[0].total == 4
