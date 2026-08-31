from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional
from kp.config import B4Config


class B4NotFoundError(Exception):
    """系统环境中未找到 b4 工具"""

    pass


class B4ExecutionError(Exception):
    """调用 b4 执行失败"""

    pass


class B4Client:
    """与 b4 CLI 交互的适配器客户端"""

    def __init__(self, config: Optional[B4Config] = None):
        self.config = config or B4Config()

    @staticmethod
    def sanitize_id(msgid: str) -> str:
        """将 Message-ID 安全化为可作为合法文件系统路径的字符串"""
        s = msgid.strip()
        if s.startswith("<") and s.endswith(">"):
            s = s[1:-1]
        s = re.sub(r"[^\w.-]+", "_", s)
        return s.strip("._") or "unknown_patchset"

    def fetch_thread(
        self,
        msgid: str,
        output_dir: Path,
        mbox_name: str = "series.mbx",
    ) -> Path:
        """调用 b4 mbox 下载指定 msgid 的完整邮件线程 mbox 文件

        Args:
            msgid: 目标邮件 Message-ID
            output_dir: 目标保存目录
            mbox_name: 目标 mbox 文件名 (默认为 series.mbx)

        Returns:
            Path: 生成的 mbox 文件绝对路径

        Raises:
            B4NotFoundError: 系统中未找到 b4 工具
            B4ExecutionError: b4 执行失败、超时或未生成目标文件
        """
        b4_bin = shutil.which("b4")
        if not b4_bin:
            raise B4NotFoundError("系统环境中未找到 b4 工具，请确保已正确安装 b4")

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        target_file = out_dir / mbox_name

        cmd = [
            b4_bin,
            "mbox",
            "-o",
            str(out_dir),
        ]
        if mbox_name:
            cmd.extend(["-n", mbox_name])
        cmd.append(msgid)

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise B4ExecutionError(
                f"b4 mbox 超时 ({self.config.timeout_seconds}s): {e}"
            ) from e
        except Exception as e:
            raise B4ExecutionError(f"执行 b4 mbox 失败: {e}") from e

        if res.returncode != 0:
            raise B4ExecutionError(
                f"b4 mbox failed (code {res.returncode}): {res.stderr.strip()}"
            )

        if not target_file.exists():
            raise B4ExecutionError(f"b4 mbox failed: 未生成目标文件 {target_file}")

        return target_file
