"""Line + word level diff of raw notes (MEM-4). Pure functions."""

from __future__ import annotations

import difflib
import re

from app.memory.schemas import NoteDiffLine, NoteDiffSegment

#: Numbers (with decimals), runs of letters (any script), whitespace, or single symbols.
#: Splitting numbers from letters makes "10분" → ["10", "분"] so a value change is one segment.
_TOKEN = re.compile(r"\d+(?:[.,]\d+)?|[^\W\d_]+|\s+|.", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Split a line into diffable tokens (concatenation reproduces the line)."""
    return _TOKEN.findall(text)


def _merge(segments: list[NoteDiffSegment]) -> list[NoteDiffSegment]:
    out: list[NoteDiffSegment] = []
    for s in segments:
        if out and out[-1].op == s.op:
            out[-1] = NoteDiffSegment(op=s.op, text=out[-1].text + s.text)
        elif s.text:
            out.append(s)
    return out


def word_segments(old: str, new: str) -> tuple[list[NoteDiffSegment], list[NoteDiffSegment]]:
    """Segments for the deleted (old) and inserted (new) version of a changed line."""
    ta, tb = tokenize(old), tokenize(new)
    matcher = difflib.SequenceMatcher(a=ta, b=tb, autojunk=False)
    seg_a: list[NoteDiffSegment] = []
    seg_b: list[NoteDiffSegment] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            text = "".join(ta[i1:i2])
            seg_a.append(NoteDiffSegment(op="equal", text=text))
            seg_b.append(NoteDiffSegment(op="equal", text=text))
        else:
            seg_a.append(NoteDiffSegment(op="delete", text="".join(ta[i1:i2])))
            seg_b.append(NoteDiffSegment(op="insert", text="".join(tb[j1:j2])))
    return _merge(seg_a), _merge(seg_b)


def note_diff(text_a: str, text_b: str) -> list[NoteDiffLine]:
    """Line diff; replaced lines are paired in order and get word-level segments."""
    lines_a, lines_b = text_a.splitlines(), text_b.splitlines()
    matcher = difflib.SequenceMatcher(a=lines_a, b=lines_b, autojunk=False)
    out: list[NoteDiffLine] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            out += [NoteDiffLine(op="equal", text=t) for t in lines_a[i1:i2]]
            continue
        old, new = lines_a[i1:i2], lines_b[j1:j2]
        paired = min(len(old), len(new)) if tag == "replace" else 0
        seg_pairs = [word_segments(old[k], new[k]) for k in range(paired)]
        for k, t in enumerate(old):
            segs = seg_pairs[k][0] if k < paired else []
            out.append(NoteDiffLine(op="delete", text=t, segments=segs))
        for k, t in enumerate(new):
            segs = seg_pairs[k][1] if k < paired else []
            out.append(NoteDiffLine(op="insert", text=t, segments=segs))
    return out
