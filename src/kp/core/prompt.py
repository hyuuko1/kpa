from __future__ import annotations

from pathlib import Path


class PromptBuilder:
    """生成 AI 筛选补丁集的提示词"""

    TEMPLATE = """# Linux 内核补丁评审与筛选任务

你是一位资深的 Linux 内核专家与代码审查助手。请对本次抓取到的 Linux 内核补丁集进行价值评估与优先级打分，筛选出值得进一步深入分析的高价值 Patchset。

## 数据源
已清洗的补丁集元数据文件绝对路径为：
`{patchsets_json_abs_path}`

请读取上述文件中的 Patchset 列表（包含 ID、标题、作者、时间、子 patch 列表）。

## 评估维度与准则
1. **子系统重要性与影响面**：核心机制（如 MM、调度器、VFS、锁等）改动 > 边缘驱动的小修补；
2. **变更性质**：重要性能优化、核心架构重构、修复关键内存损坏/死锁/安全漏洞的补丁优先级更高；
3. **设计讨论价值**：重要 RFC、跨子系统大型重构系列优先关注。

## 期望输出格式
请以 JSON 格式输出打分与筛选结果（供后续阶段二直接消费）：
```json
[
  {{
    "id": "<patchset_id>",
    "title": "<patchset_title>",
    "score": 85,
    "recommend": true,
    "reason": "简要说明推荐/分析理由"
  }}
]
```
"""

    def build_prompt(self, patchsets_json_path: Path) -> str:
        abs_path = str(patchsets_json_path.resolve())
        return self.TEMPLATE.format(patchsets_json_abs_path=abs_path)
