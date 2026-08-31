from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple
from kp.config import StorageConfig
from kp.models import RawMessage, Patchset, RunManifest, PatchReview, ParsedPatchset
from kp.storage.paths import (
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

    def get_report_path(self, msgid: str, date_str: str | None = None) -> Path:
        return compute_report_path(self.data_dir, msgid, date_str)

    def get_reports_dir(self, run_id: str | None = None) -> Path:
        """返回报告根目录"""
        if run_id:
            # 兼容旧逻辑或返回 run 内部 reports
            r_dir = self.get_run_dir(run_id) / "reports"
            r_dir.mkdir(parents=True, exist_ok=True)
            return r_dir
        reports_dir = self.data_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        return reports_dir

    def list_reports(self, run_id: str | None = None) -> List[Path]:
        """列出报告文件，优先从全局 reports 查找，兼容 run 内部 reports"""
        found_reports: List[Path] = []
        if run_id:
            run_dir = self.get_run_dir(run_id)
            # 检查 run_dir 下是否有 patchsets
            ps_file = run_dir / "patchsets.json"
            if ps_file.exists():
                try:
                    patchsets = self.load_patchsets(run_dir)
                    for ps in patchsets:
                        rpath = self.get_report_path(ps.id, ps.date)
                        if rpath.exists() and rpath.is_file():
                            found_reports.append(rpath)
                except Exception:
                    pass
            # 兼容旧 run_dir/reports 目录
            legacy_dir = run_dir / "reports"
            if legacy_dir.exists():
                found_reports.extend(
                    [p for p in legacy_dir.glob("*.md") if p.is_file()]
                )
            return sorted(list(set(found_reports)))

        # 全局报告列表
        reports_dir = self.data_dir / "reports"
        if not reports_dir.exists():
            return []
        return sorted([p for p in reports_dir.glob("**/*.md") if p.is_file()])

    def get_downloaded_patchset_dirs(self, run_id: str) -> List[Path]:
        """获取指定 run_id 关联的所有已下载且包含 meta.json 的补丁集目录"""
        run_dir = self.get_run_dir(run_id)
        if not run_dir.exists():
            return []

        dirs: List[Path] = []

        # 1. 尝试从 filtered_patchsets.json 或 patchsets.json 中查找
        for json_name in ["filtered_patchsets.json", "patchsets.json"]:
            p_file = run_dir / json_name
            if p_file.exists():
                try:
                    data = json.loads(p_file.read_text(encoding="utf-8"))
                    for item in data:
                        ps = Patchset.model_validate(item)
                        p_dir = self.get_patchset_dir(ps.id, ps.date)
                        if p_dir.exists() and (p_dir / "meta.json").exists():
                            if p_dir not in dirs:
                                dirs.append(p_dir)
                except Exception:
                    pass

        # 2. 兼容旧 run_dir / "patchsets" 目录
        legacy_dir = run_dir / "patchsets"
        if legacy_dir.exists():
            for p in legacy_dir.iterdir():
                if p.is_dir() and (p / "meta.json").exists() and p not in dirs:
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

    def save_reviews(
        self,
        run_dir: Path,
        reviews: List[PatchReview],
        filtered_patchsets: List[Patchset],
    ) -> None:
        reviews_file = run_dir / "reviews.json"
        reviews_list = [r.model_dump() for r in reviews]
        reviews_file.write_text(
            json.dumps(reviews_list, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        filtered_file = run_dir / "filtered_patchsets.json"
        filtered_list = [ps.model_dump() for ps in filtered_patchsets]
        filtered_file.write_text(
            json.dumps(filtered_list, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def save_parsed_patchset(
        self,
        run_dir: Path | None,
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

    def save_stage3_prompt(self, run_dir: Path, prompt_content: str) -> Path:
        prompt_file = run_dir / "stage3_prompt.md"
        prompt_file.write_text(prompt_content, encoding="utf-8")
        return prompt_file
