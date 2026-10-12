"""python3 -m bouncer {setup|estimate|scan|report SNAPSHOT} [--config config.yaml]"""
import argparse, glob, os, sys

from . import core
from .xclient import XClient


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bouncer", description="Read-only X follower-health scanner")
    ap.add_argument("--config", default="config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("setup", help="first-run wizard: config + credential check + cost estimate")
    st.add_argument("--handle"); st.add_argument("--cap", type=float); st.add_argument("--cadence")
    st.add_argument("--non-interactive", action="store_true", help="use flags only, no prompts")
    sub.add_parser("estimate", help="1 cheap lookup; print projected cost vs. your cap")
    sub.add_parser("scan", help="snapshot + report (refuses if over cap)")
    r = sub.add_parser("report", help="rebuild report from a saved snapshot (no API calls)")
    r.add_argument("snapshot", nargs="?")
    a = ap.parse_args(argv)
    if a.cmd == "setup":
        from . import setup
        return setup.run(a.config, a.handle, a.cap, a.cadence, interactive=not a.non_interactive)
    if not os.path.exists(a.config):
        sys.exit(f"No {a.config} yet. Run: python3 -m bouncer setup")
    cfg = core.load_config(a.config)
    if a.cmd == "estimate":
        e = core.estimate(XClient(), cfg)
        print(core.format_estimate(e))
        return 0 if e["within_cap"] else 2
    if a.cmd == "scan":
        path, _ = core.scan(XClient(), cfg)
        print("Snapshot:", path)
        print("Report:  ", core.write_report(path, cfg))
        return 0
    if a.cmd == "report":
        snap = a.snapshot or (sorted(glob.glob("snapshots/*.json")) or [None])[-1]
        if not snap:
            sys.exit("No snapshots yet; run scan first.")
        print("Report:", core.write_report(snap, cfg))
        return 0


if __name__ == "__main__":
    sys.exit(main())
