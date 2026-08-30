from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple
from kp.config import StorageConfig
from kp.models import RawMessage, Patchset, RunManifest


class SessionManager:
    """管理运行会话目录与数据持久化"""

    def __init__(self, config: StorageConfig):
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
        raw_file.write_text(json.dumps(raw_list, indent=2, ensure_ascii=False), encoding="utf-8")

        # 3. 保存 patchsets.json
        patchsets_file = run_dir / "patchsets.json"
        patchsets_list = [ps.model_dump() for ps in patchsets]
        patchsets_file.write_text(json.dumps(patchsets_list, indent=2, ensure_ascii=False), encoding="utf-8")

        # 4. 保存 prompt.md
        prompt_file = run_dir / "prompt.md"
        prompt_file.write_text(prompt_content, encoding="utf-8")
