from kp.models import RawMessage, PatchItem, Patchset, RunManifest

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

def test_patch_item():
    patch = PatchItem(
        index=1,
        total=2,
        title="[PATCH 1/2] mm: sample fix 1",
        message_id="patch1@msgid",
        date="2026-08-30T10:00:00Z"
    )
    assert patch.index == 1
    assert patch.total == 2
    assert patch.title == "[PATCH 1/2] mm: sample fix 1"
    assert patch.message_id == "patch1@msgid"
    assert patch.date == "2026-08-30T10:00:00Z"

def test_patch_item_optional_date():
    patch = PatchItem(
        index=1,
        total=1,
        title="[PATCH] fix typo",
        message_id="patch@msgid",
    )
    assert patch.date is None

def test_patchset_structure():
    patch1 = PatchItem(
        index=1,
        total=2,
        title="[PATCH 1/2] mm: sample fix 1",
        message_id="patch1@msgid",
        date="2026-08-30T10:00:00Z"
    )
    patchset = Patchset(
        id="cover@msgid",
        title="[PATCH 0/2] mm: sample series",
        author_name="John Doe",
        author_email="john@example.com",
        date="2026-08-30T10:00:00Z",
        is_cover_letter=True,
        total_patches=2,
        patches=[patch1]
    )
    assert patchset.id == "cover@msgid"
    assert patchset.title == "[PATCH 0/2] mm: sample series"
    assert patchset.author_name == "John Doe"
    assert patchset.author_email == "john@example.com"
    assert patchset.is_cover_letter is True
    assert patchset.total_patches == 2
    assert len(patchset.patches) == 1
    assert patchset.patches[0].index == 1

def test_patchset_defaults():
    patchset = Patchset(
        id="patch1@msgid",
        title="[PATCH] single fix",
        author_name="Jane Doe",
        author_email="jane@example.com",
    )
    assert patchset.is_cover_letter is False
    assert patchset.total_patches == 1
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
