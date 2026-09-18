#!/usr/bin/env python3
"""Merge the recovered community post bodies into data/source/post_bodies.json.

Each community lesson and quick guide has written content in the community that
the app used to drop, keeping only the video. The recovery step writes one JSON
file per post; this merges them and sanitises the inline markup down to links,
bold and italics so it is safe to render.

    python3 scripts/merge_post_bodies.py <bodies_dir> [<bodies_dir> ...]
"""
import glob
import html
import json
import os
import re
import sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INLINE_OK = {'a', 'strong', 'em'}
SAFE_HREF = re.compile(r'^(https?://|mailto:|tel:)', re.I)
BLOCK_TYPES = {'paragraph', 'heading', 'list', 'steps', 'tip', 'warning', 'resources'}
# emoji and the symbol ranges the community posts use as bullets
EMOJI = re.compile(
    '[\U0001F000-\U0001FAFF←-⇿⌀-➿⬀-⯿️⃣™•]'
)


class Inline(HTMLParser):
    """Keep links, bold and italics; drop every other tag, keep its text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.open_a = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            href = dict(attrs).get('href', '')
            if SAFE_HREF.match(href or ''):
                self.out.append('<a href="%s" target="_blank" rel="noopener">' % html.escape(href, quote=True))
                self.open_a += 1
        elif tag in ('strong', 'b'):
            self.out.append('<strong>')
        elif tag in ('em', 'i'):
            self.out.append('<em>')
        elif tag == 'br':
            self.out.append(' ')

    def handle_endtag(self, tag):
        if tag == 'a' and self.open_a:
            self.out.append('</a>')
            self.open_a -= 1
        elif tag in ('strong', 'b'):
            self.out.append('</strong>')
        elif tag in ('em', 'i'):
            self.out.append('</em>')

    def handle_data(self, data):
        self.out.append(html.escape(data, quote=False))

    def result(self):
        self.out.append('</a>' * self.open_a)
        return ''.join(self.out)


def clean_inline(raw):
    p = Inline()
    p.feed(raw or '')
    p.close()
    text = EMOJI.sub('', p.result())
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^[\s|\-–—:]+', '', text)
    return text


def plain(raw):
    """Plain text for fields the app escapes itself, so entities do not survive twice."""
    return html.unescape(re.sub(r'<[^>]+>', '', clean_inline(raw))).strip()


def count_links(blocks):
    return sum(len(re.findall(r'<a href=', json.dumps(b))) + len(b.get('items', []) if b['type'] == 'resources' else [])
               for b in blocks)


def clean_block(b):
    if not isinstance(b, dict) or b.get('type') not in BLOCK_TYPES:
        return None
    t = b['type']
    if t in ('paragraph', 'tip', 'warning'):
        h = clean_inline(b.get('html', ''))
        return {'type': t, 'html': h} if h else None
    if t == 'heading':
        h = plain(b.get('html', ''))
        return {'type': t, 'text': h} if h else None
    if t == 'list':
        items = [{'html': clean_inline(i.get('html', ''))} for i in b.get('items', []) if isinstance(i, dict)]
        items = [i for i in items if i['html']]
        return {'type': t, 'items': items} if items else None
    if t == 'steps':
        items = []
        for i in b.get('items', []):
            if not isinstance(i, dict):
                continue
            h = clean_inline(i.get('html', ''))
            if not h:
                continue
            items.append({'label': plain(i.get('label', ''))[:28], 'html': h})
        return {'type': t, 'items': items} if items else None
    if t == 'resources':
        items = []
        for i in b.get('items', []):
            if not isinstance(i, dict):
                continue
            href = (i.get('href') or '').strip()
            if not SAFE_HREF.match(href):
                continue
            items.append({'label': plain(i.get('label', '')) or re.sub(r'^https?://(www\.)?([^/]+).*', r'\2', href),
                          'href': href})
        return {'type': t, 'items': items} if items else None
    return None


def main(dirs):
    out, stats = {}, {'posts': 0, 'blocks': 0, 'links': 0, 'empty': []}
    seen = set()
    for d in dirs:
        for path in sorted(glob.glob(os.path.join(d, '*.json'))):
            try:
                data = json.load(open(path, encoding='utf-8'))
            except ValueError as exc:
                print('  ! %s: %s' % (os.path.basename(path), exc))
                continue
            pid = str(data.get('id') or os.path.splitext(os.path.basename(path))[0])
            if pid in seen:
                continue
            seen.add(pid)
            blocks = [x for x in (clean_block(b) for b in data.get('blocks', [])) if x]
            # a post whose only content is a link to its own PDF adds nothing:
            # the viewer already shows that PDF and its download button
            if len(blocks) == 1 and blocks[0]['type'] == 'resources' and len(blocks[0]['items']) <= 2:
                blocks = []
            if not blocks:
                stats['empty'].append(pid)
                continue
            out[pid] = blocks
            stats['posts'] += 1
            stats['blocks'] += len(blocks)
            stats['links'] += count_links(blocks)
    dest = os.path.join(ROOT, 'data', 'source', 'post_bodies.json')
    json.dump(out, open(dest, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('%d posts with text, %d blocks, %d links, %d without a body'
          % (stats['posts'], stats['blocks'], stats['links'], len(stats['empty'])))
    return out


if __name__ == '__main__':
    main(sys.argv[1:] or [os.path.join(ROOT, 'bodies')])
