from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple
import click
from kp.config import load_config
from kp.adapters.lore import SafetyValidationError, LoreExecutionError
from kp.adapters.b4 import B4ExecutionError, B4NotFoundError
from kp.adapters.agent import AgentError
from kp.core.pipeline import FetchPipeline
from kp.core.download_pipeline import DownloadPipeline
from kp.core.analyze_pipeline import AnalyzePipeline


@click.group()
@click.option(
    "-c",
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="指定配置文件路径",
)
@click.pass_context
def main(ctx: click.Context, config_path: Path | None) -> None:
    """Linux Kernel Patch Fetcher & AI Analyzer (kp)"""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config_path)


@main.command(name="fetch")
@click.option(
    "-q",
    "--query",
    required=True,
    help='lei 查询语句 (与 lei q 一致，如 "l:linux-mm.kvack.org AND NOT s:Re AND d:2.hours.ago..")',
)
@click.option(
    "--since-last",
    is_flag=True,
    help="增量巡检模式：自动对齐上次同步游标，支持超大跨度自适应分批 (Auto-chunking)",
)
@click.pass_context
def fetch_cmd(ctx: click.Context, query: str, since_last: bool) -> None:
    """阶段一：抓取补丁元数据、清洗聚合并持久化"""
    app_config = ctx.obj["config"]
    pipeline = FetchPipeline(app_config)

    try:
        if since_last:
            click.echo(f"[*] 执行增量巡检查询 (--since-last): {query}")
        else:
            click.echo(f"[*] 执行查询: {query}")

        result = pipeline.run(query, since_last=since_last)
        click.secho("[✓] 抓取完成！", fg="green", bold=True)
        click.echo(f"    - 运行 ID: {result.run_id}")
        click.echo(f"    - 原始邮件数: {result.raw_count}")
        click.echo(f"    - 聚合 Patchset 数: {result.patchset_count}")
        click.echo(f"    - 会话目录: {result.run_dir.resolve()}")
        click.secho(
            f"\n[提示] 可使用 skill 'kernel-patch-analyzer' 进行补丁初筛与打分 (0-10分制，输出 reviews.json)，或直接执行 kp download --run-id {result.run_id} --id <target_id>。",
            fg="cyan",
        )
    except SafetyValidationError as e:
        click.secho(f"[错误] {e}", fg="red", err=True)
        sys.exit(1)
    except LoreExecutionError as e:
        click.secho(f"[错误] {e}", fg="red", err=True)
        sys.exit(1)
    except Exception as e:
        click.secho(f"[异常] 未知错误: {e}", fg="red", err=True)
        sys.exit(1)


@main.command(name="download")
@click.option(
    "--run-id",
    required=True,
    help="指定阶段一运行会话 ID (run_id)",
)
@click.option(
    "--id",
    "target_ids",
    multiple=True,
    help="指定要下载的 Patchset ID (可多次指定以包含多个补丁集)",
)
@click.option(
    "-i",
    "--input",
    "input_file",
    type=click.Path(allow_dash=True, dir_okay=False),
    help="AI 评审结果 JSON 文件路径或 - (从标准输入读取)",
)
@click.option(
    "--min-score",
    default=7,
    type=click.IntRange(0, 10),
    show_default=True,
    help="最低评分过滤阈值 (0-10分制，低于该分数的补丁集将被过滤，除非 recommend=true)",
)
@click.option(
    "--force",
    is_flag=True,
    help="强制重新下载即使本地已是最新",
)
@click.pass_context
def download_cmd(
    ctx: click.Context,
    run_id: str,
    target_ids: Tuple[str, ...],
    input_file: str | None,
    min_score: int,
    force: bool,
) -> None:
    """阶段二：下载选定补丁完整邮件线索、结构化解析并生成全局直读文件"""
    if not target_ids and not input_file:
        click.secho(
            "[错误] 请至少指定 --id 或 --input 参数以选择要下载的补丁集",
            fg="red",
            err=True,
        )
        sys.exit(1)

    reviews_content: str | None = None
    if input_file is not None:
        if input_file == "-":
            reviews_content = sys.stdin.read()
        else:
            p = Path(input_file)
            if not p.exists():
                click.secho(
                    f"[错误] 评审结果文件不存在: {input_file}", fg="red", err=True
                )
                sys.exit(1)
            reviews_content = p.read_text(encoding="utf-8")

    app_config = ctx.obj["config"]
    pipeline = DownloadPipeline(app_config)

    try:
        click.echo(f"[*] 开始执行阶段二流水线 (Run ID: {run_id})...")
        result = pipeline.run(
            run_id=run_id,
            target_ids=list(target_ids) if target_ids else None,
            reviews_content=reviews_content,
            min_score=min_score,
            force=force,
        )
        click.secho("[✓] 下载与结构化解析完成！", fg="green", bold=True)
        click.echo(f"    - 运行 ID: {result.run_id}")
        click.echo(f"    - 成功下载并解析 Patchset 数: {result.downloaded_count}")
        click.echo(f"    - 会话目录: {result.run_dir.resolve()}")
        click.secho(
            f"\n[提示] 可执行 kp analyze --run-id {result.run_id} 启动 AI 深度技术分析与报告生成 (阶段三)。",
            fg="cyan",
        )
    except FileNotFoundError as e:
        click.secho(f"[错误] 会话或文件不存在: {e}", fg="red", err=True)
        sys.exit(1)
    except ValueError as e:
        click.secho(f"[错误] {e}", fg="red", err=True)
        sys.exit(1)
    except (B4ExecutionError, B4NotFoundError) as e:
        click.secho(f"[错误] {e}", fg="red", err=True)
        sys.exit(1)
    except Exception as e:
        click.secho(f"[异常] 未知错误: {e}", fg="red", err=True)
        sys.exit(1)


