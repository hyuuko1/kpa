from __future__ import annotations

import email
from email.header import decode_header, make_header
import email.message
import mailbox
from pathlib import Path
import re
from typing import Dict, List, Optional, Set, Tuple

from kp.core.aggregator import PatchsetAggregator
from kp.models import (
    ParsedComment,
    ParsedCoverLetter,
    ParsedPatch,
    ParsedPatchset,
)


DIFF_START_RE = re.compile(
    r"^(?:diff --git\s+|Index:\s+|---\s+[^\n]+\n\+\+\+\s+[^\n]+)",
    re.MULTILINE,
)

TRAILER_PATTERN = re.compile(
    r"^(?:Signed-off-by|Reviewed-by|Acked-by|Suggested-by|Reported-by|Tested-by|"
    r"Co-developed-by|Fixes|Link|Closes|Cc|References|Reported-and-tested-by|Notice):\s*(.*)$",
    re.IGNORECASE,
)


def decode_header_str(val: Optional[str]) -> str:
    """安全解码 MIME 编码的邮件头"""
    if not val:
        return ""
    try:
        decoded_chunks = decode_header(val)
        return str(make_header(decoded_chunks)).strip()
    except Exception:
        return str(val).strip()


def clean_msgid(val: Optional[str]) -> Optional[str]:
    """清洗提取 Message-ID 中的有效部分 (去除尖括号)"""
    if not val:
        return None
    val = val.strip()
    match = re.search(r"<([^>]+)>", val)
    if match:
        return match.group(1).strip()
    return val.strip("<>").strip() or None


def extract_references(msg: email.message.Message) -> List[str]:
    """提取邮件 References 列表中的所有 Message-ID"""
    refs_headers = msg.get_all("References", [])
    result: List[str] = []
    for ref_header in refs_headers:
        found = re.findall(r"<([^>]+)>", str(ref_header))
        if found:
            result.extend([f.strip() for f in found if f.strip()])
        else:
            for item in str(ref_header).split():
                clean = item.strip("<>").strip()
                if clean:
                    result.append(clean)
    return result


def extract_body(msg: email.message.Message) -> str:
    """提取邮件的纯文本正文并规范化换行"""
    if msg.is_multipart():
        body_parts = []
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition") or "")
            if "attachment" in content_disposition:
                continue
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload is not None:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        text = payload.decode(charset, errors="replace")
                    except Exception:
                        text = payload.decode("utf-8", errors="replace")
                    body_parts.append(text)
        if body_parts:
            full_text = "\n".join(body_parts)
            return full_text.replace("\r\n", "\n").replace("\r", "\n")

        for part in msg.walk():
            if part.get_content_maintype() == "text":
                payload = part.get_payload(decode=True)
                if payload is not None:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        text = payload.decode(charset, errors="replace")
                    except Exception:
                        text = payload.decode("utf-8", errors="replace")
                    return text.replace("\r\n", "\n").replace("\r", "\n")
        return ""
    else:
        payload = msg.get_payload(decode=True)
        if payload is not None:
            charset = msg.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except Exception:
                text = payload.decode("utf-8", errors="replace")
            return text.replace("\r\n", "\n").replace("\r", "\n")
        raw_payload = msg.get_payload()
        if raw_payload:
            return str(raw_payload).replace("\r\n", "\n").replace("\r", "\n")
        return ""


