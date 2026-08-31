from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple
from kp.config import StorageConfig
from kp.models import RawMessage, Patchset, RunManifest, PatchReview, ParsedPatchset
from kp.core.formatters import (
    render_cover_letter_md,
    render_discussions_md,
    render_patch_file,
    render_meta_json,
    sanitize_filename,
)


class SessionManager:
    """管理运行会话目录与数据持久化"""

    def __init__(self, config: StorageConfig | Path | str):
        if isinstance(config, (str, Path)):
            self.config = StorageConfig(data_dir=str(config))
        else:
            self.config = config

    def create_session_dir(self) -> Tuple[str, Path]:
        base_dir = Path(self.config.data_dir)
        base_dir.mkdir(parents=True, exist_ok=True)

        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rand_str = uuid.uuid4().hex[:6]
        run_id = f"{now_str}_{rand_str}"

        run_dir = base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_id, run_dir

    def create_session(self, run_id: str) -> Path:
        run_dir = self.get_run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def get_run_dir(self, run_id: str) -> Path:
        base_dir = Path(self.config.data_dir)
        return base_dir / run_id

    def get_reports_dir(self, run_id: str) -> Path:
        reports_dir = self.get_run_dir(run_id) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        return reports_dir

    def get_report_path(self, run_id: str, sanitized_id: str) -> Path:
        return self.get_run_dir(run_id) / "reports" / f"{sanitized_id}.md"

    def list_reports(self, run_id: str) -> List[Path]:
        reports_dir = self.get_run_dir(run_id) / "reports"
        if not reports_dir.exists():
            return []
        return sorted([p for p in reports_dir.glob("*.md") if p.is_file()])

    def get_downloaded_patchset_dirs(self, run_id: str) -> List[Path]:
        patchsets_dir = self.get_run_dir(run_id) / "patchsets"
        if not patchsets_dir.exists():
            return []
        return sorted(
            [
                p
                for p in patchsets_dir.iterdir()
                if p.is_dir() and (p / "meta.json").exists()
            ],
            key=lambda p: p.name,
        )

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
        prompt_content: str,
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

        # 4. 保存 prompt.md
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
        run_dir: Path,
        sanitized_id: str,
        parsed_patchset: ParsedPatchset,
    ) -> Path:
        patchset_dir = run_dir / "patchsets" / sanitized_id
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
