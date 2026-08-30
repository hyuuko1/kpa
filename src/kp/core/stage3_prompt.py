from __future__ import annotations

from pathlib import Path
from typing import List


class Stage3PromptBuilder:
    """生成阶段三 AI 补丁深度技术分析提示词"""

    TEMPLATE = """# Linux 内核补丁深度技术分析任务 (阶段三)

你是一位资深的 Linux 内核维护者与核心子系统架构专家。本次运行（Run ID: `{run_id}`）已完成补丁集筛选并拉取、清洗了高价值补丁集。

所有补丁集均已按“**AI 直读友好型**”结构拆解并组织在对应的目录中，你可以直接使用文件查看工具阅读，无需编写脚本解析：

## 目标补丁集目录列表
{patchsets_list}

## 补丁集目录结构说明
每个补丁集目录下均包含以下文件（可直接按需读取）：
- `00-cover-letter.md`：系列背景说明、整体动机与总体 Diffstat（若有多补丁系列）
- `discussions.md`：社区 Maintainer / Reviewer 的审阅评论与辩论树（直读 Markdown 引用格式）
- `patches/`：独立的代码补丁文件（如 `0001-xxx.patch`，包含完整的 Commit Message、Trailers 与统一 Diff）
- `meta.json`：轻量级索引元数据
- `parsed_series.json`：全量结构化 JSON 数据（可选）

## 深度分析核心维度与指引
针对每个补丁集，请重点从以下维度开展多角度深入分析：

1. **背景动机与架构设计 (Architecture & Context)**
   - 该补丁集试图解决什么根本问题？现有内核机制有何缺陷或性能瓶颈？
   - 核心设计与数据结构/接口演进是否合理？对所属子系统及跨子系统的架构影响几何？

2. **锁与并发安全 (Concurrency & Locking)**
   - 代码中涉及的锁保护机制（Spinlock, Mutex, RCU, Lockless/Atomics, 内存屏障）是否严谨？
   - 是否存在死锁、竞争条件（Race Condition）、ABBA 锁反序或 lock contention 风险？

3. **内存与资源生命周期 (Memory & Lifecycle)**
   - 是否存在内存泄漏、UAF（Use-After-Free）、越界访问、未初始化使用或 Double-free 隐患？
   - 错误处理路径（Error / Cleanup paths）与资源释放顺序是否完整对应？

4. **潜在回归与性能/兼容性风险 (Regressions & Impact)**
   - 变更是否可能引入潜在的行为破坏、API/ABI 不兼容或破坏特定架构（x86, ARM64 等）兼容性？
   - 对核心路径的性能（Cache line 命中率、分支预测、TLB 开销、吞吐/延迟）有何潜在影响？

5. **社区审阅洞察与争议点 (Community Discussion & Key Debates)**
   - 维护者与评审者（Reviewer）在邮件讨论中关注的重点问题是什么？
   - 作者是如何回应或修改设计的？当前是否存在未决的技术分歧或后续演进方向？

## 期望输出报告结构
请为每个分析的补丁集生成结构清晰的技术报告：
```markdown
# 补丁集分析: [<patchset_title>] (<patchset_id>)

## 1. 摘要与背景评述 (Executive Summary)
...

## 2. 关键技术方案与代码实现剖析 (Technical Deep Dive)
...

## 3. 锁、并发与内存安全评估 (Safety & Concurrency Assessment)
...

## 4. 潜在风险与回归隐患 (Risk & Regression Analysis)
...

## 5. 社区评审洞察与争议要点 (Community Review & Insights)
...
```
"""

    def build_prompt(self, run_id: str, parsed_patchsets_paths: List[Path]) -> str:
        if not parsed_patchsets_paths:
            patchsets_str = "- (本次未拉取或解析到任何补丁集数据)"
        else:
            items = []
            for p in parsed_patchsets_paths:
                p_dir = p.parent if p.is_file() else p
                items.append(f"- 目录: `{str(p_dir.resolve())}`\n  - 主数据: `{str(p.resolve())}`")
            patchsets_str = "\n".join(items)

        return self.TEMPLATE.format(
            run_id=run_id,
            patchsets_list=patchsets_str,
        )
