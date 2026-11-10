"""Compile every locale/*/LC_MESSAGES/*.po into a .mo next to it (pure Python, no GNU gettext needed).

Usage:  python scripts/compile_po.py

Same result as `python manage.py compilemessages` for the project's own locale/ folder, which needs
gettext's msgfmt (usually missing on Windows and in the Docker image). Fuzzy and empty entries are
skipped, as msgfmt does.
"""

import ast
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse_po(path):
    """Return {key: value} in .mo form: msgctxt joined by \\x04, plural forms joined by \\x00."""
    entries = []
    entry, last, fuzzy = {}, None, False

    def flush():
        nonlocal entry, fuzzy
        if "msgid" in entry and not fuzzy:
            entries.append(entry)
        entry, fuzzy = {}, False

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            flush()
            last = None
            continue
        if line.startswith("#"):
            if line.startswith("#,") and "fuzzy" in line:
                fuzzy = True
            continue
        if line.startswith('"'):
            entry[last] += ast.literal_eval(line)
            continue
        keyword, _, rest = line.partition(" ")
        if keyword in ("msgctxt", "msgid") and keyword in entry and last != "msgctxt":
            flush()
        entry[keyword] = ast.literal_eval(rest.strip())
        last = keyword
    flush()

    catalog = {}
    for e in entries:
        key = e["msgid"]
        if "msgid_plural" in e:
            key += "\x00" + e["msgid_plural"]
            forms = [e[k] for k in sorted(k for k in e if k.startswith("msgstr["))]
            value = "\x00".join(forms)
            if not all(forms):
                continue
        else:
            value = e.get("msgstr", "")
        if not value:
            continue
        if "msgctxt" in e:
            key = e["msgctxt"] + "\x04" + key
        catalog[key] = value
    return catalog


def write_mo(catalog, path):
    keys = sorted(catalog)  # the header ("") sorts first, as gettext expects
    ids = [k.encode("utf-8") for k in keys]
    strs = [catalog[k].encode("utf-8") for k in keys]
    n = len(keys)
    key_start = 7 * 4 + 16 * n
    ids_blob, strs_blob, offsets = b"", b"", []
    for i, s in zip(ids, strs):
        offsets.append((len(i), len(ids_blob), len(s), len(strs_blob)))
        ids_blob += i + b"\0"
        strs_blob += s + b"\0"
    value_start = key_start + len(ids_blob)
    key_table, value_table = [], []
    for ilen, ioff, slen, soff in offsets:
        key_table += [ilen, ioff + key_start]
        value_table += [slen, soff + value_start]
    header = struct.pack("Iiiiiii", 0x950412DE, 0, n, 7 * 4, 7 * 4 + n * 8, 0, 0)
    body = struct.pack(f"{len(key_table)}i", *key_table) + struct.pack(f"{len(value_table)}i", *value_table)
    path.write_bytes(header + body + ids_blob + strs_blob)


def main():
    pos = sorted((ROOT / "locale").glob("*/LC_MESSAGES/*.po"))
    if not pos:
        print("No .po files under locale/")
        return 1
    for po in pos:
        catalog = parse_po(po)
        if "" not in catalog:
            print(f"{po}: missing header entry (msgid \"\")")
            return 1
        mo = po.with_suffix(".mo")
        write_mo(catalog, mo)
        print(f"{mo.relative_to(ROOT)}: {len(catalog) - 1} messages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
