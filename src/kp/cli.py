from __future__ import annotations

import sys
from pathlib import Path
import click
from kp.config import load_config
from kp.adapters.lore import SafetyValidationError, LoreExecutionError
from kp.core.pipeline import FetchPipeline


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


if __name__ == "__main__":
    main()
