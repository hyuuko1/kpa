from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kp.adapters.b4 import B4Client, B4ExecutionError
from kp.config import AppConfig, B4Config, StorageConfig
from kp.core.download_pipeline import DownloadPipeline, DownloadResult
from kp.core.parser import MboxParser
from kp.models import ParsedPatch, ParsedPatchset, Patchset
from kp.storage.session import SessionManager


@pytest.fixture
def mock_env(tmp_path):
    storage_dir = tmp_path / "runs"
    config = AppConfig(
        storage=StorageConfig(data_dir=str(storage_dir)),
        b4=B4Config(timeout_seconds=30),
    )
    session_manager = SessionManager(config.storage)
    run_id, run_dir = session_manager.create_session_dir()

    # 创建初始 patchsets.json
    patchsets = [
        Patchset(
            id="patch1@example.com",
            title="[PATCH 1/2] mm: fix alloc bug",
            author_name="Alice",
            author_email="alice@example.com",
            patches=["[PATCH 1/2] mm: fix alloc bug", "[PATCH 2/2] mm: add test"],
        ),
        Patchset(
            id="patch2@example.com",
            title="[PATCH] net: trivial typo fix",
            author_name="Bob",
            author_email="bob@example.com",
            patches=["[PATCH] net: trivial typo fix"],
        ),
        Patchset(
            id="patch3@example.com",
            title="[PATCH 0/3] sched: revamp balancer",
            author_name="Charlie",
            author_email="charlie@example.com",
            patches=["[PATCH 1/3] sched: step 1", "[PATCH 2/3] sched: step 2", "[PATCH 3/3] sched: step 3"],
        ),
    ]
    patchsets_file = run_dir / "patchsets.json"
    patchsets_file.write_text(
        json.dumps([p.model_dump() for p in patchsets], indent=2),
        encoding="utf-8",
    )

    return {
        "config": config,
        "session_manager": session_manager,
        "run_id": run_id,
        "run_dir": run_dir,
        "patchsets": patchsets,
    }


def test_download_pipeline_by_reviews(mock_env, tmp_path):
    config = mock_env["config"]
    session_manager = mock_env["session_manager"]
    run_id = mock_env["run_id"]
    run_dir = mock_env["run_dir"]

    mock_b4 = MagicMock(spec=B4Client)
    mock_b4.sanitize_id.side_effect = lambda msgid: B4Client.sanitize_id(msgid)

    def fake_fetch_thread(msgid, output_dir, mbox_name="series.mbx"):
        p = Path(output_dir) / mbox_name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("From xxx\nSubject: fake\n", encoding="utf-8")
        return p

    mock_b4.fetch_thread.side_effect = fake_fetch_thread

    mock_parser = MagicMock(spec=MboxParser)

    def fake_parse(mbox_path, patchset_id, title=""):
        return ParsedPatchset(
            id=patchset_id,
            title=title or patchset_id,
            total_patches=1,
            patches=[
                ParsedPatch(
                    index=1,
                    total=1,
                    subject=title or patchset_id,
                    author="Test <test@kernel.org>",
                    message_id=patchset_id,
                    commit_message="Test commit",
                    diff="--- a/file\n+++ b/file\n",
                )
            ],
        )

    mock_parser.parse.side_effect = fake_parse

    pipeline = DownloadPipeline(
        config=config,
        b4_client=mock_b4,
        session_manager=session_manager,
        mbox_parser=mock_parser,
    )

    reviews_data = [
        {
            "id": "patch1@example.com",
            "title": "[PATCH 1/2] mm: fix alloc bug",
            "score": 85,
            "recommend": True,
            "reason": "Important memory management fix",
        },
        {
            "id": "patch2@example.com",
            "title": "[PATCH] net: trivial typo fix",
            "score": 50,
            "recommend": False,
            "reason": "Trivial typo",
        },
        {
            "id": "patch3@example.com",
            "title": "[PATCH 0/3] sched: revamp balancer",
            "score": 65,
            "recommend": True,
            "reason": "Architecture redesign recommended despite lower score",
        },
    ]
    reviews_json_str = json.dumps(reviews_data)

    result = pipeline.run(
        run_id=run_id,
        reviews_content=reviews_json_str,
        min_score=70,
    )

    assert isinstance(result, DownloadResult)
    assert result.run_id == run_id
    assert result.run_dir == run_dir
    assert result.downloaded_count == 2
    assert len(result.parsed_patchsets) == 2

    # 验证持久化文件
    assert (run_dir / "reviews.json").exists()
    assert (run_dir / "filtered_patchsets.json").exists()
    assert (run_dir / "stage3_prompt.md").exists()
    assert result.stage3_prompt_path == run_dir / "stage3_prompt.md"

    # 检查 filtered_patchsets 内容
    filtered = json.loads((run_dir / "filtered_patchsets.json").read_text(encoding="utf-8"))
    filtered_ids = [item["id"] for item in filtered]
    assert "patch1@example.com" in filtered_ids
    assert "patch3@example.com" in filtered_ids
    assert "patch2@example.com" not in filtered_ids

    # 检查 b4 调用参数
    assert mock_b4.fetch_thread.call_count == 2
    fetched_ids = [call.args[0] for call in mock_b4.fetch_thread.call_args_list]
    assert "patch1@example.com" in fetched_ids
    assert "patch3@example.com" in fetched_ids


