from pathlib import Path
import pytest
from kp.config import load_config, AppConfig, B4Config


def test_load_default_config():
    config = load_config(config_path=Path("non_existent_file.toml"))
    assert isinstance(config, AppConfig)
    assert config.safety.max_time_span_minutes == 180
    assert config.safety.require_time_filter is True
    assert config.lore.inbox_url == "https://lore.kernel.org/all/"
    assert config.lore.timeout_seconds == 60
    assert config.storage.data_dir == "data/runs"
    assert isinstance(config.b4, B4Config)
    assert config.b4.timeout_seconds == 120


def test_load_custom_toml_config(tmp_path: Path):
    custom_toml = tmp_path / "custom.toml"
    custom_toml.write_text(
        """
[safety]
max_time_span_minutes = 60
require_time_filter = true

[lore]
inbox_url = "https://lore.kernel.org/linux-mm/"
timeout_seconds = 30

[storage]
data_dir = "my_custom_runs"
""",
        encoding="utf-8",
    )
    config = load_config(config_path=custom_toml)
    assert config.safety.max_time_span_minutes == 60
    assert config.lore.inbox_url == "https://lore.kernel.org/linux-mm/"
    assert config.lore.timeout_seconds == 30
    assert config.storage.data_dir == "my_custom_runs"


def test_load_config_partial_custom(tmp_path: Path):
    custom_toml = tmp_path / "custom_partial.toml"
    custom_toml.write_text(
        """
[lore]
timeout_seconds = 45
""",
        encoding="utf-8",
    )
    config = load_config(config_path=custom_toml)
    assert config.safety.max_time_span_minutes == 180
    assert config.lore.timeout_seconds == 45
    assert config.storage.data_dir == "data/runs"


def test_load_config_invalid_toml_fallback(tmp_path: Path):
    broken_toml = tmp_path / "broken.toml"
    broken_toml.write_text("broken = [invalid toml", encoding="utf-8")
    config = load_config(config_path=broken_toml)
    assert isinstance(config, AppConfig)
    assert config.safety.max_time_span_minutes == 180


def test_load_config_auto_discover_kp_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "kp.toml").write_text(
        """
[storage]
data_dir = "auto_kp_runs"
""",
        encoding="utf-8",
    )
    config = load_config()
    assert config.storage.data_dir == "auto_kp_runs"


def test_load_config_auto_discover_config_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        """
[storage]
data_dir = "auto_config_runs"
""",
        encoding="utf-8",
    )
    config = load_config()
    assert config.storage.data_dir == "auto_config_runs"


def test_load_config_auto_discover_user_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    user_config_dir = tmp_path / ".config" / "kp"
    user_config_dir.mkdir(parents=True)
    (user_config_dir / "config.toml").write_text(
        """
[storage]
data_dir = "home_config_runs"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    config = load_config()
    assert config.storage.data_dir == "home_config_runs"


def test_load_config_with_b4_section(tmp_path: Path):
    custom_toml = tmp_path / "b4_config.toml"
    custom_toml.write_text(
        """
[b4]
timeout_seconds = 180
""",
        encoding="utf-8",
    )
    config = load_config(config_path=custom_toml)
    assert config.b4.timeout_seconds == 180


def test_agent_config_defaults():
    config = load_config(None)
    assert config.agent.default == "agy"
    assert config.agent.agy_cmd == "agy"
    assert config.agent.opencode_cmd == "opencode"
    assert config.agent.timeout_seconds == 600
    assert config.agent.concurrency == 1


def test_load_config_with_agent_section(tmp_path: Path):
    custom_toml = tmp_path / "agent_config.toml"
    custom_toml.write_text(
        """
[agent]
default = "opencode"
agy_cmd = "my-agy"
opencode_cmd = "my-opencode"
timeout_seconds = 300
concurrency = 2
""",
        encoding="utf-8",
    )
    config = load_config(config_path=custom_toml)
    assert config.agent.default == "opencode"
    assert config.agent.agy_cmd == "my-agy"
    assert config.agent.opencode_cmd == "my-opencode"
    assert config.agent.timeout_seconds == 300
    assert config.agent.concurrency == 2


def test_kernel_config_defaults():
    config = load_config(None)
    assert config.kernel.path == "/code/linux"


def test_load_config_with_kernel_section(tmp_path: Path):
    custom_toml = tmp_path / "kernel_config.toml"
    custom_toml.write_text(
        """
[kernel]
path = "/custom/kernel/source"
""",
        encoding="utf-8",
    )
    config = load_config(config_path=custom_toml)
    assert config.kernel.path == "/custom/kernel/source"