@main.command(name="analyze")
@click.option(
    "--run-id",
    required=True,
    help="指定运行会话 ID (run_id)",
)
@click.option(
    "--id",
    "target_ids",
    multiple=True,
    help="指定要分析的 Patchset ID (可多次指定以包含多个补丁集，默认分析全量已下载补丁集)",
)
@click.option(
    "--agent",
    type=click.Choice(["agy", "opencode"], case_sensitive=False),
    default=None,
    help="指定调用的 AI Agent 类型 ('agy' 或 'opencode')",
)
@click.option(
    "--concurrency",
    type=int,
    default=None,
    help="并发分析数 (默认使用配置文件设置)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="仅检查待分析补丁集完整性，不触发 Agent 调用",
)
@click.option(
    "--force",
    is_flag=True,
    help="强制重新分析已生成报告的补丁集 (默认自动跳过已分析的补丁集)",
)
@click.option(
    "-p",
    "--prompt",
    "custom_prompt",
    type=str,
    default=None,
    help="追加自定义重点关注提示词 (将附加在 Agent 分析指令末尾)",
)
@click.option(
    "--prompt-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="从文本文件读取追加自定义提示词",
)
@click.pass_context
def analyze_cmd(
    ctx: click.Context,
    run_id: str,
    target_ids: Tuple[str, ...],
    agent: str | None,
    concurrency: int | None,
    dry_run: bool,
    force: bool,
    custom_prompt: str | None,
    prompt_file: Path | None,
) -> None:
    """阶段三：调用外部 AI Agent 进行深度代码与架构分析并生成独立报告"""
    if prompt_file is not None:
        file_prompt = prompt_file.read_text(encoding="utf-8").strip()
        if custom_prompt:
            custom_prompt = f"{custom_prompt}\n\n{file_prompt}"
        else:
            custom_prompt = file_prompt

    app_config = ctx.obj["config"]
    pipeline = AnalyzePipeline(app_config)

    try:
        if dry_run:
            click.echo(f"[*] 开始检查会话 {run_id} 补丁集完整性 (Dry Run)...")
        else:
            click.echo(f"[*] 开始执行阶段三深度分析流水线 (Run ID: {run_id})...")

        result = pipeline.run(
            run_id=run_id,
            target_ids=list(target_ids) if target_ids else None,
            agent_type=agent,
            concurrency=concurrency,
            dry_run=dry_run,
            force=force,
            custom_prompt=custom_prompt,
        )

        if dry_run:
            click.secho("[✓] 完整性检查完成！", fg="green", bold=True)
            click.echo(f"    - 运行 ID: {result.run_id}")
            click.echo(f"    - 待分析 Patchset 总数: {result.total_count}")
            for item in result.analyses:
                if item.status == "skipped":
                    click.echo(
                        f"    - [{item.sanitized_id}] 就绪 -> 目标报告: {item.report_path}"
                    )
                else:
                    click.secho(
                        f"    - [{item.sanitized_id}] 异常: {item.error_message}",
                        fg="yellow",
                    )
        else:
            click.secho("[✓] 深度技术分析完成！", fg="green", bold=True)
            click.echo(f"    - 运行 ID: {result.run_id}")
            click.echo(f"    - 补丁集总数: {result.total_count}")
            click.echo(f"    - 成功分析数: {result.success_count}")
            if result.skipped_count > 0:
                click.secho(f"    - 跳过分析数: {result.skipped_count}", fg="yellow")
            if result.failed_count > 0:
                click.secho(f"    - 失败分析数: {result.failed_count}", fg="red")

            for item in result.analyses:
                if item.status == "success":
                    click.echo(
                        f"    - [{item.sanitized_id}] ({item.duration_seconds}s) 报告: {item.report_path}"
                    )
                elif item.status == "skipped":
                    if item.error_message == "Already analyzed":
                        click.secho(
                            f"    - [{item.sanitized_id}] 已跳过: 报告已存在 ({item.report_path})",
                            fg="yellow",
                        )
                    else:
                        click.echo(
                            f"    - [{item.sanitized_id}] 跳过: {item.error_message}"
                        )
                else:
                    click.secho(
                        f"    - [{item.sanitized_id}] 失败: {item.error_message}",
                        fg="red",
                    )
    except FileNotFoundError as e:
        click.secho(f"[错误] 会话或文件不存在: {e}", fg="red", err=True)
        sys.exit(1)
    except ValueError as e:
        click.secho(f"[错误] {e}", fg="red", err=True)
        sys.exit(1)
    except AgentError as e:
        click.secho(f"[错误] {e}", fg="red", err=True)
        sys.exit(1)
    except Exception as e:
        click.secho(f"[异常] 未知错误: {e}", fg="red", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