def test_download_pipeline_dict_with_reviews_key(mock_env):
    config = mock_env["config"]
    session_manager = mock_env["session_manager"]
    run_id = mock_env["run_id"]

    mock_b4 = MagicMock(spec=B4Client)
    mock_b4.sanitize_id.side_effect = lambda msgid: B4Client.sanitize_id(msgid)

    def fake_fetch_thread(msgid, output_dir, mbox_name="series.mbx"):
        p = Path(output_dir) / mbox_name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("From xxx\n", encoding="utf-8")
        return p

    mock_b4.fetch_thread.side_effect = fake_fetch_thread

    mock_parser = MagicMock(spec=MboxParser)
    mock_parser.parse.return_value = ParsedPatchset(
        id="patch1@example.com",
        title="mm patch",
        total_patches=1,
    )

    pipeline = DownloadPipeline(
        config=config,
        b4_client=mock_b4,
        session_manager=session_manager,
        mbox_parser=mock_parser,
    )

    reviews_obj = {
        "reviews": [
            {
                "id": "patch1@example.com",
                "score": 95,
                "recommend": True,
                "reason": "Top priority",
            }
        ]
    }

    result = pipeline.run(
        run_id=run_id,
        reviews_content=json.dumps(reviews_obj),
    )

    assert result.downloaded_count == 1
    assert result.parsed_patchsets[0].id == "patch1@example.com"


def test_download_pipeline_by_target_ids(mock_env):
    config = mock_env["config"]
    session_manager = mock_env["session_manager"]
    run_id = mock_env["run_id"]
    run_dir = mock_env["run_dir"]

    mock_b4 = MagicMock(spec=B4Client)
    mock_b4.sanitize_id.side_effect = lambda msgid: B4Client.sanitize_id(msgid)

    def fake_fetch_thread(msgid, output_dir, mbox_name="series.mbx"):
        p = Path(output_dir) / mbox_name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("From xxx\n", encoding="utf-8")
        return p

    mock_b4.fetch_thread.side_effect = fake_fetch_thread

    mock_parser = MagicMock(spec=MboxParser)
    mock_parser.parse.return_value = ParsedPatchset(
        id="patch2@example.com",
        title="[PATCH] net: trivial typo fix",
        total_patches=1,
    )

    pipeline = DownloadPipeline(
        config=config,
        b4_client=mock_b4,
        session_manager=session_manager,
        mbox_parser=mock_parser,
    )

    result = pipeline.run(
        run_id=run_id,
        target_ids=["patch2@example.com"],
    )

    assert result.downloaded_count == 1
    assert len(result.parsed_patchsets) == 1
    assert result.parsed_patchsets[0].id == "patch2@example.com"
    assert (run_dir / "stage3_prompt.md").exists()
    assert not (run_dir / "reviews.json").exists()