def parse_commit_message_and_trailers(
    text: str,
) -> Tuple[str, List[str], Optional[str], str]:
    """解析单个 Patch 的正文，拆分为 commit_message、trailers、diffstat 和 diff"""
    diff_match = DIFF_START_RE.search(text)
    if diff_match:
        pre_diff = text[: diff_match.start()]
        diff_raw = text[diff_match.start() :]
    else:
        pre_diff = text
        diff_raw = ""

    # 移除 git 尾部签名行 (-- \n2.43.0)
    diff_parts = re.split(r"\n-- \s*\n", diff_raw, maxsplit=1)
    diff = diff_parts[0].rstrip() if diff_parts else diff_raw.rstrip()

    # 以 --- 分割 Commit 消息与 Diffstat/版本说明
    parts = re.split(r"^---\s*$", pre_diff, maxsplit=1, flags=re.MULTILINE)
    if len(parts) == 2:
        commit_and_trailers_part = parts[0]
        notes_and_diffstat_part = parts[1]
    else:
        commit_and_trailers_part = pre_diff
        notes_and_diffstat_part = ""

    # 提取 diffstat
    diffstat_lines = []
    for line in notes_and_diffstat_part.splitlines():
        if re.match(r"^\s+.*\s+\|\s+.*", line) or re.match(
            r"^\s*\d+\s+files?\s+changed.*", line
        ):
            diffstat_lines.append(line)
    diffstat = "\n".join(diffstat_lines).strip() if diffstat_lines else None

    # 从底部扫描提取 Trailers 和 Commit Message
    lines = commit_and_trailers_part.strip().splitlines()
    trailers: List[str] = []
    commit_lines: List[str] = []
    scanning_trailers = True

    idx = len(lines) - 1
    while idx >= 0 and not lines[idx].strip():
        idx -= 1

    while idx >= 0:
        line = lines[idx]
        stripped = line.strip()
        if scanning_trailers:
            if TRAILER_PATTERN.match(stripped):
                trailers.append(stripped)
                idx -= 1
                continue
            elif not stripped:
                idx -= 1
                continue
            else:
                scanning_trailers = False
                commit_lines.append(line)
                idx -= 1
        else:
            commit_lines.append(line)
            idx -= 1

    commit_lines.reverse()
    trailers.reverse()
    commit_message = "\n".join(commit_lines).strip()

    return commit_message, trailers, diffstat, diff


def parse_cover_letter_body_and_diffstat(text: str) -> Tuple[str, Optional[str]]:
    """解析 Cover Letter 的正文与统计信息"""
    lines = text.strip().splitlines()
    diffstat_lines = []
    body_lines = []
    in_diffstat = False

    for line in lines:
        if re.match(r"^\s+.*\s+\|\s+.*", line) or re.match(
            r"^\s*\d+\s+files?\s+changed.*", line
        ):
            diffstat_lines.append(line)
            in_diffstat = True
        elif in_diffstat and not line.strip():
            continue
        else:
            body_lines.append(line)

    diffstat = "\n".join(diffstat_lines).strip() if diffstat_lines else None
    body = "\n".join(body_lines).strip()
    return body, diffstat


