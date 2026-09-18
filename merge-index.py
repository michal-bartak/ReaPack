#!/usr/bin/env python3
"""Merge the per-repository ReaPack indexes into this repository's index.xml.

Each source repository runs reapack-index itself and publishes its own
index.xml. This script only re-roots their <category> elements under a single
<index>, so the package manifests stay in the repositories that own the code.

The <source> URLs inside a generated index are already absolute and point at
their own repository, so nothing needs rewriting here.

    ./merge-index.py            # fetch the sources and rewrite index.xml
    ./merge-index.py --check    # verify index.xml is up to date, write nothing
"""

import html
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

INDEX_NAME = "MXM Scripts"

SOURCES = [
    "https://raw.githubusercontent.com/michal-bartak/ReaColorizer/main/index.xml",
    "https://raw.githubusercontent.com/michal-bartak/ListOfInstrumentsAndEffects/main/index.xml",
]

OUTPUT = Path(__file__).with_name("index.xml")


def fetch(url):
    if "://" not in url:                      # local path, for testing
        return Path(url).read_bytes()
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


XML_DECL = '<?xml version="1.0" encoding="utf-8"?>\n'

# reapack-index wraps these in CDATA. ElementTree cannot, so put it back rather
# than hand ReaPack's parser escaped RTF and Markdown it has never seen.
CDATA_TAGS = re.compile(r"<(description|changelog)>(.+?)</\1>", re.DOTALL)


def restore_cdata(xml):
    def repl(m):
        tag, body = m.group(1), m.group(2)
        text = html.unescape(body)
        if "]]>" in text:                     # would terminate the section early
            return m.group(0)
        return f"<{tag}><![CDATA[{text}]]></{tag}>"
    return CDATA_TAGS.sub(repl, xml)


def merge(sources):
    root = ET.Element("index", {"version": "1", "name": INDEX_NAME})
    categories = {}                           # name -> <category>, insertion ordered
    seen = {}                                 # (category, package) -> source url

    for url in sources:
        src = ET.fromstring(fetch(url))
        if src.tag != "index":
            raise SystemExit(f"{url}: root element is <{src.tag}>, expected <index>")

        for category in src.findall("category"):
            name = category.get("name")
            if name is None:
                raise SystemExit(f"{url}: <category> without a name attribute")

            target = categories.get(name)
            if target is None:
                target = categories[name] = ET.SubElement(
                    root, "category", {"name": name})

            for package in category.findall("reapack"):
                key = (name, package.get("name"))
                if key in seen:
                    raise SystemExit(
                        f"duplicate package {name}/{key[1]}\n"
                        f"  first seen in {seen[key]}\n"
                        f"  also present in {url}")
                seen[key] = url
                target.append(package)

    if not seen:
        raise SystemExit("no packages found in any source index")

    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="unicode")
    return (XML_DECL + restore_cdata(xml) + "\n").encode("utf-8"), seen


def main(argv):
    check = "--check" in argv
    sources = [a for a in argv[1:] if not a.startswith("-")] or SOURCES

    merged, seen = merge(sources)
    current = OUTPUT.read_bytes() if OUTPUT.exists() else None

    if check:
        if current != merged:
            print("index.xml is out of date -- run ./merge-index.py", file=sys.stderr)
            return 1
        print(f"index.xml is up to date ({len(seen)} packages)")
        return 0

    if current == merged:
        print(f"index.xml unchanged ({len(seen)} packages)")
        return 0

    OUTPUT.write_bytes(merged)
    for (category, package) in seen:
        print(f"  {category}/{package}")
    print(f"wrote {OUTPUT.name}: {len(seen)} packages")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
