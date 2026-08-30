from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


class SafetyConfig(BaseModel):
    max_time_span_minutes: int = 180
    require_time_filter: bool = True


class LoreConfig(BaseModel):
    inbox_url: str = "https://lore.kernel.org/all/"
    timeout_seconds: int = 60


class StorageConfig(BaseModel):
    data_dir: str = "data/runs"


class AppConfig(BaseModel):
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    lore: LoreConfig = Field(default_factory=LoreConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """加载配置：优先指定路径 -> ./kp.toml -> ./config.toml -> ~/.config/kp/config.toml -> 默认"""
    if config_path is not None:
        p = Path(config_path)
        if p.is_file():
            try:
                with open(p, "rb") as f:
                    data = tomllib.load(f)
                return AppConfig.model_validate(data)
            except Exception:
                pass
        return AppConfig()

    search_paths = [
        Path("kp.toml"),
        Path("config.toml"),
        Path.home() / ".config" / "kp" / "config.toml",
    ]

    for p in search_paths:
        if p.is_file():
            try:
                with open(p, "rb") as f:
                    data = tomllib.load(f)
                return AppConfig.model_validate(data)
            except Exception:
                continue

    return AppConfig()

