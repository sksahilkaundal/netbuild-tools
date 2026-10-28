# -*- coding: utf-8 -*-
r"""
ProjectA issue report check -- read-only verification of a published report folder
(or one report PDF) built by scripts\ProjectA_IssueReport_Pipeline.py.

    py -3.14 ProjectA_IssueReport_Verify.py "<BASE>\<YYYYMMDD>_ProjectA_ACC Issue detail (Issues <a>-<b>)"
    py -3.14 ProjectA_IssueReport_Verify.py "<folder or report.pdf>" <EXPORT_SUBDIR>

The export folder is found from the "(Issues a-b)" range in the folder name
(BASE\*\ProjectA_issue_detail_report_<a>_<b>.csv); pass EXPORT_SUBDIR when that is
ambiguous or when the report was capped with MAX_ISSUE_ID.

Every PDF:
  - pages, size (decimal MB), issue pages found
  - layout (since 2026-10-09): the summary starts on page 1, the issue table
    follows it, the issue pages follow the table, and page 1 starts with the
    same two title lines as the table's first page (reports built before
    2026-10-09 have the table first and FAIL only this check)
  - table pages are found by their repeated "ACC ID" header row, so the link
    checks below work on either layout
  - every issue-table ACC ID jumps to that issue's own page (in-PDF link)
  - every heading #ID carries the issue's ACC link (CSV column acc_url)
Summary page: every 'By tier / model' row with issues (numbered NN) links to
its group band (by Tier-Model) or to the group's lowest-id issue page (complete).
Complete report: issues in ACC id order, exactly the CSV's issues.
"by Tier-Model" report: groups contiguous and in summary-row order, ACC id
order inside every group, each issue exactly once and in its own tier / model
group, group bands' counts right, group rows in the table jump to their band,
bookmarks = issue table + summary + one per group (level 1), one per issue
(level 2).
Exit code 0 = all checks passed, 1 = something failed (printed as FAIL).

Not covered (look at a few pages): the After image on issues with 2-3
attachment photos must be a real, different photo.
"""
import glob
import os
import re
import sys

import pymupdf

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # ...\Netbuild
sys.path.insert(0, TOOLS)
import ProjectA_IssueDetailReport_Build as b

BASE = b.BASE
GROUP_RE = re.compile(r"^(\d\d)\s+(.+?)\s+-\s+(\d+) issues?\s*$", re.M)   # text extraction collapses spaces
failures = []


def check(cond, label):
    if not cond:
        failures.append(label)
    return "ok" if cond else "FAIL"


def export_subdir_for(path):
    m = re.search(r"\(Issues (\d+)-(\d+)\)", path)
    if not m:
        raise SystemExit("no '(Issues a-b)' in the path -- pass EXPORT_SUBDIR")
    hits = glob.glob(os.path.join(BASE, "*", "ProjectA_issue_detail_report_%s_%s.csv" % m.groups()))
    if len(hits) != 1:
        raise SystemExit("export folder for issues %s-%s not unique (%s) -- pass EXPORT_SUBDIR" % (m.group(1), m.group(2), hits))
    return os.path.basename(os.path.dirname(hits[0]))


def scan(path, url):
    d = pymupdf.open(path)
    lines = [[s.strip() for s in p.get_text("text").splitlines()] for p in d]
    table = {i for i, ls in enumerate(lines) if "ACC ID" in ls}       # issue table pages (header row repeats)
    summary = next(i for i, ls in enumerate(lines) if "Summary" in ls and i not in table)
    order, page_of, group_start = [], {}, {}
    for i in range(summary + 1, len(d)):
        if i in table:
            continue
        t = d[i].get_text("text")
        g = GROUP_RE.search(t.split("#", 1)[0])
        if g:
            group_start[int(g.group(1))] = (i, g.group(2), int(g.group(3)))
        m = re.search(r"^#(\d+):", t, re.M)
        if m and m.group(1) not in page_of:
            page_of[m.group(1)] = i
            order.append(m.group(1))
    first_issue = min(page_of.values()) if page_of else len(d)
    jumps = acc = grp_links = bad = 0
    summary_links = {}                       # NN -> target page index, from the summary's tier / model rows
    for i, p in enumerate(d):
        for link in p.get_links():
            txt = p.get_textbox(link["from"]).strip()
            m = re.match(r"#?(\d+)\b", txt)
            g = re.match(r"(\d\d)\s", txt)
            if i in table:
                if g and len(txt) > 6 and int(g.group(1)) in group_start \
                        and link.get("page") == group_start[int(g.group(1))][0]:
                    grp_links += 1
                elif m and link.get("page") is not None and link["page"] == page_of.get(m.group(1)):
                    jumps += 1
                else:
                    bad += 1
            elif summary <= i < first_issue:
                if g and link.get("page") is not None:
                    summary_links[int(g.group(1))] = link["page"]
                else:
                    bad += 1
            elif link.get("uri") and m and url.get(m.group(1)) == link["uri"]:
                acc += 1
            else:
                bad += 1
    layout = dict(summary=summary, table=sorted(table), first_issue=first_issue,
                  heading=lines[0][:2], table_heading=lines[min(table)][:2] if table else [])
    return d, order, group_start, jumps, acc, grp_links, bad, summary_links, page_of, layout


