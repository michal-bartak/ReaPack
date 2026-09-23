#!/usr/bin/env python3
"""Merge the per-repository ReaPack indexes into this repository's index.xml.

Each source repository runs reapack-index itself and publishes its own
index.xml. This script only re-roots their <category> elements under a single
<index>, so the package manifests stay in the repositories that own the code.

The <source> URLs inside a generated index are already absolute and point at
their own repository, so nothing needs rewriting here.

A source is read from TWO places: its main branch and its newest tag. A beta
is cut and tagged on a branch before it reaches main, so main alone would
never publish it; the newest tag alone would miss a hotfix released on main
after it. Each index is cumulative, so their union per package is every
published version. Older tags are not read: a version trimmed from the index
by hand would come back from them.

    ./merge-index.py            # fetch the sources and rewrite index.xml
    ./merge-index.py --check    # verify index.xml is up to date, write nothing
    ./merge-index.py a.xml ...  # local files or URLs instead, for testing
"""

import html
import posixpath
import re
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

INDEX_NAME = "MXM Scripts"

SOURCES = [
    "michal-bartak/Reaper-AutoColor",
    "michal-bartak/ListOfInstrumentsAndEffects",
]

RAW = "https://raw.githubusercontent.com/{repo}/{ref}/index.xml"

OUTPUT = Path(__file__).with_name("index.xml")


def fetch(url):
    if "://" not in url:                      # local path, for testing
        return Path(url).read_bytes()
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def version_key(v):
    """ReaPack's version order: numbers numerically, a letter segment marks a
    pre-release, so 1.1.0beta1 < 1.1.0 < 1.1.0.1 and 1.1 == 1.1.0."""
    parts = [(1, int(t)) if t.isdigit() else (0, t)
             for t in re.findall(r"\d+|[A-Za-z]+", v)]
    return parts


def compare_key(v, width):
    parts = version_key(v)
    return parts + [(1, 0)] * (width - len(parts))


def newest_first(names):
    width = max((len(version_key(n)) for n in names), default=0)
    return sorted(names, key=lambda n: compare_key(n, width), reverse=True)


def tags(repo):
    """Tag names that look like versions, newest first. 'v2.1.0' counts."""
    out = subprocess.run(["git", "ls-remote", "--tags", f"https://github.com/{repo}"],
                         capture_output=True, text=True, check=True).stdout
    names = {line.split("refs/tags/", 1)[1].removesuffix("^{}")
             for line in out.splitlines() if "refs/tags/" in line}
    by_version = {n.lstrip("vV"): n for n in names if re.match(r"[vV]?\d", n)}
    return [by_version[v] for v in newest_first(list(by_version))]


def fetch_ref(repo, ref):
    try:
        return fetch(RAW.format(repo=repo, ref=ref))
    except urllib.error.HTTPError as e:
        if e.code == 404:                     # a tag older than the repo's index
            return None
        raise


def union(indexes):
    """One index from several of the same repository: every <version> of each
    package. The package's own metadata comes from the FIRST index holding it --
    main -- so a beta's About text reaches nobody before its release does."""
    packages = {}                             # (category, name) -> {version: elem}
    first = {}                                # (category, name) -> <reapack>
    order = []
    for idx in indexes:
        for category in idx.findall("category"):
            for package in category.findall("reapack"):
                key = (category.get("name"), package.get("name"))
                if key not in packages:
                    packages[key], first[key] = {}, package
                    order.append(key)
                for version in package.findall("version"):
                    packages[key].setdefault(version.get("name"), version)

    root = ET.Element("index", {"version": "1"})
    cats = {}
    for key in order:
        versions = packages[key]
        names = newest_first(list(versions))
        base = first[key]
        pkg = ET.Element("reapack", base.attrib)
        for child in base:
            if child.tag != "version":
                pkg.append(child)
        for name in reversed(names):          # oldest first, as reapack-index writes
            pkg.append(versions[name])
        cat = cats.get(key[0])
        if cat is None:
            cat = cats[key[0]] = ET.SubElement(root, "category", {"name": key[0]})
        cat.append(pkg)
    return root


def load(source):
    """A source as one <index>: a repository's main plus its newest tag with an
    index, or a single file or URL as given."""
    if "://" in source or not re.fullmatch(r"[\w.-]+/[\w.-]+", source):
        return source, ET.fromstring(fetch(source))
    indexes, used = [ET.fromstring(fetch(RAW.format(repo=source, ref="main")))], ["main"]
    for tag in tags(source):
        data = fetch_ref(source, tag)
        if data is not None:
            indexes.append(ET.fromstring(data))
            used.append(tag)
            break
    return f"{source} ({' + '.join(used)})", union(indexes)


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


# reapack-index enforces that no two packages install the same file, but only
# within one repository. Ours live in separate repositories indexed
# independently, so a clash between them is invisible to it and would surface
# as a failed install. ReaPack's registry declares files.path UNIQUE.
def install_paths(category, package):
    """Every path this package writes into REAPER's resource directory."""
    pkg_type = package.get("type")
    for version in package.findall("version"):
        for src in version.findall("source"):
            target = src.get("file") or package.get("name")
            kind = src.get("type") or pkg_type
            base = "Data" if kind == "data" else posixpath.join("Scripts", category)
            yield posixpath.normpath(posixpath.join(base, target))


def merge(sources):
    root = ET.Element("index", {"version": "1", "name": INDEX_NAME})
    categories = {}                           # name -> <category>, insertion ordered
    seen = {}                                 # (category, package) -> source url
    installs = {}                             # install path -> (category, package)

    for source in sources:
        url, src = load(source)
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

                for path in install_paths(name, package):
                    owner = installs.get(path)
                    if owner and owner != key:
                        raise SystemExit(
                            f"two packages install the same file: {path}\n"
                            f"  {owner[0]}/{owner[1]}\n"
                            f"  {key[0]}/{key[1]} (from {url})\n"
                            "ReaPack gives each package exclusive ownership of "
                            "its files; retarget one of them into its own "
                            "subdirectory.")
                    installs[path] = key

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
