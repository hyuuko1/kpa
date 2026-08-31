from __future__ import annotations

import re
from typing import List, Dict, Any
from kp.models import ParsedPatchset, ParsedPatch, ParsedCoverLetter, ParsedComment


def sanitize_filename(title: str, max_len: int = 50) -> str:
    """清理文件名中的非法字符并截断"""
    # 移除非字母数字下划线减号空格
    clean = re.sub(r"[^\w\s-]", "", title).strip()
    clean = re.sub(r"[\s_]+", "_", clean)
    if not clean:
        clean = "patch"
    return clean[:max_len].strip("_")


def render_cover_letter_md(cover: ParsedCoverLetter) -> str:
    """将 ParsedCoverLetter 渲染为结构清晰直读的 Markdown"""
    lines = [
        f"# Cover Letter: {cover.subject}",
        "",
        f"- **Author**: {cover.author}",
        f"- **Date**: {cover.date or 'Unknown'}",
        f"- **Message-ID**: `{cover.message_id}`",
        "",
        "## Description & Changelog",
        "",
        cover.body.strip() if cover.body else "(No description provided)",
        "",
    ]
    if cover.diffstat:
        lines.extend(
            [
                "## Diffstat",
                "",
                "```text",
                cover.diffstat.strip(),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _render_comment_tree(comment: ParsedComment, level: int = 1) -> List[str]:
    """递归渲染单条评论及其所有子回复"""
    quote_prefix = (">" * level) + " "
    lines = [
        f"{quote_prefix}**{comment.author}** ({comment.date or 'Unknown date'} - `{comment.message_id}`):",
        f"{quote_prefix}",
    ]
    body = comment.body.strip() if comment.body else "(Empty body)"
    for body_line in body.splitlines():
        lines.append(f"{quote_prefix}{body_line}")
    lines.append(f"{quote_prefix}")

    for reply in comment.replies:
        lines.extend(_render_comment_tree(reply, level=level + 1))
    return lines


def render_discussions_md(patchset: ParsedPatchset) -> str:
    """将整个 Patchset 的所有社区审阅评论与讨论树渲染为 Markdown"""
    has_general = bool(patchset.general_comments)
    has_patch_comments = any(bool(p.comments) for p in patchset.patches)

    if not has_general and not has_patch_comments:
        return "# 社区审阅与讨论\n\n(本次抓取的邮件线程中无后续评论回复)"

    lines = [
        f"# 社区审阅与技术讨论: {patchset.title}",
        "",
        f"> 代表性 Message-ID: `{patchset.id}`",
        "",
    ]

    if has_general:
        lines.extend(
            [
                "## 系列总体讨论 (General / Cover Letter Discussions)",
                "",
            ]
        )
        for c in patchset.general_comments:
            lines.extend(_render_comment_tree(c, level=1))
            lines.append("")

    if has_patch_comments:
        lines.extend(
            [
                "## 各 Patch 内联审阅与讨论 (Patch Discussions)",
                "",
            ]
        )
        for patch in patchset.patches:
            if not patch.comments:
                continue
            lines.extend(
                [
                    f"### [PATCH {patch.index}/{patch.total}] {patch.subject}",
                    "",
                ]
            )
            for c in patch.comments:
                lines.extend(_render_comment_tree(c, level=1))
                lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_patch_file(patch: ParsedPatch) -> str:
    """将 ParsedPatch 渲染为标准独立的 .patch 格式文本"""
    lines = [
        f"From: {patch.author}",
        f"Date: {patch.date or ''}",
        f"Subject: {patch.subject}",
        f"Message-ID: <{patch.message_id}>",
        "",
        patch.commit_message.strip() if patch.commit_message else "",
        "",
    ]

    if patch.trailers:
        for t in patch.trailers:
            lines.append(t)
        lines.append("")

    lines.append("---")
    if patch.diffstat:
        lines.append(patch.diffstat.strip())
        lines.append("")

    if patch.diff:
        lines.append(patch.diff.strip())
    lines.append("")

    return "\n".join(lines)


def render_meta_json(patchset: ParsedPatchset) -> Dict[str, Any]:
    """生成轻量元数据字典（不包含几万行的巨大 Diff 与冗长正文）"""
    return {
        "id": patchset.id,
        "title": patchset.title,
        "total_patches": patchset.total_patches,
        "has_cover_letter": patchset.cover_letter is not None,
        "patches": [
            {
                "index": p.index,
                "total": p.total,
                "subject": p.subject,
                "author": p.author,
                "date": p.date,
                "message_id": p.message_id,
                "comments_count": len(p.comments),
            }
            for p in patchset.patches
        ],
        "general_comments_count": len(patchset.general_comments),
    }