def verify(path, rows, ours):
    url = {r["issue_id"]: r.get("acc_url", "") for r in rows}
    bucket = {r["issue_id"]: b.tier_model(r, ours.get(r["issue_id"])) for r in rows}
    n_links = sum(1 for u in url.values() if u)
    d, order, groups, jumps, acc, grp_links, bad, summary_links, page_of, lay = scan(path, url)
    name = os.path.basename(path)
    print("\n%s\n   %d pages, %.1f MB, %d issue pages" % (name, len(d), os.path.getsize(path) / 1e6, len(order)))
    t = lay["table"]
    first_ok = lay["summary"] == 0 and bool(t) and lay["first_issue"] == t[-1] + 1 \
        and len(lay["heading"]) == 2 and lay["heading"][0].startswith("ProjectF") and lay["heading"] == lay["table_heading"]
    print("   layout: summary from p%d, issue table p%d-%d, issues from p%d | summary first, title lines on top %s" % (
        lay["summary"] + 1, (t[0] + 1 if t else 0), (t[-1] + 1 if t else 0), lay["first_issue"] + 1,
        check(first_ok, name + ": summary first + title lines")))
    print("   table jumps %d/%d %s | ACC links %d/%d %s | stray links %d %s" % (
        jumps, len(rows), check(jumps == len(rows), name + ": table jumps"),
        acc, n_links, check(acc == n_links, name + ": ACC links"), bad, check(bad == 0, name + ": stray links")))
    ids = sorted((r["issue_id"] for r in rows), key=int)
    used = {b.BUCKET_NO[v] for v in bucket.values()}
    if "by Tier-Model" not in name:
        want = {b.BUCKET_NO[bucket[i]]: page_of.get(i) for i in reversed(ids)}   # lowest id wins
    else:
        want = {n: pg for n, (pg, _, _) in groups.items()}
    print("   summary tier / model links %d/%d %s" % (
        sum(1 for n, pg in summary_links.items() if want.get(n) == pg), len(used),
        check(set(summary_links) == used and all(want.get(n) == pg for n, pg in summary_links.items()),
              name + ": summary links")))
    if "by Tier-Model" not in name:
        print("   complete report: ACC id order %s | exactly the CSV's issues %s" % (
            check(order == ids, name + ": id order"), check(sorted(order, key=int) == ids, name + ": issue set")))
        return
    seq = [bucket[i] for i in order]
    blocks = [seq[0]] + [seq[k] for k in range(1, len(seq)) if seq[k] != seq[k - 1]] if seq else []
    expected = [label for label in b.BUCKETS if label in set(bucket.values())]
    inner = all(int(order[k]) < int(order[k + 1]) for k in range(len(order) - 1) if seq[k] == seq[k + 1])
    bands_ok = sorted(lbl for _, lbl, _ in groups.values()) == sorted(expected) and all(
        c == sum(1 for v in bucket.values() if v == lbl) for _, lbl, c in groups.values())
    toc = d.get_toc()
    lvl1, lvl2 = sum(1 for e in toc if e[0] == 1), sum(1 for e in toc if e[0] == 2)
    print("   groups contiguous, summary-row order %s | id order inside groups %s | each issue once %s | all issues %s" % (
        check(blocks == expected, name + ": group order"), check(inner, name + ": id order in groups"),
        check(len(order) == len(set(order)), name + ": duplicates"), check(sorted(order, key=int) == ids, name + ": issue set")))
    print("   group bands %s | group row links %d/%d %s | bookmarks L1 %d/%d %s, L2 %d/%d %s" % (
        check(bands_ok, name + ": bands"), grp_links, len(expected), check(grp_links == len(expected), name + ": group links"),
        lvl1, len(expected) + 2, check(lvl1 == len(expected) + 2, name + ": bookmarks L1"),
        lvl2, len(rows), check(lvl2 == len(rows), name + ": bookmarks L2")))
    print("   groups: " + ", ".join("%02d %s (%d)" % (n, lbl, c) for n, (_, lbl, c) in sorted(groups.items())))


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    target = argv[0]
    b.EXPORT_SUBDIR = argv[1] if len(argv) > 1 else export_subdir_for(target)
    rows = b.read_csv(b._export_csv())
    ours = b.load_ours()
    print("Export %s: %d issues in the CSV" % (b.EXPORT_SUBDIR, len(rows)))
    pdfs = [target] if target.lower().endswith(".pdf") else \
        [os.path.join(target, n) for n in sorted(os.listdir(target)) if n.lower().endswith(".pdf")]
    for path in pdfs:
        verify(path, rows, ours)
    print("\n%s" % ("ALL CHECKS PASSED" if not failures else "FAILED: " + "; ".join(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
