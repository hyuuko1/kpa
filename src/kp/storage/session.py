from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple
from kp.config import StorageConfig
from kp.models import RawMessage, Patchset, RunManifest, ParsedPatchset
from kp.storage.paths import (
    get_clean_id,
    get_patchset_dir as compute_patchset_dir,
    get_report_path as compute_report_path,
)
from kp.storage.db import DatabaseManager
from kp.core.formatters import (
    render_cover_letter_md,
    render_discussions_md,
    render_patch_file,
    render_meta_json,
    sanitize_filename,
)


class SessionManager:
    """管理运行会话目录、数据库与数据持久化"""

    def __init__(self, config: StorageConfig | Path | str):
        if isinstance(config, (str, Path)):
            self.config = StorageConfig(data_dir=str(config))
        else:
            self.config = config

        self.data_dir = Path(self.config.data_dir)
        self.db = DatabaseManager(self.data_dir / "kp.db")
        self.db.init_tables()

    def create_session_dir(self) -> Tuple[str, Path]:
        runs_base = self.data_dir / "runs"
        runs_base.mkdir(parents=True, exist_ok=True)

        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        run_id = now_str

        run_dir = runs_base / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_id, run_dir

    def create_session(self, run_id: str) -> Path:
        run_dir = self.get_run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def get_run_dir(self, run_id: str) -> Path:
        return self.data_dir / "runs" / run_id

    def get_patchset_dir(self, msgid: str, date_str: str | None = None) -> Path:
        return compute_patchset_dir(self.data_dir, msgid, date_str)

    def find_patchset_dir(self, msgid: str, date_str: str | None = None) -> Path | None:
        """在全局资产库中定位补丁集目录，支持通过 DB 日期或模糊年月查找"""
        clean_id = get_clean_id(msgid)
        # 1. 尝试使用传入的 date_str
        if date_str:
            p = compute_patchset_dir(self.data_dir, msgid, date_str)
            if p.exists():
                return p
        # 2. 尝试从数据库记录中获取 date
        db_rec = self.db.get_patchset(clean_id)
        if db_rec and db_rec.date:
            p = compute_patchset_dir(self.data_dir, msgid, db_rec.date)
            if p.exists():
                return p
        # 3. 扫描 patchsets/ 目录下的所有年月桶
        patchsets_root = self.data_dir / "patchsets"
        if patchsets_root.exists():
            for bucket in patchsets_root.iterdir():
                if bucket.is_dir():
                    target = bucket / clean_id
                    if target.exists() and target.is_dir():
                        return target
        # 4. 回退直接计算路径（即便尚未存在）
        computed = compute_patchset_dir(self.data_dir, msgid, date_str)
        if computed.exists():
            return computed
        return None

    def get_report_path(self, msgid: str, date_str: str | None = None) -> Path:
        return compute_report_path(self.data_dir, msgid, date_str)

    def find_report_path(self, msgid: str, date_str: str | None = None) -> Path:
        """在全局报告库中定位已生成的报告文件，若未找到则返回标准计算路径"""
        clean_id = get_clean_id(msgid)
        if date_str:
            p = compute_report_path(self.data_dir, msgid, date_str)
            if p.exists():
                return p
        db_rec = self.db.get_patchset(clean_id)
        if db_rec and db_rec.date:
            p = compute_report_path(self.data_dir, msgid, db_rec.date)
            if p.exists():
                return p
        reports_root = self.data_dir / "reports"
        if reports_root.exists():
            for bucket in reports_root.iterdir():
                if bucket.is_dir():
                    target = bucket / f"{clean_id}.md"
                    if target.exists() and target.is_file():
                        return target
        return compute_report_path(self.data_dir, msgid, date_str)

    def get_reports_dir(self) -> Path:
        """返回全局报告根目录"""
        reports_dir = self.data_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        return reports_dir

    def list_reports(self) -> List[Path]:
        """列出全局报告库中的所有报告文件"""
        reports_dir = self.data_dir / "reports"
        if not reports_dir.exists():
            return []
        return sorted([p for p in reports_dir.glob("**/*.md") if p.is_file()])

    def get_downloaded_patchset_dirs(self) -> List[Path]:
        """获取全局资产库中所有已下载且包含 meta.json 的补丁集目录"""
        patchsets_root = self.data_dir / "patchsets"
        if not patchsets_root.exists():
            return []
        dirs: List[Path] = []
        for p in patchsets_root.glob("*/*"):
            if p.is_dir() and (p / "meta.json").exists():
                dirs.append(p)
        return sorted(dirs, key=lambda p: p.name)

    def load_patchsets(self, run_dir: Path) -> List[Patchset]:
        patchsets_file = run_dir / "patchsets.json"
        if not patchsets_file.exists():
            raise FileNotFoundError(f"patchsets.json not found in {run_dir}")
        data = json.loads(patchsets_file.read_text(encoding="utf-8"))
        return [Patchset.model_validate(item) for item in data]

    def save_run(
        self,
        run_dir: Path,
        manifest: RunManifest,
        raw_msgs: List[RawMessage],
        patchsets: List[Patchset],
        prompt_content: str | None = None,
    ) -> None:
        # 1. 保存 manifest.json
        manifest_file = run_dir / "manifest.json"
        manifest_file.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        # 2. 保存 raw_metadata.json
        raw_file = run_dir / "raw_metadata.json"
        raw_list = [m.model_dump() for m in raw_msgs]
        raw_file.write_text(
            json.dumps(raw_list, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # 3. 保存 patchsets.json
        patchsets_file = run_dir / "patchsets.json"
        patchsets_list = [ps.model_dump() for ps in patchsets]
        patchsets_file.write_text(
            json.dumps(patchsets_list, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # 4. 保存 prompt.md (可选)
        if prompt_content is not None:
            prompt_file = run_dir / "prompt.md"
            prompt_file.write_text(prompt_content, encoding="utf-8")

    def save_parsed_patchset(
        self,
        sanitized_id: str,
        parsed_patchset: ParsedPatchset,
        date_str: str | None = None,
    ) -> Path:
        """保存拆解后的补丁集到全局资产库 data/patchsets/YYYY-MM/<clean_id>/"""
        if date_str is None:
            if parsed_patchset.cover_letter and parsed_patchset.cover_letter.date:
                date_str = parsed_patchset.cover_letter.date
            elif parsed_patchset.patches and parsed_patchset.patches[0].date:
                date_str = parsed_patchset.patches[0].date

        patchset_dir = self.get_patchset_dir(parsed_patchset.id, date_str)
        patchset_dir.mkdir(parents=True, exist_ok=True)

        # 1. 保存全量 parsed_series.json
        parsed_file = patchset_dir / "parsed_series.json"
        parsed_file.write_text(
            parsed_patchset.model_dump_json(indent=2), encoding="utf-8"
        )

        # 2. 保存轻量元数据 meta.json
        meta_file = patchset_dir / "meta.json"
        meta_dict = render_meta_json(parsed_patchset)
        meta_file.write_text(
            json.dumps(meta_dict, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # 3. 保存直读 00-cover-letter.md（若存在 Cover Letter）
        if parsed_patchset.cover_letter:
            cover_file = patchset_dir / "00-cover-letter.md"
            cover_file.write_text(
                render_cover_letter_md(parsed_patchset.cover_letter), encoding="utf-8"
            )

        # 4. 保存直读 discussions.md（若存在讨论）
        if parsed_patchset.general_comments or any(
            p.comments for p in parsed_patchset.patches
        ):
            disc_file = patchset_dir / "discussions.md"
            disc_file.write_text(
                render_discussions_md(parsed_patchset), encoding="utf-8"
            )

        # 5. 保存独立 patches/ 目录
        if parsed_patchset.patches:
            patches_dir = patchset_dir / "patches"
            patches_dir.mkdir(parents=True, exist_ok=True)
            for patch in parsed_patchset.patches:
                patch_clean_title = sanitize_filename(patch.subject, max_len=40)
                patch_fname = f"{patch.index:04d}-{patch_clean_title}.patch"
                patch_fpath = patches_dir / patch_fname
                patch_fpath.write_text(render_patch_file(patch), encoding="utf-8")

        return parsed_file
