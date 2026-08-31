from __future__ import annotations

import concurrent.futures
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from kp.adapters.agent import BaseAgentRunner, get_agent_runner
from kp.config import AppConfig
from kp.core.formatters import sanitize_filename
from kp.models import AnalyzeRunResult, PatchsetAnalysis
from kp.storage.session import SessionManager

logger = logging.getLogger(__name__)


class AnalyzePipeline:
    """阶段三核心流水线：会话校验 -> 直读文件完整性检查 -> Agent 分析分发与并发执行 -> 独立报告持久化"""

    def __init__(
        self,
        config: AppConfig,
        session_manager: Optional[SessionManager] = None,
    ) -> None:
        self.config = config
        self.session_manager = session_manager or SessionManager(config.storage)

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
        run_id: str,
        target_ids: Optional[List[str]] = None,
        agent_type: Optional[str] = None,
        concurrency: Optional[int] = None,
        dry_run: bool = False,
        runner_override: Optional[BaseAgentRunner] = None,
    ) -> AnalyzeRunResult:
        """执行阶段三深度分析流水线

        Args:
            run_id: 运行会话 ID
            target_ids: 指定要分析的 Patchset ID 列表 (可选，默认分析全部已下载补丁集)
            agent_type: 指定调用的外部 Agent 类型 ('agy' 或 'opencode'，可选)
            concurrency: 并发分析数 (可选，默认使用配置值)
            dry_run: 是否仅执行完整性校验而不触发 Agent 调用
            runner_override: 自定义 AgentRunner 实例 (用于测试注入)

        Returns:
            AnalyzeRunResult: 包含各补丁集分析状态与报告路径的结果摘要
        """
        run_dir = self.session_manager.get_run_dir(run_id)
        if not run_dir.exists() or not run_dir.is_dir():
            raise FileNotFoundError(f"Session '{run_id}' not found at {run_dir}")

        patchsets_dir = run_dir / "patchsets"
        downloaded_dirs: List[Path] = []
        if patchsets_dir.exists() and patchsets_dir.is_dir():
            downloaded_dirs = sorted(
                [p for p in patchsets_dir.iterdir() if p.is_dir()],
                key=lambda p: p.name,
            )

        # 建立目录映射以便 target_ids 过滤
        dir_meta_map: List[Tuple[Path, str, str]] = []
        for p_dir in downloaded_dirs:
            meta_file = p_dir / "meta.json"
            msgid = p_dir.name
            if meta_file.exists():
                try:
                    meta_dict = json.loads(meta_file.read_text(encoding="utf-8"))
                    if isinstance(meta_dict, dict):
                        msgid = (
                            meta_dict.get("msgid") or meta_dict.get("id") or p_dir.name
                        )
                except Exception:
                    pass
            dir_meta_map.append((p_dir, str(msgid), p_dir.name))

        items_to_process: List[Tuple[Optional[Path], str, str]] = []

        if target_ids:
            for tid in target_ids:
                clean_tid = tid.strip("<>")
                matched = False
                for p_dir, msgid, sanitized_id in dir_meta_map:
                    clean_msgid = msgid.strip("<>")
                    if tid in (msgid, clean_msgid, sanitized_id) or clean_tid in (
                        msgid,
                        clean_msgid,
                        sanitized_id,
                    ):
                        items_to_process.append((p_dir, msgid, sanitized_id))
                        matched = True
                        break
                if not matched:
                    items_to_process.append(
                        (None, tid, sanitize_filename(clean_tid) or clean_tid)
                    )
        else:
            items_to_process = [
                (p_dir, msgid, sanitized_id)
                for p_dir, msgid, sanitized_id in dir_meta_map
            ]

        if not items_to_process:
            return AnalyzeRunResult(
                run_id=run_id,
                analyses=[],
                total_count=0,
                success_count=0,
                failed_count=0,
            )

        runner: Optional[BaseAgentRunner] = None
        if not dry_run:
            runner = runner_override or get_agent_runner(
                agent_type or self.config.agent.default,
                self.config.agent,
            )

        def _process_item(item: Tuple[Optional[Path], str, str]) -> PatchsetAnalysis:
            p_dir, msgid, sanitized_id = item
            if p_dir is None:
                return PatchsetAnalysis(
                    msgid=msgid,
                    sanitized_id=sanitized_id,
                    status="failed",
                    error_message=f"Patchset '{msgid}' not found in session '{run_id}'",
                    duration_seconds=0.0,
                )

            is_valid, err_msg, _ = self._verify_patchset_integrity(p_dir)
            if not is_valid:
                return PatchsetAnalysis(
                    msgid=msgid,
                    sanitized_id=sanitized_id,
                    status="failed",
                    error_message=err_msg,
                    duration_seconds=0.0,
                )

            report_path = self.session_manager.get_report_path(run_id, sanitized_id)

            if dry_run:
                return PatchsetAnalysis(
                    msgid=msgid,
                    sanitized_id=sanitized_id,
                    status="skipped",
                    report_path=report_path,
                    duration_seconds=0.0,
                )

            report_path.parent.mkdir(parents=True, exist_ok=True)
            t0 = time.time()
            try:
                assert runner is not None
                runner.run_analysis(p_dir, report_path)
                duration = round(time.time() - t0, 3)
                return PatchsetAnalysis(
                    msgid=msgid,
                    sanitized_id=sanitized_id,
                    status="success",
                    report_path=report_path,
                    duration_seconds=duration,
                )
            except Exception as e:
                duration = round(time.time() - t0, 3)
                logger.error("Analysis for patchset %s failed: %s", sanitized_id, e)
                return PatchsetAnalysis(
                    msgid=msgid,
                    sanitized_id=sanitized_id,
                    status="failed",
                    error_message=str(e),
                    duration_seconds=duration,
                )

        worker_count = (
            concurrency if concurrency is not None else self.config.agent.concurrency
        )
        if worker_count is None or worker_count < 1:
            worker_count = 1

        if worker_count > 1 and len(items_to_process) > 1 and not dry_run:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=worker_count
            ) as executor:
                analyses = list(executor.map(_process_item, items_to_process))
        else:
            analyses = [_process_item(item) for item in items_to_process]

        total_count = len(analyses)
        success_count = sum(1 for a in analyses if a.status == "success")
        failed_count = sum(1 for a in analyses if a.status == "failed")

        return AnalyzeRunResult(
            run_id=run_id,
            analyses=analyses,
            total_count=total_count,
            success_count=success_count,
            failed_count=failed_count,
        )
