"""Michigan EGLE well-log PDF downloader with threaded workers + failtree tracking."""

from __future__ import annotations

import argparse
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from failtree import Tracker

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

LAYER_URL = (
    "https://gisagoegle.state.mi.us/arcgis/rest/services/EGLE/DwOpenData/MapServer/3/query"
)
PDF_BASE_URL = (
    "https://www.egle.state.mi.us/WELLOGIC/ReportProxy.aspx/?/WELLOGIC/WELLOGIC/"
    "user_Well%20Record&rs:Command=Render&rs:Format=PDF&wellLogID="
)

OUTPUT_FOLDER = "michigan_files"
RUNS_DB = "michigan_runs.db"
MAX_WORKERS = 20
BATCH_SIZE = 2000

print_lock = threading.Lock()


def fetch_all_wellids(*, limit: int | None = None) -> list[str]:
    """Page through the layer and collect WELLIDs (optional early stop via limit)."""
    params = {
        "where": "1=1",
        "outFields": "WELLID",
        "returnGeometry": "false",
        "f": "json",
        "resultRecordCount": BATCH_SIZE,
        "returnExceededLimitFeatures": "true",
    }

    well_ids: list[str] = []
    offset = 0

    while True:
        params["resultOffset"] = offset
        try:
            response = requests.get(LAYER_URL, params=params, timeout=30)
            data = response.json()
        except Exception as exc:
            print(f"  Query error at offset {offset}: {exc}")
            break

        features = data.get("features", [])
        if not features:
            break

        for feat in features:
            wid = feat["attributes"].get("WELLID")
            if wid:
                well_ids.append(str(wid).strip())
                if limit is not None and len(well_ids) >= limit:
                    return well_ids

        fetched = len(well_ids)
        if fetched % 50000 == 0:
            print(f"  … collected {fetched:,} IDs so far")

        if len(features) < BATCH_SIZE:
            break
        offset += BATCH_SIZE

    return well_ids


def inject_test_error(well_id: str, index: int) -> None:
    """Raise synthetic errors so failtree grouping/chains can be verified.

    Pattern by index % 5:
      0,1 -> ValueError with different UUIDs/paths (should share one group)
      2   -> RuntimeError HTTP-style failure
      3   -> chained KeyError -> RuntimeError (parent/child tree)
      4   -> no inject (real download path)
    """
    bucket = index % 5
    if bucket in (0, 1):
        raise ValueError(
            f"simulated corrupt PDF stream id={uuid.uuid4()} "
            f"path=/data/wells/{well_id}.pdf"
        )
    if bucket == 2:
        raise RuntimeError(f"HTTP 503 for wellLogID={well_id}")
    if bucket == 3:
        try:
            raise KeyError(well_id)
        except KeyError as exc:
            raise RuntimeError(f"metadata missing for wellLogID={well_id}") from exc
    # bucket == 4: fall through to real download


