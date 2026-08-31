from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

from kp.adapters.b4 import B4Client, B4ExecutionError, B4NotFoundError
from kp.config import AppConfig
from kp.core.parser import MboxParser
from kp.models import ParsedPatchset, PatchReview, Patchset, PatchsetStatus
from kp.storage.session import SessionManager
from kp.storage.paths import get_clean_id

logger = logging.getLogger(__name__)


class DownloadResult(BaseModel):
    """阶段二下载与解析流水线执行结果"""

    run_id: str
    run_dir: Path
    downloaded_count: int
    parsed_patchsets: List[ParsedPatchset] = Field(default_factory=list)


DownloadRunResult = DownloadResult


class DownloadPipeline:
    """阶段二核心业务流水线：Reviews过滤 / 指定ID -> B4拉取 -> MboxParser清洗 -> SessionStorage持久化 + SQLite状态更新"""

    def __init__(
        self,
        config: AppConfig,
        b4_client: Optional[B4Client] = None,
        session_manager: Optional[SessionManager] = None,
        mbox_parser: Optional[MboxParser] = None,
    ):
        self.config = config
        self.b4_client = b4_client or B4Client(config.b4)
        self.session_manager = session_manager or SessionManager(config.storage)
        self.mbox_parser = mbox_parser or MboxParser()

    def _parse_reviews(self, reviews_content: str) -> List[PatchReview]:
        """解析并校验 AI 评审结果 JSON 字符串 (0-10 分制)"""
        text = reviews_content.strip()
        # 处理可能包含的 Markdown 代码块包裹 (如 ```json ... ```)，即使存在前导对话文本
        if "```" in text:
            start_idx = text.find("```")
            end_idx = text.rfind("```")
            if end_idx > start_idx:
                inner = text[start_idx + 3 : end_idx].strip()
            else:
                inner = text[start_idx + 3 :].strip()

            lines = inner.splitlines()
            if lines and lines[0].strip().lower() in (
                "json",
                "jsonc",
                "javascript",
                "js",
                "text",
            ):
                inner = "\n".join(lines[1:]).strip()
            elif (
                lines and not lines[0].strip().startswith(("{", "[")) and len(lines) > 1
            ):
                inner = "\n".join(lines[1:]).strip()
            text = inner

        try:
            raw_data = json.loads(text)
        except Exception as e:
            raise ValueError(f"解析 AI 评审结果 JSON 失败: {e}") from e

        if (
            isinstance(raw_data, dict)
            and "reviews" in raw_data
            and isinstance(raw_data["reviews"], list)
        ):
            items = raw_data["reviews"]
        elif isinstance(raw_data, list):
            items = raw_data
        else:
            raise ValueError(
                "AI 评审结果 JSON 格式不符合规范：必须为评审列表或包含 'reviews' 键的字典"
            )

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
        min_score: int = 7,
        force: bool = False,
    ) -> DownloadRunResult:
        """执行下载与结构化清洗流水线

        Args:
            run_id: 阶段一会话 ID
            target_ids: 直接指定的 Message-ID 列表 (可选)
            reviews_content: AI 评审结果 JSON 字符串 (可选)
            min_score: 最低推荐分数阈值 (默认 7，基于 0-10 分制)
            force: 是否强制重新下载即使已是最新

        Returns:
            DownloadRunResult: 包含下载统计与解析后补丁集列表的结果对象
        """
        run_dir = self.session_manager.get_run_dir(run_id)
        existing_patchsets = self.session_manager.load_patchsets(run_dir)
        patchset_map = {get_clean_id(ps.id): ps for ps in existing_patchsets}
        for ps in existing_patchsets:
            patchset_map[ps.id] = ps

        target_patchsets: List[Patchset] = []
        seen_ids = set()

        # 1. 如果提供了评审结果，进行解析与过滤
        if reviews_content is not None:
            reviews = self._parse_reviews(reviews_content)
            filtered_patchsets: List[Patchset] = []

            for r in reviews:
                clean_id = get_clean_id(r.id)
                # 更新 SQLite 中的评分
                self.session_manager.db.update_patchset_review(
                    clean_id, r.score, r.recommend, r.reason
                )

                # 过滤规则：score >= min_score 或 recommend is True
                if r.score >= min_score or r.recommend is True:
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
                clean_id = get_clean_id(tid)
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

        # 3. 逐个增量检查并调用 b4 下载与解析 mbox
        parsed_patchsets: List[ParsedPatchset] = []

        for ps in target_patchsets:
            patchset_id = ps.id
            clean_id = get_clean_id(patchset_id)
            db_record = self.session_manager.db.get_patchset(clean_id)

            latest_msg_date = ps.date
            # 增量检查：无 force 且已下载过，且邮件日期不新于已下载时间 -> 跳过
            if not force and db_record and db_record.downloaded_at:
                if latest_msg_date and latest_msg_date <= db_record.downloaded_at:
                    logger.info(
                        "[SKIP] Patchset %s is up-to-date (downloaded at %s)",
                        clean_id,
                        db_record.downloaded_at,
                    )
                    continue

            patchset_dir = self.session_manager.get_patchset_dir(ps.id, ps.date)

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
            self.session_manager.save_parsed_patchset(
                run_dir,
                clean_id,
                parsed_ps,
                date_str=ps.date,
            )

            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            report_path = self.session_manager.get_report_path(ps.id, ps.date)

            # 状态流转规则：若原 status 为 ANALYZED 且报告非空存在，保持 ANALYZED，不降级为 DOWNLOADED
            if (
                db_record
                and db_record.status == PatchsetStatus.ANALYZED
                and report_path.exists()
                and report_path.stat().st_size > 0
            ):
                self.session_manager.db.update_patchset_status(
                    clean_id, PatchsetStatus.ANALYZED, downloaded_at=now_iso
                )
                logger.info(
                    "[UPDATED] Downloaded new replies for analyzed patchset %s. Discussions updated at %s",
                    clean_id,
                    patchset_dir,
                )
            else:
                self.session_manager.db.update_patchset_status(
                    clean_id, PatchsetStatus.DOWNLOADED, downloaded_at=now_iso
                )

            parsed_patchsets.append(parsed_ps)

        return DownloadRunResult(
            run_id=run_id,
            run_dir=run_dir,
            downloaded_count=len(parsed_patchsets),
            parsed_patchsets=parsed_patchsets,
        )
