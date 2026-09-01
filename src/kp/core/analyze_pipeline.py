from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from kp.adapters.agent import BaseAgentRunner, get_agent_runner
from kp.config import AppConfig
from kp.core.parser import parse_reviews
from kp.storage.paths import get_clean_id
from kp.models import (
    AnalyzeRunResult,
    PatchsetAnalysis,
    PatchsetStatus,
)
from kp.storage.session import SessionManager

logger = logging.getLogger(__name__)


class AnalyzePipeline:
    """阶段三核心流水线：会话校验 -> 直读文件完整性检查 -> Agent 分析分发与并发执行 -> 独立报告持久化 + SQLite状态同步"""

    def __init__(
        self,
        config: AppConfig,
        session_manager: Optional[SessionManager] = None,
    ) -> None:
        self.config = config
        self.session_manager = session_manager or SessionManager(config.storage)

    _parse_reviews = staticmethod(parse_reviews)

    def _verify_patchset_integrity(
        self, patchset_dir: Path
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """校验待分析补丁集直读文件完整性 (meta.json, 00-cover-letter.md, patches/)"""
        meta_file = patchset_dir / "meta.json"
        if not meta_file.exists():
            return False, f"Missing meta.json in {patchset_dir}", None

        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception as e:
            return False, f"Corrupted meta.json in {patchset_dir}: {e}", None

        if not isinstance(meta, dict):
            return False, f"Invalid meta.json format in {patchset_dir}", None

        # 检查 Cover Letter 是否如元数据声明那样存在
        if meta.get("has_cover_letter") is True:
            cover_file = patchset_dir / "00-cover-letter.md"
            if not cover_file.is_file():
                return False, f"Missing 00-cover-letter.md in {patchset_dir}", meta

        # 检查 patches 目录与补丁文件
        patches = meta.get("patches")
        if isinstance(patches, list) and len(patches) > 0:
            patches_dir = patchset_dir / "patches"
            if not patches_dir.is_dir():
                return False, f"Missing patches directory in {patchset_dir}", meta

        return True, None, meta

    def run(
        self,
        target_ids: Optional[List[str]] = None,
        reviews_content: Optional[str] = None,
        min_score: int = 7,
        agent_type: Optional[str] = None,
        concurrency: Optional[int] = None,
        dry_run: bool = False,
        force: bool = False,
        custom_prompt: Optional[str] = None,
        runner_override: Optional[BaseAgentRunner] = None,
    ) -> AnalyzeRunResult:
        """执行阶段三深度分析流水线

        Args:
            target_ids: 指定要分析的 Patchset ID 列表 (可选)
            reviews_content: AI 评审结果 JSON 字符串 (可选)
            min_score: 最低推荐分数阈值 (默认 7，基于 0-10 分制)
            agent_type: 指定调用的外部 Agent 类型 ('agy' 或 'opencode'，可选)
            concurrency: 并发分析数 (可选，默认使用配置值)
            dry_run: 是否仅执行完整性校验而不触发 Agent 调用
            force: 是否强制重新分析已生成报告的补丁集 (默认 False，自动跳过已分析补丁集)
            custom_prompt: 用户附加自定义提示词 (可选)
            runner_override: 自定义 AgentRunner 实例 (用于测试注入)

        Returns:
            AnalyzeRunResult: 包含各补丁集分析状态与报告路径的结果摘要
        """
        items_to_process: List[Tuple[Optional[Path], str, str, Optional[str]]] = []
        seen_clean_ids = set()

        # 1. 如果提供了评审结果，进行解析与过滤
        if reviews_content is not None:
            reviews = self._parse_reviews(reviews_content)
            for r in reviews:
                clean_id = get_clean_id(r.id)
                self.session_manager.db.update_patchset_review(
                    clean_id, r.score, r.recommend, r.reason
                )
                if r.score >= min_score or r.recommend is True:
                    if clean_id not in seen_clean_ids:
                        seen_clean_ids.add(clean_id)
                        db_rec = self.session_manager.db.get_patchset(clean_id)
                        date_str = db_rec.date if db_rec else None
                        p_dir = self.session_manager.find_patchset_dir(r.id, date_str)
                        items_to_process.append((p_dir, r.id, clean_id, date_str))

        # 2. 如果指定了 target_ids
        if target_ids:
            for tid in target_ids:
                clean_id = get_clean_id(tid)
                if clean_id not in seen_clean_ids:
                    seen_clean_ids.add(clean_id)
                    db_rec = self.session_manager.db.get_patchset(clean_id)
                    date_str = db_rec.date if db_rec else None
                    p_dir = self.session_manager.find_patchset_dir(tid, date_str)
                    items_to_process.append((p_dir, tid, clean_id, date_str))

        if not items_to_process:
            return AnalyzeRunResult(
                analyses=[],
                total_count=0,
                success_count=0,
                failed_count=0,
                skipped_count=0,
            )

        runner: Optional[BaseAgentRunner] = None
        kernel_path: Optional[str] = None
        if not dry_run:
            kernel_path = (
                self.config.kernel.path if self.config.kernel is not None else None
            )
            if not kernel_path or not str(kernel_path).strip():
                raise ValueError(
                    "未配置 Linux 内核代码路径，请在配置文件中设置 [kernel].path"
                )
            runner = runner_override or get_agent_runner(
                agent_type or self.config.agent.default,
                self.config.agent,
            )

        def _process_item(
            item: Tuple[Optional[Path], str, str, Optional[str]],
        ) -> PatchsetAnalysis:
            p_dir, msgid, clean_id, date_str = item
            if p_dir is None:
                return PatchsetAnalysis(
                    msgid=msgid,
                    sanitized_id=clean_id,
                    status="failed",
                    error_message=f"Patchset '{msgid}' not found or not downloaded yet. Run 'kp download' first.",
                    duration_seconds=0.0,
                )

            is_valid, err_msg, meta = self._verify_patchset_integrity(p_dir)
            if not is_valid:
                return PatchsetAnalysis(
                    msgid=msgid,
                    sanitized_id=clean_id,
                    status="failed",
                    error_message=err_msg,
                    duration_seconds=0.0,
                )

            report_path = self.session_manager.find_report_path(msgid, date_str)

            if dry_run:
                return PatchsetAnalysis(
                    msgid=msgid,
                    sanitized_id=clean_id,
                    status="skipped",
                    report_path=report_path,
                    duration_seconds=0.0,
                )

            # 检查是否已分析过该补丁集 (如果已存在非空报告且未指定 force，则跳过)
            db_record = self.session_manager.db.get_patchset(clean_id)
            is_already_analyzed = (
                report_path.exists()
                and report_path.stat().st_size > 0
                and (db_record is None or db_record.status == PatchsetStatus.ANALYZED)
            )

            if not force and is_already_analyzed:
                logger.info("[SKIP] Already analyzed: %s", clean_id)
                return PatchsetAnalysis(
                    msgid=msgid,
                    sanitized_id=clean_id,
                    status="skipped",
                    report_path=report_path,
                    error_message="Already analyzed",
                    duration_seconds=0.0,
                )

            report_path.parent.mkdir(parents=True, exist_ok=True)
            t0 = time.time()
            try:
                assert runner is not None
                runner.run_analysis(
                    p_dir,
                    report_path,
                    kernel_path=kernel_path,
                    custom_prompt=custom_prompt,
                )
                duration = round(time.time() - t0, 3)

                # 更新 SQLite 数据库状态为 analyzed
                self.session_manager.db.update_patchset_status(
                    clean_id, PatchsetStatus.ANALYZED
                )

                return PatchsetAnalysis(
                    msgid=msgid,
                    sanitized_id=clean_id,
                    status="success",
                    report_path=report_path,
                    duration_seconds=duration,
                )
            except Exception as e:
                duration = round(time.time() - t0, 3)
                logger.error("Analysis for patchset %s failed: %s", clean_id, e)
                return PatchsetAnalysis(
                    msgid=msgid,
                    sanitized_id=clean_id,
                    status="failed",
                    error_message=str(e),
                    duration_seconds=duration,
                )

        max_workers = concurrency or self.config.agent.concurrency
        results: List[PatchsetAnalysis] = []

        if len(items_to_process) <= 1 or max_workers <= 1:
            for item in items_to_process:
                results.append(_process_item(item))
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_item = {
                    executor.submit(_process_item, item): item
                    for item in items_to_process
                }
                for future in as_completed(future_to_item):
                    results.append(future.result())

        # 按初始顺序排序
        clean_id_order = {item[2]: idx for idx, item in enumerate(items_to_process)}
        results.sort(key=lambda a: clean_id_order.get(a.sanitized_id, 0))

        success_cnt = sum(1 for r in results if r.status == "success")
        failed_cnt = sum(1 for r in results if r.status == "failed")
        skipped_cnt = sum(1 for r in results if r.status == "skipped")

        return AnalyzeRunResult(
            analyses=results,
            total_count=len(results),
            success_count=success_cnt,
            failed_count=failed_cnt,
            skipped_count=skipped_cnt,
        )
