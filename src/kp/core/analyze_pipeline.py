from __future__ import annotations

import concurrent.futures
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from kp.adapters.agent import BaseAgentRunner, get_agent_runner
from kp.config import AppConfig
from kp.storage.paths import get_clean_id
from kp.models import AnalyzeRunResult, Patchset, PatchsetAnalysis, PatchsetStatus
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
        force: bool = False,
        custom_prompt: Optional[str] = None,
        runner_override: Optional[BaseAgentRunner] = None,
    ) -> AnalyzeRunResult:
        """执行阶段三深度分析流水线

        Args:
            run_id: 运行会话 ID
            target_ids: 指定要分析的 Patchset ID 列表 (可选，默认分析全部已下载补丁集)
            agent_type: 指定调用的外部 Agent 类型 ('agy' 或 'opencode'，可选)
            concurrency: 并发分析数 (可选，默认使用配置值)
            dry_run: 是否仅执行完整性校验而不触发 Agent 调用
            force: 是否强制重新分析已生成报告的补丁集 (默认 False，自动跳过已分析补丁集)
            custom_prompt: 用户附加自定义提示词 (可选)
            runner_override: 自定义 AgentRunner 实例 (用于测试注入)

        Returns:
            AnalyzeRunResult: 包含各补丁集分析状态与报告路径的结果摘要
        """
        run_dir = self.session_manager.get_run_dir(run_id)
        if not run_dir.exists() or not run_dir.is_dir():
            raise FileNotFoundError(f"Session '{run_id}' not found at {run_dir}")

        # 收集该会话中包含的 patchsets 元数据
        session_patchsets: List[Patchset] = []
        for jname in ["filtered_patchsets.json", "patchsets.json"]:
            jfile = run_dir / jname
            if jfile.exists():
                try:
                    data = json.loads(jfile.read_text(encoding="utf-8"))
                    for item in data:
                        session_patchsets.append(Patchset.model_validate(item))
                    if session_patchsets:
                        break
                except Exception:
                    pass

        # 收集已下载目录映射：(patchset_dir, msgid, clean_id, date_str)
        dir_meta_map: List[Tuple[Path, str, str, Optional[str]]] = []

        # 1. 尝试从全局资产库匹配
        for ps in session_patchsets:
            p_dir = self.session_manager.get_patchset_dir(ps.id, ps.date)
            if p_dir.exists() and (p_dir / "meta.json").exists():
                dir_meta_map.append((p_dir, ps.id, get_clean_id(ps.id), ps.date))

        # 2. 兼容检查 run_dir / "patchsets" 目录
        legacy_patchsets_dir = run_dir / "patchsets"
        if legacy_patchsets_dir.exists() and legacy_patchsets_dir.is_dir():
            for p_dir in sorted(legacy_patchsets_dir.iterdir(), key=lambda p: p.name):
                if p_dir.is_dir():
                    meta_file = p_dir / "meta.json"
                    msgid = p_dir.name
                    date_str = None
                    if meta_file.exists():
                        try:
                            meta_dict = json.loads(
                                meta_file.read_text(encoding="utf-8")
                            )
                            if isinstance(meta_dict, dict):
                                msgid = (
                                    meta_dict.get("msgid")
                                    or meta_dict.get("id")
                                    or p_dir.name
                                )
                                date_str = meta_dict.get("date")
                        except Exception:
                            pass
                    clean_id = get_clean_id(str(msgid))
                    if not any(d[2] == clean_id for d in dir_meta_map):
                        dir_meta_map.append((p_dir, str(msgid), clean_id, date_str))

        items_to_process: List[Tuple[Optional[Path], str, str, Optional[str]]] = []

        if target_ids:
            for tid in target_ids:
                clean_tid = get_clean_id(tid)
                matched = False
                for p_dir, msgid, clean_id, date_str in dir_meta_map:
                    if tid in (msgid, clean_id) or clean_tid in (msgid, clean_id):
                        items_to_process.append((p_dir, msgid, clean_id, date_str))
                        matched = True
                        break
                if not matched:
                    items_to_process.append((None, tid, clean_tid, None))
        else:
            items_to_process = dir_meta_map

        if not items_to_process:
            return AnalyzeRunResult(
                run_id=run_id,
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
                    error_message=f"Patchset '{msgid}' not found in session '{run_id}'",
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

            # 优先使用全局 report path，兼容旧 run_dir reports
            report_path = self.session_manager.get_report_path(msgid, date_str)
            legacy_report_path = (
                self.session_manager.get_run_dir(run_id) / "reports" / f"{clean_id}.md"
            )

            actual_report_path = report_path
            if not actual_report_path.exists() and legacy_report_path.exists():
                actual_report_path = legacy_report_path

            if dry_run:
                return PatchsetAnalysis(
                    msgid=msgid,
                    sanitized_id=clean_id,
                    status="skipped",
                    report_path=actual_report_path,
                    duration_seconds=0.0,
                )

            # 检查是否已分析过该补丁集 (如果已存在非空报告且未指定 force，则跳过)
            db_record = self.session_manager.db.get_patchset(clean_id)
            is_already_analyzed = (
                actual_report_path.exists()
                and actual_report_path.stat().st_size > 0
                and (db_record is None or db_record.status == PatchsetStatus.ANALYZED)
            )

            if not force and is_already_analyzed:
                logger.info("[SKIP] Already analyzed: %s", clean_id)
                return PatchsetAnalysis(
                    msgid=msgid,
                    sanitized_id=clean_id,
                    status="skipped",
                    report_path=actual_report_path,
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
        skipped_count = sum(1 for a in analyses if a.status == "skipped")

        return AnalyzeRunResult(
            run_id=run_id,
            analyses=analyses,
            total_count=total_count,
            success_count=success_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
        )
