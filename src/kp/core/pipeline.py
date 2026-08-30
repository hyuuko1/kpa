from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel
from kp.config import AppConfig
from kp.adapters.lore import LoreClient
from kp.core.aggregator import PatchsetAggregator
from kp.core.prompt import PromptBuilder
from kp.storage.session import SessionManager
from kp.models import RunManifest


class PipelineResult(BaseModel):
    run_id: str
    run_dir: Path
    raw_count: int
    patchset_count: int
    prompt_path: Path


class FetchPipeline:
    """阶段一核心业务流水线：Query -> Lore -> Aggregator -> SessionStorage -> Prompt"""

    def __init__(self, config: AppConfig):
        self.config = config
        self.lore_client = LoreClient(config.lore, config.safety)
        self.aggregator = PatchsetAggregator()
        self.session_manager = SessionManager(config.storage)
        self.prompt_builder = PromptBuilder()

    def run(self, query: str) -> PipelineResult:
        # 1. 创建 Run 会话目录
        run_id, run_dir = self.session_manager.create_session_dir()
        now_iso = datetime.now(timezone.utc).isoformat()

        # 2. 调用 Lore 抓取原始元数据
        raw_msgs = self.lore_client.query(query)

        # 3. 清洗与聚合为 Patchset 列表
        patchsets = self.aggregator.aggregate(raw_msgs)

        # 4. 生成提示词内容（引用 patchsets.json 绝对路径）
        patchsets_file = run_dir / "patchsets.json"
        prompt_content = self.prompt_builder.build_prompt(patchsets_file)

        # 5. 持久化所有成果物
        manifest = RunManifest(
            run_id=run_id,
            timestamp=now_iso,
            query=query,
            total_raw_messages=len(raw_msgs),
            total_patchsets=len(patchsets),
        )
        self.session_manager.save_run(
            run_dir=run_dir,
            manifest=manifest,
            raw_msgs=raw_msgs,
            patchsets=patchsets,
            prompt_content=prompt_content,
        )

        return PipelineResult(
            run_id=run_id,
            run_dir=run_dir,
            raw_count=len(raw_msgs),
            patchset_count=len(patchsets),
            prompt_path=run_dir / "prompt.md",
        )
