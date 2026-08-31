from __future__ import annotations

import shutil
from pathlib import Path
from typing import Generator
import pytest

import kp.config
import kp.cli

TEST_TMP_RUNS_DIR = Path("/tmp/kp_pytest_runs")


@pytest.fixture(scope="session", autouse=True)
def clean_tmp_runs_session() -> Generator[None, None, None]:
    """在每轮测试开始前，清理 /tmp 中的旧测试产物并重新创建。"""
    if TEST_TMP_RUNS_DIR.exists():
        shutil.rmtree(TEST_TMP_RUNS_DIR, ignore_errors=True)
    TEST_TMP_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    yield
    # 会话结束后保持隔离目录或在下轮开始前清理


@pytest.fixture(autouse=True)
def isolate_test_data_dir(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Generator[Path, None, None]:
    """确保单元测试不会在项目仓库的 data/runs 写入产物，统一重定向到 /tmp 下的隔离目录。"""
    test_node_name = (
        request.node.name.replace("/", "_")
        .replace(":", "_")
        .replace("[", "_")
        .replace("]", "_")
    )
    test_dir = TEST_TMP_RUNS_DIR / test_node_name
    if test_dir.exists():
        shutil.rmtree(test_dir, ignore_errors=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    # 包装 load_config，使得未指定特定配置文件时，默认将 storage.data_dir 重定向到 /tmp 目录
    orig_load_config = kp.config.load_config

    def wrapped_load_config(config_path=None):
        cfg = orig_load_config(config_path)
        # 如果没有显式指定 config_path，且当前测试不是专门测试默认字符串的用例
        if config_path is None and request.module.__name__ != "tests.test_config":
            cfg.storage.data_dir = str(test_dir)
        return cfg

    monkeypatch.setattr(kp.config, "load_config", wrapped_load_config)
    monkeypatch.setattr(kp.cli, "load_config", wrapped_load_config)

    yield test_dir
