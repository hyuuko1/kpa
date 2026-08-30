from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple
import click
from kp.config import load_config
from kp.adapters.lore import SafetyValidationError, LoreExecutionError
from kp.adapters.b4 import B4ExecutionError, B4NotFoundError
from kp.core.pipeline import FetchPipeline
from kp.core.download_pipeline import DownloadPipeline


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
@click.pass_context
def fetch_cmd(ctx: click.Context, query: str) -> None:
    """阶段一：抓取补丁元数据、清洗聚合并生成 AI 提示词"""
    app_config = ctx.obj["config"]
    pipeline = FetchPipeline(app_config)

    try:
        click.echo(f"[*] 执行查询: {query}")
        result = pipeline.run(query)
        click.secho("[✓] 抓取完成！", fg="green", bold=True)
        click.echo(f"    - 运行 ID: {result.run_id}")
        click.echo(f"    - 原始邮件数: {result.raw_count}")
        click.echo(f"    - 聚合 Patchset 数: {result.patchset_count}")
        click.echo(f"    - 会话目录: {result.run_dir.resolve()}")
        click.echo(f"    - 提示词文件: {result.prompt_path.resolve()}")
        click.secho(f"\n[提示] 可将 {result.prompt_path.name} 提交给 AI 进行第一轮补丁评审与打分。", fg="cyan")
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
    default=70,
    type=int,
    show_default=True,
    help="最低评分过滤阈值 (低于该分数的补丁集将被过滤，除非 recommend=true)",
)
@click.pass_context
def download_cmd(
    ctx: click.Context,
    run_id: str,
    target_ids: Tuple[str, ...],
    input_file: str | None,
    min_score: int,
) -> None:
    """阶段二：下载选定补丁完整邮件线索、结构化解析并生成阶段三提示词"""
    if not target_ids and not input_file:
        click.secho("[错误] 请至少指定 --id 或 --input 参数以选择要下载的补丁集", fg="red", err=True)
        sys.exit(1)

    reviews_content: str | None = None
    if input_file is not None:
        if input_file == "-":
            reviews_content = sys.stdin.read()
        else:
            p = Path(input_file)
            if not p.exists():
                click.secho(f"[错误] 评审结果文件不存在: {input_file}", fg="red", err=True)
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
        )
        click.secho("[✓] 下载与结构化解析完成！", fg="green", bold=True)
        click.echo(f"    - 运行 ID: {result.run_id}")
        click.echo(f"    - 成功下载并解析 Patchset 数: {result.downloaded_count}")
        click.echo(f"    - 会话目录: {result.run_dir.resolve()}")
        if result.stage3_prompt_path:
            click.echo(f"    - 阶段三提示词: {result.stage3_prompt_path.resolve()}")
            click.secho(
                f"\n[提示] 可将 {result.stage3_prompt_path.name} 提交给 AI 进行深度代码架构与逻辑分析 (阶段三)。",
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


if __name__ == "__main__":
    main()

