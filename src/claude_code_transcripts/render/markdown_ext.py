"""Markdown rendering with copy-source instrumentation for the render layer."""

import base64
import html
import re

import markdown


class CopySourceTreeprocessor(markdown.treeprocessors.Treeprocessor):
    """Attach copy-target--inline-code + data-copy-src to inline <code> spans."""

    def run(self, root):
        inside_pre = set()
        for pre in root.iter("pre"):
            for code in pre.iter("code"):
                inside_pre.add(id(code))
        for code in root.iter("code"):
            if id(code) in inside_pre:
                continue
            raw = code.text or ""
            existing = code.get("class")
            merged = (
                f"{existing} copy-target--inline-code".strip()
                if existing
                else "copy-target--inline-code"
            )
            code.set("class", merged)
            code.set(
                "data-copy-src",
                base64.b64encode(raw.encode("utf-8")).decode("ascii"),
            )


class CopySourcePostprocessor(markdown.postprocessors.Postprocessor):
    """Attach copy-target--code-block + data-copy-src to <pre><code> blocks.

    fenced_code stashes the <pre><code> HTML and substitutes it back during
    postprocessing, so the tree never sees these elements. We rewrite the
    final HTML string instead.
    """

    PATTERN = re.compile(r"<pre[^>]*>(<code[^>]*>)(.*?)</code></pre>", re.DOTALL)

    def run(self, text):
        return self.PATTERN.sub(self._replace, text)

    @staticmethod
    def _replace(match):
        opening = match.group(1)
        body = match.group(2)
        raw = html.unescape(body)
        b64 = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        if 'class="' in opening:
            new_opening = opening.replace(
                'class="', 'class="copy-target--code-block ', 1
            )
        else:
            new_opening = opening.replace(
                "<code", '<code class="copy-target--code-block"', 1
            )
        new_opening = new_opening[:-1] + f' data-copy-src="{b64}">'
        return f"<pre>{new_opening}{body}</code></pre>"


class CopySourceExtension(markdown.extensions.Extension):
    """Markdown extension that registers copy-source instrumentation."""

    def extendMarkdown(self, md):
        md.treeprocessors.register(CopySourceTreeprocessor(md), "copy_source_inline", 5)
        md.postprocessors.register(CopySourcePostprocessor(md), "copy_source_block", 5)


_LIST_START_RE = re.compile(r"^(?:[-*+]|\d+\.)\s", re.MULTILINE)
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


def _prepare_markdown_for_lists(text):
    """Insert a blank line before list items that follow a non-blank, non-list line.

    The Python markdown library requires a blank line before a list block to
    recognise it.  Claude's output routinely omits this blank line.
    Skips lines inside fenced code blocks.
    """
    lines = text.split("\n")
    result = []
    fence_marker = None
    for i, line in enumerate(lines):
        fence_match = _FENCE_RE.match(line.strip())
        if fence_match:
            char = fence_match.group(1)[0]
            length = len(fence_match.group(1))
            if fence_marker is None:
                fence_marker = (char, length)
            elif (
                char == fence_marker[0]
                and length >= fence_marker[1]
                and line.strip() == fence_match.group(1)
            ):
                fence_marker = None
        if fence_marker is None and i > 0 and _LIST_START_RE.match(line):
            prev = lines[i - 1]
            if prev.strip() and not _LIST_START_RE.match(prev):
                result.append("")
        result.append(line)
    return "\n".join(result)


def _strip_trailing_orphan_fence(text):
    """Remove a trailing orphan opening fence that has no closing partner."""
    lines = text.split("\n")
    last_idx = len(lines) - 1
    while last_idx >= 0 and not lines[last_idx].strip():
        last_idx -= 1
    if last_idx < 0:
        return text
    last_stripped = lines[last_idx].strip()
    fence_match = _FENCE_RE.match(last_stripped)
    if not fence_match or last_stripped != fence_match.group(1):
        return text
    fence_marker = None
    for i in range(last_idx):
        fm = _FENCE_RE.match(lines[i].strip())
        if fm:
            char = fm.group(1)[0]
            length = len(fm.group(1))
            if fence_marker is None:
                fence_marker = (char, length)
            elif (
                char == fence_marker[0]
                and length >= fence_marker[1]
                and lines[i].strip() == fm.group(1)
            ):
                fence_marker = None
    if fence_marker is None:
        lines = lines[:last_idx] + lines[last_idx + 1 :]
        return "\n".join(lines).rstrip()
    return text


def render_markdown_text(text):
    if not text:
        return ""
    text = _strip_trailing_orphan_fence(text)
    text = _prepare_markdown_for_lists(text)
    return markdown.markdown(
        text,
        extensions=[
            "fenced_code",
            "tables",
            "sane_lists",
            "pymdownx.tilde",
            "pymdownx.tasklist",
            CopySourceExtension(),
        ],
    )
