from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from kp.models import RawMessage, Patchset


class UnionFind:
    """并查集，用于按引用关系快速合并邮件线程"""

    def __init__(self) -> None:
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
            return x
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: str, y: str) -> None:
        root_x = self.find(x)
        root_y = self.find(y)
        if root_x != root_y:
            self.parent[root_x] = root_y


class PatchsetAggregator:
    """将 RawMessage 列表清洗并聚合为 Patchset 列表"""

    REPLY_PREFIX_RE = re.compile(r"^(?:re|aw|fwd|sv)\s*:", re.IGNORECASE)
    SUBJECT_RE = re.compile(
        r"\[(?P<tag>[^\]]*\bPATCH\b[^\]]*)\]\s*(?P<rest>.*)",
        re.IGNORECASE,
    )
    FRACTION_RE = re.compile(r"\b(\d+)/(\d+)\b")

    def is_reply(self, subject: str) -> bool:
        """判断邮件主题是否为回复"""
        return bool(self.REPLY_PREFIX_RE.match(subject.strip()))

    def parse_subject_meta(self, subject: str) -> Tuple[bool, int, int]:
        """解析邮件主题，返回 (is_cover_letter, index, total)"""
        match = self.SUBJECT_RE.search(subject)
        if match:
            tag = match.group("tag")
            frac_match = self.FRACTION_RE.search(tag)
            if frac_match:
                idx = int(frac_match.group(1))
                tot = int(frac_match.group(2))
                is_cover = (idx == 0)
                return (is_cover, idx, tot)
            return (False, 1, 1)

        # 非标准 patch 标签，默认当做独立 patch
        return (False, 1, 1)

    def parse_subject(self, subject: str) -> Tuple[bool, int, int, str]:
        """解析邮件主题，返回 (is_cover_letter, index, total, title)"""
        is_cov, idx, tot = self.parse_subject_meta(subject)
        return (is_cov, idx, tot, subject)

    def _extract_author(self, msg: Optional[RawMessage]) -> Tuple[str, str]:
        """从 RawMessage 中安全提取作者姓名和邮箱"""
        author_name = "Unknown"
        author_email = "unknown@kernel.org"
        if msg and msg.f and len(msg.f) > 0:
            first_from = msg.f[0]
            if len(first_from) > 0 and first_from[0]:
                author_name = first_from[0]
            if len(first_from) > 1 and first_from[1]:
                author_email = first_from[1]
        return author_name, author_email

    def aggregate(self, messages: List[RawMessage]) -> List[Patchset]:
        """按线程和引用关系聚合并生成 Patchset 列表（自动过滤回复）"""
        if not messages:
            return []

        # 1. 初始化并查集并合并引用关系
        uf = UnionFind()
        msg_map: Dict[str, RawMessage] = {m.m: m for m in messages if m.m}

        for msg in messages:
            if not msg.m:
                continue
            uf.find(msg.m)
            for ref in (msg.refs or []):
                if ref:
                    uf.union(msg.m, ref)

        # 2. 按连通分量进行聚类
        clusters: Dict[str, List[RawMessage]] = {}
        for msg in messages:
            if not msg.m:
                continue
            root = uf.find(msg.m)
            if root not in clusters:
                clusters[root] = []
            clusters[root].append(msg)

        # 3. 从每个 cluster 构造 Patchset 对象
        result: List[Patchset] = []
        for root_id, cluster_msgs in clusters.items():
            cover_msg: Optional[RawMessage] = None
            # 存储 (index, title, msg_id, date, msg)
            raw_patches: List[Tuple[int, str, str, Optional[str], RawMessage]] = []

            for msg in cluster_msgs:
                # 过滤回复邮件 (如 Re: [PATCH ...])
                if self.is_reply(msg.s):
                    continue

                is_cov, idx, tot = self.parse_subject_meta(msg.s)

                if is_cov:
                    cover_msg = msg
                else:
                    raw_patches.append((idx, msg.s, msg.m, msg.dt, msg))

            # 如果该 cluster 全是回复邮件，无有效 cover letter 或 patch，则跳过
            if not cover_msg and not raw_patches:
                continue

            # 按 index 升序排序
            raw_patches.sort(key=lambda item: item[0])
            patch_titles = [item[1] for item in raw_patches]

            # 确定代表性 ID、Title、作者和时间
            if cover_msg:
                rep_id = cover_msg.m
                title = cover_msg.s
                author_name, author_email = self._extract_author(cover_msg)
                date = cover_msg.dt
            else:
                rep_id = raw_patches[0][2]
                title = raw_patches[0][1]
                first_msg = raw_patches[0][4]
                author_name, author_email = self._extract_author(first_msg)
                date = raw_patches[0][3]

            ps = Patchset(
                id=rep_id,
                title=title,
                author_name=author_name,
                author_email=author_email,
                date=date,
                patches=patch_titles,
            )
            result.append(ps)

        # 4. 按提交日期降序排列
        result.sort(key=lambda ps: ps.date or "", reverse=True)
        return result

