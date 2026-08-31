# Linux 内核补丁筛选指南 (Screening Reference)

本指南为 AI Agent 提供在 **阶段一 (Stage 1: Screening)** 对 Linux 内核补丁集进行价值评估与优先级打分的准则与规范。

---

## 1. 输入数据源

在筛选阶段，Agent 需要读取当前会话抓取到的元数据文件：
- `data/runs/<run_id>/patchsets.json` (或 `data/runs/<run_id>/manifest.json`)

文件中包含该批次抓取的所有补丁集列表，每个补丁集包含：
- `id` / `msgid`: 邮件 Message-ID / 补丁集唯一标识
- `title`: 补丁集标题 (包含 `[PATCH vX ...]` 等前缀)
- `author_name` / `author_email`: 提交者姓名与邮箱
- `date`: 提交时间
- `patches`: 包含的子补丁列表 (序号、标题、msgid)

---

## 2. 评估维度与准则

请从以下核心维度对补丁集进行价值评估 (0 - 10 分整数制)：

1. **核心子系统重要性与影响面 (Subsystem Importance & Scope)**
   - 核心机制 (Memory Management, Scheduler, VFS, RCU, Locking, BPF, Core Networking) > 边缘/特定小众外设驱动的简单适配；
   - 跨子系统的大型基础设施改动具有更高的优先级。

2. **变更性质与技术深度 (Nature of Changes)**
   - 重大性能瓶颈优化 (如消除热点锁竞争、减少 TLB flush、优化 cache locality)；
   - 核心架构重构与旧机制淘汰演进；
   - 修复严重并发竞态、死锁、Use-After-Free 或安全漏洞 (CVE / KASAN 报告) 的补丁。

3. **设计讨论价值与社区关注度 (Design & RFC Value)**
   - 重要的 RFC (Request for Comments) 系列，代表内核未来的关键演进方向；
   - 涉及核心维护者 (Maintainers) 重点参与讨论的争议性方案。

4. **变更规模与风险权衡 (Scale & Risk)**
   - 单纯的代码风格修正 (checkpatch 警告)、拼写修正、简单版本号提升等打低分 (0-4 分)；
   - 具备完整测试、丰富 Commit Message 论证且影响深远的补丁集打高分 (8-10 分)。

---

## 3. 输出格式规范 (`reviews.json`)

完成评估打分后，必须将结果输出为 JSON 数组并保存至：
`data/runs/<run_id>/reviews.json`

### JSON Schema / 结构定义

```json
[
  {
    "id": "<patchset_id>",
    "title": "<patchset_title>",
    "score": 8,
    "recommend": true,
    "reason": "简要说明推荐/分析理由"
  }
]
```

### 字段说明
- `id` (string, 必需): 对应 `patchsets.json` 中的 `id` 或 `msgid`
- `title` (string, 必需): 补丁集标题
- `score` (integer, 必需): 0 到 10 之间的整数评分
- `recommend` (boolean, 必需): 是否推荐下载并进入后续深度分析 (建议分值 >= 7 时设为 `true`)
- `reason` (string, 必需): 简明扼要的推荐或不推荐理由
