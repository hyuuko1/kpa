from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import List, Optional
from pydantic import BaseModel, Field

from kp.adapters.b4 import B4Client, B4ExecutionError, B4NotFoundError
from kp.config import AppConfig
from kp.core.parser import MboxParser
from kp.core.stage3_prompt import Stage3PromptBuilder
from kp.models import ParsedPatchset, PatchReview, Patchset
from kp.storage.session import SessionManager

logger = logging.getLogger(__name__)


class DownloadResult(BaseModel):
    """阶段二下载与解析流水线执行结果"""
    run_id: str
    run_dir: Path
    downloaded_count: int
    parsed_patchsets: List[ParsedPatchset] = Field(default_factory=list)
    stage3_prompt_path: Optional[Path] = None


class DownloadPipeline:
    """阶段二核心业务流水线：Reviews过滤 / 指定ID -> B4拉取 -> MboxParser清洗 -> SessionStorage持久化 -> Stage3Prompt生成"""

    def __init__(
        self,
        config: AppConfig,
        b4_client: Optional[B4Client] = None,
        session_manager: Optional[SessionManager] = None,
        mbox_parser: Optional[MboxParser] = None,
        prompt_builder: Optional[Stage3PromptBuilder] = None,
    ):
        self.config = config
        self.b4_client = b4_client or B4Client(config.b4)
        self.session_manager = session_manager or SessionManager(config.storage)
        self.mbox_parser = mbox_parser or MboxParser()
        self.prompt_builder = prompt_builder or Stage3PromptBuilder()

    def _parse_reviews(self, reviews_content: str) -> List[PatchReview]:
        """解析并校验 AI 评审结果 JSON 字符串"""
        text = reviews_content.strip()
        # 处理可能包含的 Markdown 代码块包裹 (如 ```json ... ```)
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            raw_data = json.loads(text)
        except Exception as e:
            raise ValueError(f"解析 AI 评审结果 JSON 失败: {e}") from e

        if isinstance(raw_data, dict) and "reviews" in raw_data and isinstance(raw_data["reviews"], list):
            items = raw_data["reviews"]
        elif isinstance(raw_data, list):
            items = raw_data
        else:
            raise ValueError("AI 评审结果 JSON 格式不符合规范：必须为评审列表或包含 'reviews' 键的字典")

        reviews: List[PatchReview] = []
        for idx, item in enumerate(items):
            try:
                review = PatchReview.model_validate(item)
                reviews.append(review)
            except Exception as e:
                raise ValueError(f"AI 评审结果第 {idx + 1} 项数据格式错误: {e}") from e

        return reviews

    def run(
        self,
        run_id: str,
        target_ids: Optional[List[str]] = None,
        reviews_content: Optional[str] = None,
        min_score: int = 70,
    ) -> DownloadResult:
        """执行下载与结构化清洗流水线

        Args:
            run_id: 阶段一会话 ID
            target_ids: 直接指定的 Message-ID 列表 (可选)
            reviews_content: AI 评审结果 JSON 字符串 (可选)
            min_score: 最低推荐分数阈值 (默认 70)

        Returns:
            DownloadResult: 包含下载统计、解析后补丁集列表与阶段三提示词路径的结果对象
        """
        run_dir = self.session_manager.get_run_dir(run_id)
        existing_patchsets = self.session_manager.load_patchsets(run_dir)
        patchset_map = {ps.id.strip("<>"): ps for ps in existing_patchsets}
        for ps in existing_patchsets:
            patchset_map[ps.id] = ps

        target_patchsets: List[Patchset] = []
        seen_ids = set()

        # 1. 如果提供了评审结果，进行解析与过滤
        if reviews_content is not None:
            reviews = self._parse_reviews(reviews_content)
            filtered_patchsets: List[Patchset] = []

            for r in reviews:
                # 过滤规则：score >= min_score 或 recommend is True
                if r.score >= min_score or r.recommend is True:
                    clean_id = r.id.strip("<>")
                    ps = patchset_map.get(r.id) or patchset_map.get(clean_id)
                    if not ps:
                        ps = Patchset(
                            id=r.id,
                            title=r.title or r.id,
                            author_name="",
                            author_email="",
                        )
                    if ps.id not in seen_ids:
                        seen_ids.add(ps.id)
                        filtered_patchsets.append(ps)

            self.session_manager.save_reviews(run_dir, reviews, filtered_patchsets)
            target_patchsets.extend(filtered_patchsets)

        # 2. 如果额外/直接指定了 target_ids
        if target_ids:
            for tid in target_ids:
                clean_id = tid.strip("<>")
                ps = patchset_map.get(tid) or patchset_map.get(clean_id)
                if not ps:
                    ps = Patchset(
                        id=tid,
                        title=tid,
                        author_name="",
                        author_email="",
                    )
                if ps.id not in seen_ids:
                    seen_ids.add(ps.id)
                    target_patchsets.append(ps)

        # 3. 逐个调用 b4 下载并解析 mbox
        parsed_patchsets: List[ParsedPatchset] = []
        parsed_paths: List[Path] = []

        for ps in target_patchsets:
            patchset_id = ps.id
            sanitized_id = self.b4_client.sanitize_id(patchset_id)
            patchset_dir = run_dir / "patchsets" / sanitized_id

            try:
                mbox_path = self.b4_client.fetch_thread(
                    patchset_id,
                    patchset_dir,
                    mbox_name="series.mbx",
                )
            except (B4ExecutionError, B4NotFoundError) as e:
                logger.warning("下载 Patchset %s 失败: %s", patchset_id, e)
                continue

            parsed_ps = self.mbox_parser.parse(
                mbox_path,
                patchset_id=patchset_id,
                title=ps.title,
            )
            saved_file = self.session_manager.save_parsed_patchset(
                run_dir,
                sanitized_id,
                parsed_ps,
            )
            parsed_paths.append(saved_file)
            parsed_patchsets.append(parsed_ps)

        # 4. 生成阶段三提示词并持久化
        prompt_content = self.prompt_builder.build_prompt(run_id, parsed_paths)
        stage3_prompt_path = self.session_manager.save_stage3_prompt(run_dir, prompt_content)

        return DownloadResult(
            run_id=run_id,
            run_dir=run_dir,
            downloaded_count=len(parsed_patchsets),
            parsed_patchsets=parsed_patchsets,
            stage3_prompt_path=stage3_prompt_path,
        )
