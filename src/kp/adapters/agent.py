import logging
import shlex
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from kp.config import AgentConfig

logger = logging.getLogger(__name__)


class AgentError(Exception):
    """Base exception for agent adapter errors."""


class AgentNotFoundError(AgentError):
    """Raised when the agent CLI executable cannot be found in PATH."""


class AgentExecutionError(AgentError):
    """Raised when the agent CLI fails or expected report output is missing/empty."""


class AgentTimeoutError(AgentError):
    """Raised when the agent CLI execution exceeds the configured timeout."""


class BaseAgentRunner(ABC):
    """Abstract base class for external AI agent runners."""

    def __init__(self, cmd: str, timeout_seconds: int = 1200) -> None:
        self.cmd = cmd
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    def check_available(self) -> bool:
        """Check if the agent CLI executable is available in PATH."""

    @abstractmethod
    def run_analysis(
        self,
        patchset_dir: Path,
        report_output_path: Path,
        kernel_path: Path | str | None = None,
        skill_name: str = "kernel-patch-analyzer",
        custom_prompt: Optional[str] = None,
    ) -> None:
        """Execute deep technical analysis on patchset using external agent."""


class AgyAgentRunner(BaseAgentRunner):
    """Antigravity CLI (agy) runner adapter."""

    def check_available(self) -> bool:
        return shutil.which(self.cmd) is not None

    def run_analysis(
        self,
        patchset_dir: Path,
        report_output_path: Path,
        kernel_path: Path | str | None = None,
        skill_name: str = "kernel-patch-analyzer",
        custom_prompt: Optional[str] = None,
    ) -> None:
        if not self.check_available():
            raise AgentNotFoundError(
                f"Agent executable '{self.cmd}' not found in PATH."
            )

        if kernel_path:
            base_prompt = (
                f"使用 skill '{skill_name}' 分析补丁集：{patchset_dir.resolve()}，"
                f"Linux 内核代码路径：{kernel_path}，请将生成的深度分析报告写入文件：{report_output_path.resolve()}"
            )
        else:
            base_prompt = (
                f"使用 skill '{skill_name}' 分析补丁集：{patchset_dir.resolve()}，"
                f"请将生成的深度分析报告写入文件：{report_output_path.resolve()}"
            )

        if custom_prompt and custom_prompt.strip():
            prompt = (
                f"{base_prompt}\n\n【用户附加重点关注要求】：\n{custom_prompt.strip()}"
            )
        else:
            prompt = base_prompt

        args = [self.cmd, "--dangerously-skip-permissions", "-p", prompt]
        logger.info("Executing command: %s", shlex.join(args))

        try:
            res = subprocess.run(
                args,
                timeout=self.timeout_seconds,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise AgentTimeoutError(
                f"Agent analysis timed out after {self.timeout_seconds}s"
            ) from e

        if res.returncode != 0:
            raise AgentExecutionError(
                f"Agent failed with exit code {res.returncode}: {res.stderr}"
            )

        if not report_output_path.exists() or report_output_path.stat().st_size == 0:
            raise AgentExecutionError(
                f"Agent finished but report file '{report_output_path}' was not generated."
            )


class OpenCodeAgentRunner(BaseAgentRunner):
    """OpenCode CLI runner adapter."""

    def check_available(self) -> bool:
        return shutil.which(self.cmd) is not None

    def run_analysis(
        self,
        patchset_dir: Path,
        report_output_path: Path,
        kernel_path: Path | str | None = None,
        skill_name: str = "kernel-patch-analyzer",
        custom_prompt: Optional[str] = None,
    ) -> None:
        if not self.check_available():
            raise AgentNotFoundError(
                f"Agent executable '{self.cmd}' not found in PATH."
            )

        if kernel_path:
            base_prompt = (
                f"使用 skill '{skill_name}' 分析补丁集：{patchset_dir.resolve()}，"
                f"Linux 内核代码路径：{kernel_path}，请将生成的深度分析报告写入文件：{report_output_path.resolve()}"
            )
        else:
            base_prompt = (
                f"使用 skill '{skill_name}' 分析补丁集：{patchset_dir.resolve()}，"
                f"请将生成的深度分析报告写入文件：{report_output_path.resolve()}"
            )

        if custom_prompt and custom_prompt.strip():
            prompt = (
                f"{base_prompt}\n\n【用户附加重点关注要求】：\n{custom_prompt.strip()}"
            )
        else:
            prompt = base_prompt

        args = [self.cmd, "run", "--auto", prompt]
        logger.info("Executing command: %s", shlex.join(args))

        try:
            res = subprocess.run(
                args,
                timeout=self.timeout_seconds,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise AgentTimeoutError(
                f"Agent analysis timed out after {self.timeout_seconds}s"
            ) from e

        if res.returncode != 0:
            raise AgentExecutionError(
                f"Agent failed with exit code {res.returncode}: {res.stderr}"
            )

        if not report_output_path.exists() or report_output_path.stat().st_size == 0:
            raise AgentExecutionError(
                f"Agent finished but report file '{report_output_path}' was not generated."
            )


def get_agent_runner(agent_type: str, config: AgentConfig) -> BaseAgentRunner:
    """Factory function to get the appropriate AgentRunner instance."""
    normalized_type = agent_type.lower()
    if normalized_type == "agy":
        return AgyAgentRunner(
            cmd=config.agy_cmd, timeout_seconds=config.timeout_seconds
        )
    elif normalized_type == "opencode":
        return OpenCodeAgentRunner(
            cmd=config.opencode_cmd, timeout_seconds=config.timeout_seconds
        )
    else:
        raise ValueError(
            f"Unsupported agent type: {agent_type}. Supported: 'agy', 'opencode'"
        )
