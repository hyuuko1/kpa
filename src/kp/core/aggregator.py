from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from kp.models import RawMessage, PatchItem, Patchset


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

    SUBJECT_RE = re.compile(
        r"\[(?P<tag>[^\]]*\bPATCH\b[^\]]*)\]\s*(?P<rest>.*)",
        re.IGNORECASE,
    )
    FRACTION_RE = re.compile(r"\b(\d+)/(\d+)\b")

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

        # 非标准 patch 标签（如仅有 RFC 或普通提交），默认当做独立 patch
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
        """按线程和引用关系聚合并生成 Patchset 列表"""
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
            patches: List[PatchItem] = []
            max_total = 1

            for msg in cluster_msgs:
                is_cov, idx, tot = self.parse_subject_meta(msg.s)
                if tot > max_total:
                    max_total = tot

                if is_cov:
                    cover_msg = msg
                else:
                    patches.append(
                        PatchItem(
                            index=idx,
                            total=tot,
                            title=msg.s,
                            message_id=msg.m,
                            date=msg.dt,
                        )
                    )

            # 确定代表性 ID、Title、作者和时间
            if cover_msg:
                rep_id = cover_msg.m
                title = cover_msg.s
                author_name, author_email = self._extract_author(cover_msg)
                date = cover_msg.dt
                is_cover = True
            else:
                # 无 cover letter 时按 index 升序排序
                patches.sort(key=lambda p: p.index)
                if patches:
                    rep_id = patches[0].message_id
                    title = patches[0].title
                    first_msg = msg_map.get(patches[0].message_id)
                    author_name, author_email = self._extract_author(first_msg)
                    date = patches[0].date
                else:
                    rep_id = root_id
                    title = "Patchset"
                    author_name, author_email = "Unknown", "unknown@kernel.org"
                    date = None
                is_cover = False

            patches.sort(key=lambda p: p.index)
            total_patches = max(max_total, len(patches))

            ps = Patchset(
                id=rep_id,
                title=title,
                author_name=author_name,
                author_email=author_email,
                date=date,
                is_cover_letter=is_cover,
                total_patches=total_patches,
                patches=patches,
            )
            result.append(ps)

        # 4. 按提交日期降序排列
        result.sort(key=lambda ps: ps.date or "", reverse=True)
        return result