def test_download_pipeline_combined_targets_and_reviews_dedup(mock_env):
    config = mock_env["config"]
    session_manager = mock_env["session_manager"]
    run_id = mock_env["run_id"]

    mock_b4 = MagicMock(spec=B4Client)
    mock_b4.sanitize_id.side_effect = lambda msgid: B4Client.sanitize_id(msgid)

    def fake_fetch_thread(msgid, output_dir, mbox_name="series.mbx"):
        p = Path(output_dir) / mbox_name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("From xxx\n", encoding="utf-8")
        return p

    mock_b4.fetch_thread.side_effect = fake_fetch_thread

    mock_parser = MagicMock(spec=MboxParser)

    def fake_parse(mbox_path, patchset_id, title=""):
        return ParsedPatchset(
            id=patchset_id,
            title=title or patchset_id,
            total_patches=1,
        )

    mock_parser.parse.side_effect = fake_parse

    pipeline = DownloadPipeline(
        config=config,
        b4_client=mock_b4,
        session_manager=session_manager,
        mbox_parser=mock_parser,
    )

    reviews_data = [
        {
            "id": "patch1@example.com",
            "score": 90,
            "recommend": True,
            "reason": "Important",
        }
    ]

    # target_ids 重复包含 patch1@example.com 并新增 patch2@example.com
    result = pipeline.run(
        run_id=run_id,
        reviews_content=json.dumps(reviews_data),
        target_ids=["patch1@example.com", "patch2@example.com"],
    )

    # 去重后应当只下载 2 个 (patch1, patch2)
    assert result.downloaded_count == 2
    assert mock_b4.fetch_thread.call_count == 2


def test_download_pipeline_markdown_fences_reviews(mock_env):
    config = mock_env["config"]
    session_manager = mock_env["session_manager"]
    run_id = mock_env["run_id"]

    mock_b4 = MagicMock(spec=B4Client)
    mock_b4.sanitize_id.side_effect = lambda msgid: B4Client.sanitize_id(msgid)

    def fake_fetch_thread(msgid, output_dir, mbox_name="series.mbx"):
        p = Path(output_dir) / mbox_name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("From xxx\n", encoding="utf-8")
        return p

    mock_b4.fetch_thread.side_effect = fake_fetch_thread

    mock_parser = MagicMock(spec=MboxParser)
    mock_parser.parse.return_value = ParsedPatchset(
        id="patch1@example.com",
        title="mm patch",
        total_patches=1,
    )

    pipeline = DownloadPipeline(
        config=config,
        b4_client=mock_b4,
        session_manager=session_manager,
        mbox_parser=mock_parser,
    )

    fenced_content = """```json
[
  {
    "id": "patch1@example.com",
    "score": 90,
    "recommend": true,
    "reason": "Crucial fix"
  }
]
```"""

    result = pipeline.run(
        run_id=run_id,
        reviews_content=fenced_content,
        min_score=70,
    )

    assert result.downloaded_count == 1
    assert result.parsed_patchsets[0].id == "patch1@example.com"


def test_download_pipeline_markdown_fences_with_leading_conversational_text(mock_env):
    config = mock_env["config"]
    session_manager = mock_env["session_manager"]
    run_id = mock_env["run_id"]

    mock_b4 = MagicMock(spec=B4Client)
    mock_b4.sanitize_id.side_effect = lambda msgid: B4Client.sanitize_id(msgid)

    def fake_fetch_thread(msgid, output_dir, mbox_name="series.mbx"):
        p = Path(output_dir) / mbox_name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("From xxx\n", encoding="utf-8")
        return p

    mock_b4.fetch_thread.side_effect = fake_fetch_thread

    mock_parser = MagicMock(spec=MboxParser)
    mock_parser.parse.return_value = ParsedPatchset(
        id="patch1@example.com",
        title="mm patch",
        total_patches=1,
    )

    pipeline = DownloadPipeline(
        config=config,
        b4_client=mock_b4,
        session_manager=session_manager,
        mbox_parser=mock_parser,
    )

    conversational_content = """Here is the patch review result as requested:

```json
[
  {
    "id": "patch1@example.com",
    "score": 85,
    "recommend": true,
    "reason": "Well tested fix"
  }
]
```

Let me know if you need further analysis!"""

    result = pipeline.run(
        run_id=run_id,
        reviews_content=conversational_content,
        min_score=70,
    )

    assert result.downloaded_count == 1
    assert result.parsed_patchsets[0].id == "patch1@example.com"