class MboxParser:
    """Mbox 结构化清洗与树形审阅回复解析器"""

    def __init__(self) -> None:
        self.aggregator = PatchsetAggregator()

    def parse(
        self, mbox_path: Path | str, patchset_id: str, title: str = ""
    ) -> ParsedPatchset:
        """解析指定 mbox 文件，提取 Cover Letter、Patches 与嵌套评论树"""
        mbox_path = Path(mbox_path)
        if not mbox_path.exists() or mbox_path.stat().st_size == 0:
            return ParsedPatchset(
                id=patchset_id,
                title=title or patchset_id,
                total_patches=0,
                cover_letter=None,
                patches=[],
                general_comments=[],
            )

        mbox = mailbox.mbox(str(mbox_path))

        cover_letter: Optional[ParsedCoverLetter] = None
        patches: List[ParsedPatch] = []
        raw_comments: List[Dict] = []

        for msg in mbox:
            subject = decode_header_str(msg.get("Subject"))
            msg_id = (
                clean_msgid(msg.get("Message-ID"))
                or f"msg-{len(patches) + len(raw_comments)}"
            )
            in_reply_to = clean_msgid(msg.get("In-Reply-To"))
            references = extract_references(msg)
            author = decode_header_str(msg.get("From"))
            date = decode_header_str(msg.get("Date")) or None
            body = extract_body(msg)

            is_reply = self.aggregator.is_reply(subject)
            is_cov, idx, tot = self.aggregator.parse_subject_meta(subject)
            has_diff = bool(DIFF_START_RE.search(body))

            if is_reply:
                raw_comments.append(
                    {
                        "author": author,
                        "date": date,
                        "message_id": msg_id,
                        "in_reply_to": in_reply_to,
                        "references": references,
                        "body": body,
                        "subject": subject,
                    }
                )
            elif is_cov:
                cov_body, cov_diffstat = parse_cover_letter_body_and_diffstat(body)
                cover_letter = ParsedCoverLetter(
                    subject=subject,
                    author=author,
                    date=date,
                    message_id=msg_id,
                    body=cov_body,
                    diffstat=cov_diffstat,
                )
            elif has_diff or "[PATCH" in subject.upper():
                commit_msg, trailers, diffstat, diff = (
                    parse_commit_message_and_trailers(body)
                )
                patches.append(
                    ParsedPatch(
                        index=idx,
                        total=tot,
                        subject=subject,
                        author=author,
                        date=date,
                        message_id=msg_id,
                        commit_message=commit_msg,
                        trailers=trailers,
                        diffstat=diffstat,
                        diff=diff,
                        comments=[],
                    )
                )
            else:
                raw_comments.append(
                    {
                        "author": author,
                        "date": date,
                        "message_id": msg_id,
                        "in_reply_to": in_reply_to,
                        "references": references,
                        "body": body,
                        "subject": subject,
                    }
                )

        # 补丁按 index 排序
        patches.sort(key=lambda p: p.index)
        if len(patches) > 1:
            for p in patches:
                if p.total < len(patches):
                    p.total = len(patches)

        # 构建评论树
        patch_map: Dict[str, ParsedPatch] = {p.message_id: p for p in patches}
        cover_id = cover_letter.message_id if cover_letter else None

        comment_nodes: Dict[str, ParsedComment] = {}
        for raw in raw_comments:
            node = ParsedComment(
                author=raw["author"],
                date=raw["date"],
                message_id=raw["message_id"],
                in_reply_to=raw["in_reply_to"],
                body=raw["body"],
                replies=[],
            )
            comment_nodes[node.message_id] = node

        general_comments: List[ParsedComment] = []

        comment_parent_map: Dict[str, Optional[str]] = {}
        for raw in raw_comments:
            msg_id = raw["message_id"]
            target_parent = raw["in_reply_to"]
            if not target_parent and raw["references"]:
                target_parent = raw["references"][-1]
            comment_parent_map[msg_id] = target_parent

        def is_ancestor(ancestor_id: str, start_parent_id: str) -> bool:
            curr: Optional[str] = start_parent_id
            visited: Set[str] = set()
            while curr and curr in comment_parent_map:
                if curr == ancestor_id:
                    return True
                if curr in visited:
                    break
                visited.add(curr)
                curr = comment_parent_map[curr]
            return False

        for raw in raw_comments:
            msg_id = raw["message_id"]
            node = comment_nodes[msg_id]
            parent_id = comment_parent_map[msg_id]

            if (
                parent_id
                and parent_id in comment_nodes
                and not is_ancestor(msg_id, parent_id)
            ):
                comment_nodes[parent_id].replies.append(node)
            elif parent_id and parent_id in patch_map:
                patch_map[parent_id].comments.append(node)
            elif parent_id and parent_id == cover_id:
                general_comments.append(node)
            else:
                attached = False
                for ref in reversed(raw.get("references", [])):
                    if ref in comment_nodes and not is_ancestor(msg_id, ref):
                        comment_nodes[ref].replies.append(node)
                        attached = True
                        break
                    elif ref in patch_map:
                        patch_map[ref].comments.append(node)
                        attached = True
                        break
                    elif cover_id and ref == cover_id:
                        general_comments.append(node)
                        attached = True
                        break
                if not attached:
                    general_comments.append(node)

        final_title = title
        if not final_title:
            if cover_letter and cover_letter.subject:
                final_title = cover_letter.subject
            elif patches and patches[0].subject:
                final_title = patches[0].subject
            else:
                final_title = patchset_id

        return ParsedPatchset(
            id=patchset_id,
            title=final_title,
            total_patches=len(patches),
            cover_letter=cover_letter,
            patches=patches,
            general_comments=general_comments,
        )
