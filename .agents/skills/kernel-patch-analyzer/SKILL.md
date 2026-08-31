---
name: kernel-patch-analyzer
description: "Linux 内核补丁初筛打分、下载解包与 AI 深度技术分析全流程指南。"
---

# Linux 内核补丁分析器指南 (Kernel Patch Analyzer Guide)

本 Skill 指引 AI Agent 使用 `kp` 工具链完成 Linux 内核补丁集的初筛打分、完整拉取拆解与多维度深度技术分析。

## 全流程工作流概览

1. **阶段一：初筛打分 (Stage 1: Screening)**
   - 读取当前会话目录中的 `data/runs/<run_id>/patchsets.json` (或 `manifest.json`)；
   - 遵循 [初筛指南](references/screening.md) 对各补丁集进行价值评估打分 (0 - 100 分) 并给出推荐标记；
   - 将结构化评分结果保存至 `data/runs/<run_id>/reviews.json`。

2. **阶段二：拉取与直读拆解 (Stage 2: Download & Decomposition)**
   - 运行命令 `kp download --run-id <run_id> -i reviews.json`；
   - `kp` 会自动下载完整邮件线程并解构为直读文件，存放于 `data/runs/<run_id>/patchsets/<sanitized_id>/`：
     - `00-cover-letter.md`：系列背景说明、整体动机与总体 Diffstat
     - `discussions.md`：社区审阅评论与嵌套辩论树
     - `patches/*.patch`：包含完整 Commit Message、Trailers 与统一 Diff 的 Git 补丁文件
     - `meta.json`：轻量级索引元数据

3. **阶段三：内核深度分析与报告落盘 (Stage 3: Deep Analysis & Reporting)**
   - 当被调度分析指定补丁集（路径如 `data/runs/<run_id>/patchsets/<sanitized_id>/`）时：
   - 直接读取该目录下的 `00-cover-letter.md`、`discussions.md`、`patches/*.patch` 及 `meta.json`；
   - 严格按照 [深度分析指南](references/deep-analysis.md) 中的 5 大核心维度展开系统性技术剖析；
   - **将生成的完整 Markdown 分析报告直接持久化保存至**：
     `data/runs/<run_id>/reports/<sanitized_id>.md`

## 渐进式披露参考文档 (Progressive Disclosure)

- **补丁初筛评分标准与 `reviews.json` Schema**：请查阅 [初筛指南](references/screening.md)；
- **5 大深度技术分析维度与报告标准模板**：请查阅 [深度分析指南](references/deep-analysis.md)。