def test_download_pipeline_invalid_reviews_json(mock_env):
    config = mock_env["config"]
    session_manager = mock_env["session_manager"]
    run_id = mock_env["run_id"]

    pipeline = DownloadPipeline(
        config=config,
        session_manager=session_manager,
    )

    with pytest.raises(ValueError) as exc_info:
        pipeline.run(
            run_id=run_id,
            reviews_content="This is not valid JSON content",
        )
    assert "JSON" in str(exc_info.value) or "解析" in str(exc_info.value)


def test_download_pipeline_invalid_item_in_reviews(mock_env):
    config = mock_env["config"]
    session_manager = mock_env["session_manager"]
    run_id = mock_env["run_id"]

    pipeline = DownloadPipeline(
        config=config,
        session_manager=session_manager,
    )

    # score 超过 100 不合法
    invalid_data = [{"id": "p1", "score": 150, "recommend": True, "reason": "bad"}]

    with pytest.raises(ValueError) as exc_info:
        pipeline.run(
            run_id=run_id,
            reviews_content=json.dumps(invalid_data),
        )
    assert "格式错误" in str(exc_info.value) or "规范" in str(exc_info.value)


def test_download_pipeline_b4_failure_resilient(mock_env):
    config = mock_env["config"]
    session_manager = mock_env["session_manager"]
    run_id = mock_env["run_id"]

    mock_b4 = MagicMock(spec=B4Client)
    mock_b4.sanitize_id.side_effect = lambda msgid: B4Client.sanitize_id(msgid)

    # 第一个失败，第二个成功
    def side_effect_fetch(msgid, output_dir, mbox_name="series.mbx"):
        if msgid == "patch1@example.com":
            raise B4ExecutionError("b4 mbox failed: 404 not found on lore")
        p = Path(output_dir) / mbox_name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("From xxx\n", encoding="utf-8")
        return p

    mock_b4.fetch_thread.side_effect = side_effect_fetch

    mock_parser = MagicMock(spec=MboxParser)
    mock_parser.parse.return_value = ParsedPatchset(
        id="patch2@example.com",
        title="net patch",
        total_patches=1,
    )

    pipeline = DownloadPipeline(
        config=config,
        b4_client=mock_b4,
        session_manager=session_manager,
        mbox_parser=mock_parser,
    )

    result = pipeline.run(
        run_id=run_id,
        target_ids=["patch1@example.com", "patch2@example.com"],
    )

    # 虽然 patch1 失败，但 patch2 成功，不阻断
    assert result.downloaded_count == 1
    assert result.parsed_patchsets[0].id == "patch2@example.com"
    assert result.stage3_prompt_path is not None


def test_download_pipeline_empty_targets(mock_env):
    config = mock_env["config"]
    session_manager = mock_env["session_manager"]
    run_id = mock_env["run_id"]

    pipeline = DownloadPipeline(
        config=config,
        session_manager=session_manager,
    )

    result = pipeline.run(
        run_id=run_id,
        target_ids=[],
    )

    assert result.downloaded_count == 0
    assert result.parsed_patchsets == []
    assert result.stage3_prompt_path is not None
    assert result.stage3_prompt_path.exists()


def test_download_pipeline_nonexistent_run_dir(tmp_path):
    config = AppConfig(storage=StorageConfig(data_dir=str(tmp_path)))
    pipeline = DownloadPipeline(config=config)

    with pytest.raises(FileNotFoundError):
        pipeline.run(run_id="nonexistent_run_id_12345")