def download_pdf(well_id: str, output_folder: str) -> str:
    """Download one PDF. Returns 'skipped' | 'downloaded'. Raises on failure."""
    filepath = os.path.join(output_folder, f"{well_id}.pdf")

    if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
        return "skipped"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/pdf,*/*",
    }
    response = requests.get(
        PDF_BASE_URL + well_id,
        headers=headers,
        timeout=30,
        stream=True,
    )
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code} for wellLogID={well_id}")

    with open(filepath, "wb") as handle:
        for chunk in response.iter_content(chunk_size=16384):
            handle.write(chunk)

    size = os.path.getsize(filepath)
    if size < 500:
        os.remove(filepath)
        raise RuntimeError(f"empty PDF response for wellLogID={well_id}")

    with print_lock:
        print(f"  {well_id}.pdf  ({size // 1024} KB)")
    return "downloaded"


def process_one(
    tracker: Tracker,
    well_id: str,
    *,
    index: int,
    inject_errors: bool,
) -> None:
    """One worker task: tracked download (failtree captures failures)."""
    with tracker.item(well_id, stage="download"):
        if inject_errors:
            inject_test_error(well_id, index)
        download_pdf(well_id, OUTPUT_FOLDER)


def run_downloads(
    tracker: Tracker,
    well_ids: list[str],
    *,
    workers: int,
    inject_errors: bool = False,
) -> None:
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                process_one,
                tracker,
                wid,
                index=i,
                inject_errors=inject_errors,
            )
            for i, wid in enumerate(well_ids)
        ]
        for fut in as_completed(futures):
            # Exceptions already captured by Tracker when continue_on_error=True.
            fut.result()


def retry_failed(
    tracker: Tracker,
    *,
    workers: int,
    inject_errors: bool = False,
) -> None:
    log = os.path.join(OUTPUT_FOLDER, "_failed_ids.txt")
    if not os.path.exists(log):
        print("No failed log found.")
        return
    with open(log, encoding="utf-8") as handle:
        ids = [line.strip() for line in handle if line.strip()]
    print(f"Retrying {len(ids):,} failed IDs …")
    run_downloads(
        tracker,
        ids,
        workers=workers,
        inject_errors=inject_errors,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Michigan well PDF downloader + failtree")
    parser.add_argument("--retry", action="store_true", help="Retry IDs from _failed_ids.txt")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only fetch/download the first N well IDs (useful for smoke tests)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=MAX_WORKERS,
        help=f"Thread workers (default {MAX_WORKERS})",
    )
    parser.add_argument(
        "--inject-errors",
        action="store_true",
        help="Inject synthetic failures to exercise failtree grouping/chains",
    )
    parser.add_argument(
        "--fresh-db",
        action="store_true",
        help=f"Delete {RUNS_DB} before starting a new tracked run",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    Path(OUTPUT_FOLDER).mkdir(parents=True, exist_ok=True)

    if args.fresh_db and Path(RUNS_DB).exists():
        Path(RUNS_DB).unlink()
        for suffix in ("-wal", "-shm"):
            side = Path(RUNS_DB + suffix)
            if side.exists():
                side.unlink()

    print("=" * 65)
    print("Michigan EGLE Well Log PDF Downloader + failtree")
    print("=" * 65)
    if args.inject_errors:
        print("Inject errors: ON (synthetic failures for failtree testing)")

    with Tracker(
        RUNS_DB,
        label="michigan-download-inject" if args.inject_errors else "michigan-download",
        continue_on_error=True,
        project_roots=(Path(__file__).resolve().parent,),
    ) as tracker:
        if args.retry:
            retry_failed(
                tracker,
                workers=args.workers,
                inject_errors=args.inject_errors,
            )
        else:
            print("\nFetching WELLID values from MapServer layer 3 …")
            if args.limit:
                print(f"  (limit={args.limit})")
            well_ids = fetch_all_wellids(limit=args.limit)
            print(f"  Total well IDs collected: {len(well_ids):,}")

            if not well_ids:
                print("No IDs returned. Check network access to the MapServer.")
                return

            existing = {
                name.replace(".pdf", "")
                for name in os.listdir(OUTPUT_FOLDER)
                if name.endswith(".pdf")
            }
            # When injecting errors, process the whole batch so failures are recorded
            # even if PDFs already exist from a prior run.
            if args.inject_errors:
                remaining = well_ids
            else:
                remaining = [wid for wid in well_ids if wid not in existing]
            print(f"  Already downloaded : {len(existing):,}")
            print(f"  Queued             : {len(remaining):,}")

            if not remaining:
                print("\nAll selected PDFs already downloaded!")
                print("  Tip: re-test failtree with:")
                print(
                    "    python michigan.py --limit 15 --workers 6 "
                    "--inject-errors --fresh-db"
                )
            else:
                print(
                    f"\nDownloading {len(remaining):,} PDFs "
                    f"with {args.workers} workers …\n"
                )
                run_downloads(
                    tracker,
                    remaining,
                    workers=args.workers,
                    inject_errors=args.inject_errors,
                )

        summary = tracker.summary()
        print("\n-- failtree summary --")
        print(f"  run_id={summary.run_id}")
        print(f"  total={summary.total} ok={summary.ok} failed={summary.failed}")
        print(f"  groups={summary.groups}")
        print(f"  db={Path(RUNS_DB).resolve()}")
        print(f"  files={Path(OUTPUT_FOLDER).resolve()}")
        print("\nInspect with:")
        print(f"  python -m failtree.cli summary {RUNS_DB}")
        print(f"  python -m failtree.cli export {RUNS_DB} -o retry.txt --stage download")


if __name__ == "__main__":
    main()
