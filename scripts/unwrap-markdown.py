#!/usr/bin/env python3
"""Join hard-wrapped markdown paragraphs into one line each.

Prose is stored unwrapped and flowed by whatever reads it. Code fences,
tables, headings and list structure are preserved exactly; only the line
breaks inside a paragraph or a single list item are removed.
"""
import re
import sys

FENCE = re.compile(r'^\s{0,3}(```|~~~)')
HEADING = re.compile(r'^\s{0,3}#{1,6}\s')
LIST = re.compile(r'^(\s*)([-*+]|\d+[.)])\s+')
TABLE = re.compile(r'^\s*\|')
RULE = re.compile(r'^\s{0,3}([-*_])\s*(\1\s*){2,}$')
SETEXT = re.compile(r'^\s{0,3}(=+|-+)\s*$')
INDENTED = re.compile(r'^ {4,}\S')


def unwrap(text):
    lines = text.split('\n')
    out = []
    pending = None          # paragraph or list item being accumulated
    indent = ''             # continuation indent of the pending list item
    fence = None

    def flush():
        nonlocal pending, indent
        if pending is not None:
            out.append(pending)
            pending = None
            indent = ''

    previous_blank = True
    for line in lines:
        stripped = line.strip()
        if fence:
            out.append(line)
            if FENCE.match(line) and line.strip().startswith(fence):
                fence = None
            previous_blank = False
            continue
        match = FENCE.match(line)
        if match:
            flush()
            fence = match.group(1)
            out.append(line)
            previous_blank = False
            continue
        if not stripped:
            flush()
            out.append('')
            previous_blank = True
            continue
        starts_block = (HEADING.match(line) or TABLE.match(line) or RULE.match(line)
                        or SETEXT.match(line) or stripped.startswith('>')
                        or (previous_blank and INDENTED.match(line)))
        list_match = LIST.match(line)
        if starts_block:
            flush()
            out.append(line)
        elif list_match:
            flush()
            pending = line.rstrip()
            indent = ' ' * (len(list_match.group(1)) + len(list_match.group(2)) + 1)
        elif pending is not None:
            pending = pending + ' ' + stripped
        else:
            pending = line.rstrip()
            indent = ''
        previous_blank = False
    flush()
    result = '\n'.join(out)
    return result if result.endswith('\n') or not text.endswith('\n') else result + '\n'


def check(before, after):
    """Nothing may be added, dropped or reordered, and block structure must hold."""
    if re.sub(r'\s+', '', before) != re.sub(r'\s+', '', after):
        return 'content changed'
    for name, pattern in (('headings', HEADING), ('list items', LIST), ('table rows', TABLE)):
        counts = [sum(1 for line in t.split('\n') if pattern.match(line)) for t in (before, after)]
        if counts[0] != counts[1]:
            return name + ' changed: ' + str(counts[0]) + ' -> ' + str(counts[1])
    if before.count('```') != after.count('```'):
        return 'code fences changed'
    return None


if __name__ == '__main__':
    failures = 0
    for path in sys.argv[1:]:
        with open(path, encoding='utf-8') as stream:
            before = stream.read()
        after = unwrap(before)
        problem = check(before, after)
        if problem:
            print('SKIPPED ' + path + ': ' + problem)
            failures += 1
            continue
        if after != before:
            with open(path, 'w', encoding='utf-8') as stream:
                stream.write(after)
            print('unwrapped ' + path)
    raise SystemExit(1 if failures else 0)
