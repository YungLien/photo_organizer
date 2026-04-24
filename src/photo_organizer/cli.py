"""Command-line entry point."""

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Organize photos/videos by capture date and find duplicates.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit.",
    )
    sub = parser.add_subparsers(dest="command", help="Commands")

    sub.add_parser("init-dirs", help="Create Organized/ and Reports/ under a root (for CLI use).")

    p_org = sub.add_parser(
        "organize",
        help="Sort media from an input folder into Organized/YYYY/MM/ (copy by default).",
    )
    p_org.add_argument(
        "--input",
        "-i",
        type=Path,
        default=Path("photos"),
        help="Folder to read from (default: ./photos).",
    )
    p_org.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("Organized"),
        help="Root for YYYY/MM folders (default: ./Organized).",
    )
    p_org.add_argument(
        "--move",
        action="store_true",
        help="Move files instead of copying (default is copy).",
    )
    p_org.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned paths without copying.",
    )

    p_dup = sub.add_parser(
        "duplicates",
        help="Find byte-identical files and perceptually similar images; write JSON under Reports/.",
    )
    p_dup.add_argument(
        "--input",
        "-i",
        type=Path,
        default=Path("Organized"),
        help="Folder to scan recursively (default: ./Organized).",
    )
    p_dup.add_argument(
        "--reports-dir",
        type=Path,
        default=Path("Reports"),
        help="Directory for the report file (default: ./Reports).",
    )
    p_dup.add_argument(
        "--output",
        "-O",
        type=Path,
        default=None,
        help="Report JSON path (default: Reports/duplicates_YYYYMMDD_HHMMSS.json).",
    )
    p_dup.add_argument(
        "--no-exact",
        action="store_true",
        help="Skip SHA-256 exact-duplicate scan.",
    )
    p_dup.add_argument(
        "--no-similar",
        action="store_true",
        help="Skip perceptual-hash similar-image scan.",
    )
    p_dup.add_argument(
        "--similar-max-hamming",
        type=int,
        default=14,
        metavar="N",
        help="Global: max pHash Hamming (default: 14; see --similar-match).",
    )
    p_dup.add_argument(
        "--ahash-max-hamming",
        type=int,
        default=18,
        metavar="N",
        help="Global: max aHash Hamming (default: 18). Use 0 for pHash-only.",
    )
    p_dup.add_argument(
        "--similar-match",
        choices=("phash_led", "and", "or"),
        default="phash_led",
        help=(
            "phash_led (default): (p≤max and a≤max) OR (p≤tight and a≤loose) for exposure-tolerant "
            "matches; and/or are stricter or legacy."
        ),
    )
    p_dup.add_argument(
        "--similar-phash-tight",
        type=int,
        default=10,
        metavar="N",
        help="phash_led: tight pHash bound for the second branch (default: 10).",
    )
    p_dup.add_argument(
        "--similar-ahash-loose",
        type=int,
        default=28,
        metavar="N",
        help="phash_led: loose aHash bound paired with tight pHash (default: 28).",
    )
    p_dup.add_argument(
        "--similar-include-screenshots",
        action="store_true",
        help="Include filename-tagged screenshots in similar clusters (default: exclude by name).",
    )
    p_dup.add_argument(
        "--serial-max-gap",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Same filename prefix (e.g. IMG_): neighbor numbers (gap≤N) may use serial "
            "pHash/aHash limits per --similar-match (default: 0 = off; try 1 for burst bursts)."
        ),
    )
    p_dup.add_argument(
        "--serial-max-hamming",
        type=int,
        default=16,
        metavar="N",
        help="Serial pHash limit with --serial-max-gap>0 (default: 16).",
    )
    p_dup.add_argument(
        "--serial-ahash-max-hamming",
        type=int,
        default=16,
        metavar="N",
        help="Serial aHash limit with --serial-max-gap>0 (default: 16).",
    )

    p_rev = sub.add_parser(
        "review",
        help="Open a browser UI to review duplicate/similar groups from a duplicates JSON report.",
    )
    p_rev.add_argument(
        "--report",
        "-r",
        type=Path,
        default=None,
        help="Path to duplicates_*.json (default: newest in --reports-dir).",
    )
    p_rev.add_argument(
        "--reports-dir",
        type=Path,
        default=Path("Reports"),
        help="Pick latest duplicates_*.json here if --report omitted (default: ./Reports).",
    )
    p_rev.add_argument(
        "--quarantine",
        type=Path,
        default=None,
        help="Ignored for duplicate review (web UI uses Trash). Kept for API compatibility.",
    )
    p_rev.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1).")
    p_rev.add_argument("--port", type=int, default=8765, help="Port (default: 8765).")
    p_rev.add_argument(
        "--screenshots",
        action="store_true",
        help="Review likely screenshots under --screenshots-input instead of duplicates JSON.",
    )
    p_rev.add_argument(
        "--screenshots-input",
        "-S",
        type=Path,
        default=Path("photos"),
        help="Folder to scan for screenshots when --screenshots (default: ./photos).",
    )

    p_serve = sub.add_parser(
        "serve",
        help="Start dashboard + review (Reports under project root; copies to ~/Desktop/Organized).",
    )
    p_serve.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Repo / workspace root (default: current working directory).",
    )
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1).")
    p_serve.add_argument("--port", type=int, default=8765, help="Port (default: 8765).")
    p_serve.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the system browser automatically.",
    )

    p_ss = sub.add_parser(
        "screenshots",
        help="List likely screenshots (filename / PNG shape) and write Reports/screenshots_*.json.",
    )
    p_ss.add_argument(
        "--input",
        "-i",
        type=Path,
        default=Path("photos"),
        help="Folder to scan (default: ./photos).",
    )
    p_ss.add_argument(
        "--reports-dir",
        type=Path,
        default=Path("Reports"),
        help="Output directory (default: ./Reports).",
    )
    p_ss.add_argument(
        "--output",
        "-O",
        type=Path,
        default=None,
        help="Output JSON path (default: screenshots_YYYYMMDD_HHMMSS.json).",
    )

    args = parser.parse_args()

    if args.version:
        from photo_organizer import __version__

        print(__version__)
        sys.exit(0)

    if args.command == "init-dirs":
        root = Path.cwd()
        for name in ("Organized", "Reports"):
            (root / name).mkdir(parents=True, exist_ok=True)
        print(f"Created output directories under {root}")
        sys.exit(0)

    if args.command == "organize":
        from photo_organizer.organize import organize

        inp = args.input.resolve()
        out = args.output.resolve()
        if not inp.is_dir():
            print(f"Input is not a directory: {inp}", file=sys.stderr)
            sys.exit(2)

        r = organize(
            inp,
            out,
            copy=not args.move,
            dry_run=args.dry_run,
        )
        mode = "Would copy" if args.dry_run else ("Moved" if args.move else "Copied")
        for src, dest in r.planned:
            print(f"  {src} -> {dest}")
        print(
            f"{mode}: {len(r.planned)} file(s); "
            f"skipped non-media: {r.skipped}; "
            f"unknown date: {r.unknown_date}"
        )
        if args.dry_run:
            print(
                "Dry run only — nothing was written. "
                "Run again without --dry-run to copy or move files."
            )
        if r.errors:
            for e in r.errors:
                print(e, file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    if args.command == "duplicates":
        from datetime import datetime

        from photo_organizer.duplicates import scan_duplicates, write_report

        inp = args.input.resolve()
        if not inp.is_dir():
            print(f"Input is not a directory: {inp}", file=sys.stderr)
            sys.exit(2)

        do_exact = not args.no_exact
        do_similar = not args.no_similar
        if not do_exact and not do_similar:
            print("Nothing to do: both --no-exact and --no-similar.", file=sys.stderr)
            sys.exit(2)

        r = scan_duplicates(
            inp,
            do_exact=do_exact,
            do_similar=do_similar,
            similar_max_hamming=args.similar_max_hamming,
            similar_ahash_max_hamming=args.ahash_max_hamming,
            similar_serial_max_gap=args.serial_max_gap,
            similar_serial_max_hamming=args.serial_max_hamming,
            similar_serial_ahash_max_hamming=args.serial_ahash_max_hamming,
            similar_match_mode=args.similar_match,
            similar_phash_tight=args.similar_phash_tight,
            similar_ahash_loose=args.similar_ahash_loose,
            similar_include_screenshots=args.similar_include_screenshots,
        )
        if args.output is not None:
            out_path = args.output.resolve()
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = (args.reports_dir / f"duplicates_{stamp}.json").resolve()

        write_report(r, out_path)
        print(f"Wrote {out_path}")
        if do_exact:
            print(f"Exact duplicate groups (2+ files): {len(r.exact_groups)}")
            for g in r.exact_groups[:20]:
                print(f"  {len(g.paths)} files sha256={g.sha256[:12]}…")
            if len(r.exact_groups) > 20:
                print(f"  … and {len(r.exact_groups) - 20} more groups")
        if do_similar:
            if r.similar_ahash_max_hamming > 0:
                if r.similar_match_mode == "phash_led":
                    sim_note = (
                        f"(p≤{r.similar_max_hamming} and a≤{r.similar_ahash_max_hamming}) or "
                        f"(p≤{r.similar_phash_tight} and a≤{r.similar_ahash_loose}) (phash_led)"
                    )
                else:
                    joiner = " and " if r.similar_match_mode == "and" else " or "
                    sim_note = (
                        f"pHash≤{r.similar_max_hamming}{joiner}aHash≤{r.similar_ahash_max_hamming} "
                        f"({r.similar_match_mode})"
                    )
            else:
                sim_note = f"pHash≤{r.similar_max_hamming} only"
            if r.similar_serial_max_gap > 0:
                inner = f"p≤{r.similar_serial_max_hamming}"
                if r.similar_serial_ahash_max_hamming > 0:
                    inner += f" and a≤{r.similar_serial_ahash_max_hamming}"
                sim_note += f"; serial gap≤{r.similar_serial_max_gap} ({inner})"
            print(f"Similar image groups (2+ files, {sim_note}): {len(r.similar_groups)}")
            if r.similar_excluded_screenshots:
                print(
                    f"Excluded {r.similar_excluded_screenshots} filename-tagged screenshot(s) from similar scan."
                )
            for g in r.similar_groups[:20]:
                print(f"  {len(g.paths)} files e.g. {Path(g.paths[0]).name}")
            if len(r.similar_groups) > 20:
                print(f"  … and {len(r.similar_groups) - 20} more groups")
            if r.similar_skipped:
                print(f"Skipped {len(r.similar_skipped)} image(s) (open/hash errors).")
        sys.exit(0)

    if args.command == "screenshots":
        from datetime import datetime

        from photo_organizer.screenshots import scan_screenshots_folder, write_screenshots_report

        inp = args.input.resolve()
        if not inp.is_dir():
            print(f"Input is not a directory: {inp}", file=sys.stderr)
            sys.exit(2)
        hits = scan_screenshots_folder(inp)
        if args.output is not None:
            out_path = args.output.resolve()
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = (args.reports_dir / f"screenshots_{stamp}.json").resolve()
        write_screenshots_report(hits, out_path, input_dir=inp)
        print(f"Wrote {out_path} ({len(hits)} items)")
        sys.exit(0)

    if args.command == "serve":
        from photo_organizer.serve_app import run_serve_server

        root = (args.project_root or Path.cwd()).resolve()
        run_serve_server(
            root,
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
        )
        sys.exit(0)

    if args.command == "review":
        from photo_organizer.review_app import (
            latest_duplicates_json,
            run_review_server,
            run_screenshot_review_server,
        )

        if args.screenshots:
            sd = args.screenshots_input.resolve()
            if not sd.is_dir():
                print(f"Not a directory: {sd}", file=sys.stderr)
                sys.exit(2)
            q = args.quarantine.resolve() if args.quarantine is not None else None
            url = f"http://{args.host}:{args.port}/"
            print(f"Screenshots review UI: {url}")
            print(f"Scan folder: {sd}")
            run_screenshot_review_server(sd, host=args.host, port=args.port, quarantine_root=q)
            sys.exit(0)

        if args.report is not None:
            rp = args.report.resolve()
        else:
            found = latest_duplicates_json(args.reports_dir.resolve())
            if found is None:
                print(
                    "No duplicates_*.json found. Run: photo-organizer duplicates -i photos",
                    file=sys.stderr,
                )
                sys.exit(2)
            rp = found
        if not rp.is_file():
            print(f"Report not found: {rp}", file=sys.stderr)
            sys.exit(2)
        q = args.quarantine.resolve() if args.quarantine is not None else None
        url = f"http://{args.host}:{args.port}/"
        print(f"Opening review UI: {url}")
        print(f"Report file: {rp}")
        run_review_server(rp, host=args.host, port=args.port, quarantine_root=q)
        sys.exit(0)

    if args.command is None:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
