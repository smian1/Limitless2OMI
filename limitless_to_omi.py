#!/usr/bin/env python3
"""
Limitless to Omi Migration Script
Fetches lifelogs from Limitless API and imports them to Omi as conversations.

Usage:
    python3 limitless_to_omi.py --date 2025-12-05
    python3 limitless_to_omi.py --from-date 2025-12-01 --to-date 2025-12-05
    python3 limitless_to_omi.py --all
"""

import argparse
import requests
import time
import sys
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# =============================================================================
# API CONFIGURATION - Enter your API keys here
# =============================================================================
# Get your Limitless API key from: https://limitless.ai/developers
LIMITLESS_API_KEY = ""

# Get your Omi API key from: https://docs.omi.me/developer/apps/Introduction
OMI_API_KEY = ""
# =============================================================================

# API Base URLs (don't change these)
LIMITLESS_BASE_URL = "https://api.limitless.ai"
OMI_BASE_URL = "https://api.omi.me/v1/dev"

# Rate limiting config
OMI_REQUESTS_PER_MINUTE = 100
OMI_MIN_DELAY = 60.0 / OMI_REQUESTS_PER_MINUTE  # 0.6s minimum between requests
DEFAULT_WORKERS = 3  # Number of parallel workers
OMI_MAX_SEGMENTS = 500  # Omi API limit per conversation


def prompt_for_api_keys():
    """Interactively prompt user for API keys if not configured"""
    global LIMITLESS_API_KEY, OMI_API_KEY

    print("=" * 60)
    print("Limitless to Omi Migration - Setup")
    print("=" * 60)
    print("\nAPI keys not configured. Let's set them up.\n")

    if not LIMITLESS_API_KEY:
        print("1. Limitless API Key")
        print("   Get yours from: https://limitless.ai/developers")
        LIMITLESS_API_KEY = input("   Enter your Limitless API key: ").strip()
        if not LIMITLESS_API_KEY:
            print("\n   Error: Limitless API key is required.")
            sys.exit(1)
        print()

    if not OMI_API_KEY:
        print("2. Omi API Key")
        print("   Get yours from: https://docs.omi.me/developer/apps/Introduction")
        OMI_API_KEY = input("   Enter your Omi API key: ").strip()
        if not OMI_API_KEY:
            print("\n   Error: Omi API key is required.")
            sys.exit(1)
        print()

    print("-" * 60)
    print("API keys configured successfully!")
    print("-" * 60)
    print("\nTip: To avoid entering keys each time, edit this script and")
    print("     add your keys in the API CONFIGURATION section at the top.\n")


class LimitlessClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.headers = {"X-API-Key": api_key}

    def fetch_lifelogs(self, date=None, limit=10, cursor=None, timezone="America/Los_Angeles", include_contents=True):
        """Fetch lifelogs from Limitless API"""
        params = {
            "limit": limit,
            "timezone": timezone,
            "includeContents": "true" if include_contents else "false"
        }

        if date:
            params["date"] = date
        if cursor:
            params["cursor"] = cursor

        response = requests.get(
            f"{LIMITLESS_BASE_URL}/v1/lifelogs",
            headers=self.headers,
            params=params
        )

        if response.ok:
            return response.json()
        else:
            return None

    def fetch_all_lifelogs(self, date=None, timezone="America/Los_Angeles", include_contents=True, quiet=False):
        """Fetch all lifelogs with pagination"""
        all_lifelogs = []
        cursor = None
        page = 1

        while True:
            if not quiet:
                print(f"    Fetching page {page}...", end="\r")
            result = self.fetch_lifelogs(date=date, limit=10, cursor=cursor, timezone=timezone, include_contents=include_contents)
            if not result:
                break

            lifelogs = result.get("data", {}).get("lifelogs", [])
            all_lifelogs.extend(lifelogs)

            # Check for next page
            next_cursor = result.get("meta", {}).get("lifelogs", {}).get("nextCursor")
            if not next_cursor:
                break
            cursor = next_cursor
            page += 1

            # Small delay to respect rate limits
            time.sleep(0.3)

        if not quiet:
            print(" " * 40, end="\r")  # Clear the line
        return all_lifelogs

    def get_date_range(self, timezone="America/Los_Angeles"):
        """Find the earliest and latest dates with lifelogs"""
        # Get most recent lifelog
        result = self.fetch_lifelogs(limit=1, timezone=timezone, include_contents=False)
        if not result or not result.get("data", {}).get("lifelogs"):
            return None, None

        latest = result["data"]["lifelogs"][0]
        latest_date = latest.get("startTime", "")[:10]

        # Binary search for earliest date (go back in time)
        earliest_date = latest_date
        days_back = 1

        while days_back < 365:  # Max 1 year back
            check_date = (datetime.strptime(latest_date, "%Y-%m-%d") - timedelta(days=days_back)).strftime("%Y-%m-%d")
            result = self.fetch_lifelogs(date=check_date, limit=1, timezone=timezone, include_contents=False)

            if result and result.get("data", {}).get("lifelogs"):
                earliest_date = check_date
                days_back *= 2  # Double the jump
            else:
                # No data at this date, start narrowing down
                break

            time.sleep(0.2)

        # Now find the actual earliest by checking dates more carefully
        # Go back from earliest_date until we find no data
        current = datetime.strptime(earliest_date, "%Y-%m-%d")
        while True:
            check_date = (current - timedelta(days=1)).strftime("%Y-%m-%d")
            result = self.fetch_lifelogs(date=check_date, limit=1, timezone=timezone, include_contents=False)

            if result and result.get("data", {}).get("lifelogs"):
                earliest_date = check_date
                current = current - timedelta(days=1)
            else:
                break

            time.sleep(0.2)

        return earliest_date, latest_date


class OmiClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        self._lock = threading.Lock()
        self._last_request_time = 0

    def _rate_limit(self):
        """Ensure we don't exceed rate limits"""
        with self._lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < OMI_MIN_DELAY:
                time.sleep(OMI_MIN_DELAY - elapsed)
            self._last_request_time = time.time()

    def create_conversation(self, payload):
        """Create a conversation in Omi using from-segments endpoint"""
        self._rate_limit()

        response = requests.post(
            f"{OMI_BASE_URL}/user/conversations/from-segments",
            headers=self.headers,
            json=payload
        )

        if response.ok:
            return response.json()
        else:
            return None

    def get_conversations(self, limit=100):
        """Get existing conversations for deduplication"""
        response = requests.get(
            f"{OMI_BASE_URL}/user/conversations",
            headers=self.headers,
            params={"limit": limit}
        )

        if response.ok:
            return response.json()
        return []


def convert_lifelog_to_omi(lifelog):
    """Convert a Limitless lifelog to Omi conversation format (from-segments)"""
    segments = []
    speaker_map = {}  # Map speaker names to SPEAKER_XX format
    speaker_counter = 0

    for content in lifelog.get("contents", []):
        # Only include blockquote type (actual transcript, not AI summaries)
        if content.get("type") != "blockquote":
            continue

        text = content.get("content", "").strip()
        if not text:
            continue

        speaker_name = content.get("speakerName", "Unknown")

        # Map all speakers to SPEAKER_XX format
        if speaker_name not in speaker_map:
            speaker_map[speaker_name] = f"SPEAKER_{speaker_counter:02d}"
            speaker_counter += 1

        speaker = speaker_map[speaker_name]
        speaker_id = list(speaker_map.keys()).index(speaker_name)

        segments.append({
            "text": text,
            "speaker": speaker,
            "speaker_id": speaker_id,
            "is_user": False,
            "start": content.get("startOffsetMs", 0) / 1000.0,
            "end": content.get("endOffsetMs", 0) / 1000.0
        })

    return {
        "transcript_segments": segments,
        "started_at": lifelog.get("startTime"),
        "finished_at": lifelog.get("endTime"),
        "source": "phone",
        "language": "en"
    }


def print_progress_bar(current, total, prefix="", suffix="", length=40):
    """Print a progress bar"""
    percent = current / total * 100
    filled = int(length * current // total)
    bar = "█" * filled + "░" * (length - filled)
    print(f"\r{prefix} |{bar}| {percent:5.1f}% {suffix}", end="", flush=True)


def analyze_lifelogs(lifelogs):
    """Analyze lifelogs and return statistics"""
    total_segments = 0
    empty_count = 0
    oversized_count = 0  # Lifelogs that will be split
    extra_conversations = 0  # Additional conversations from splits
    date_range = {}

    for log in lifelogs:
        # Count blockquote segments only
        blockquotes = [c for c in log.get("contents", []) if c.get("type") == "blockquote"]
        segment_count = len(blockquotes)
        total_segments += segment_count

        if segment_count == 0:
            empty_count += 1
        elif segment_count > OMI_MAX_SEGMENTS:
            oversized_count += 1
            # Calculate how many conversations this will become
            num_parts = (segment_count + OMI_MAX_SEGMENTS - 1) // OMI_MAX_SEGMENTS
            extra_conversations += num_parts - 1  # -1 because 1 is already counted

        # Track by date
        start_time = log.get("startTime", "")[:10]
        if start_time:
            if start_time not in date_range:
                date_range[start_time] = 0
            date_range[start_time] += 1

    importable = len(lifelogs) - empty_count
    total_conversations = importable + extra_conversations

    return {
        "total_lifelogs": len(lifelogs),
        "total_segments": total_segments,
        "empty_count": empty_count,
        "importable": importable,
        "oversized_count": oversized_count,
        "total_conversations": total_conversations,
        "dates": date_range
    }


def split_payload_if_needed(omi_payload):
    """Split a payload into multiple if it exceeds the segment limit"""
    segments = omi_payload["transcript_segments"]

    if len(segments) <= OMI_MAX_SEGMENTS:
        return [omi_payload]

    # Split into chunks of OMI_MAX_SEGMENTS
    payloads = []
    for i in range(0, len(segments), OMI_MAX_SEGMENTS):
        chunk = segments[i:i + OMI_MAX_SEGMENTS]

        payloads.append({
            "transcript_segments": chunk,
            "started_at": omi_payload["started_at"],  # Keep original timestamps
            "finished_at": omi_payload["finished_at"],
            "source": omi_payload["source"],
            "language": omi_payload["language"]
        })

    return payloads


def import_single_lifelog(args):
    """Import a single lifelog to Omi (for parallel processing)"""
    index, log, omi_client = args
    title = log.get('title', 'Untitled')[:30]

    omi_payload = convert_lifelog_to_omi(log)

    # Skip empty conversations
    if not omi_payload["transcript_segments"]:
        return (index, "skipped", title, 0)

    # Split if needed (Omi has 500 segment limit)
    payloads = split_payload_if_needed(omi_payload)

    success_count = 0
    for payload in payloads:
        result = omi_client.create_conversation(payload)
        if result:
            success_count += 1

    if success_count == len(payloads):
        return (index, "success", title, len(payloads))
    elif success_count > 0:
        return (index, "partial", title, success_count)
    else:
        return (index, "failed", title, 0)


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Limitless lifelogs to Omi conversations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 limitless_to_omi.py --date 2025-12-05
      Import all lifelogs from December 5, 2025

  python3 limitless_to_omi.py --from-date 2025-12-01 --to-date 2025-12-05
      Import lifelogs from December 1-5, 2025

  python3 limitless_to_omi.py --all
      Import all available lifelogs

  python3 limitless_to_omi.py --date 2025-12-05 --dry-run
      Preview what would be imported without making changes

API Keys:
  You can either:
  1. Edit this script and add your keys in the API CONFIGURATION section
  2. Run the script and enter them interactively when prompted
        """
    )
    parser.add_argument("--date", help="Fetch lifelogs for specific date (YYYY-MM-DD)")
    parser.add_argument("--from-date", help="Start date for range import (YYYY-MM-DD)")
    parser.add_argument("--to-date", help="End date for range import (YYYY-MM-DD)")
    parser.add_argument("--all", action="store_true", help="Import all available lifelogs")
    parser.add_argument("--limit", type=int, default=3, help="Max lifelogs to fetch (default: 3)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without uploading to Omi")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"Number of parallel workers (default: {DEFAULT_WORKERS})")
    parser.add_argument("--timezone", default="America/Los_Angeles", help="Timezone for date filtering")
    args = parser.parse_args()

    # Check if API keys are configured, prompt if not
    if not LIMITLESS_API_KEY or not OMI_API_KEY:
        prompt_for_api_keys()

    print("=" * 60)
    print("Limitless to Omi Migration")
    print("=" * 60)

    # Initialize clients
    limitless = LimitlessClient(LIMITLESS_API_KEY)
    omi = OmiClient(OMI_API_KEY)

    # Step 1: Analyze available data
    print("\n[1] Analyzing Limitless data...")

    if args.all or args.from_date:
        print("    Finding date range of available lifelogs...")
        earliest, latest = limitless.get_date_range(timezone=args.timezone)

        if not earliest or not latest:
            print("    Error: Could not determine date range")
            return

        print(f"    Available data: {earliest} to {latest}")

        # Use provided dates or full range
        start_date = args.from_date if args.from_date else earliest
        end_date = args.to_date if args.to_date else latest

        print(f"    Import range: {start_date} to {end_date}")

    # Step 2: Fetch lifelogs
    print("\n[2] Fetching lifelogs from Limitless...")

    if args.all or args.from_date:
        # Fetch all dates in range
        all_lifelogs = []
        current_date = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        dates_to_fetch = []
        while current_date <= end:
            dates_to_fetch.append(current_date.strftime("%Y-%m-%d"))
            current_date += timedelta(days=1)

        print(f"    Fetching {len(dates_to_fetch)} days of data...")

        for i, date in enumerate(dates_to_fetch):
            print_progress_bar(i + 1, len(dates_to_fetch), prefix="    Fetching", suffix=f"({date})")
            day_lifelogs = limitless.fetch_all_lifelogs(date=date, timezone=args.timezone, quiet=True)
            all_lifelogs.extend(day_lifelogs)
            time.sleep(0.2)

        print()  # New line after progress bar
        lifelogs = all_lifelogs

    elif args.date:
        print(f"    Date: {args.date}")
        lifelogs = limitless.fetch_all_lifelogs(date=args.date, timezone=args.timezone)
    else:
        result = limitless.fetch_lifelogs(limit=args.limit, timezone=args.timezone)
        if not result:
            print("    Failed to fetch lifelogs")
            return
        lifelogs = result.get("data", {}).get("lifelogs", [])

    if not lifelogs:
        print("    No lifelogs found")
        return

    # Step 3: Analyze what we're about to import
    print("\n[3] Analysis Summary:")
    print("-" * 60)

    stats = analyze_lifelogs(lifelogs)

    print(f"    Total lifelogs found:    {stats['total_lifelogs']}")
    print(f"    Total transcript segments: {stats['total_segments']}")
    print(f"    Empty lifelogs (skip):   {stats['empty_count']}")
    print(f"    Lifelogs to import:      {stats['importable']}")
    if stats['oversized_count'] > 0:
        print(f"    Oversized (will split):  {stats['oversized_count']}")
        print(f"    Omi conversations:       {stats['total_conversations']}")

    if stats['dates']:
        print(f"\n    By date:")
        for date in sorted(stats['dates'].keys()):
            print(f"      {date}: {stats['dates'][date]} lifelogs")

    # Estimate time with parallel processing
    effective_rate = min(args.workers * (60 / OMI_MIN_DELAY), OMI_REQUESTS_PER_MINUTE)
    est_time_seconds = stats['total_conversations'] * (60 / effective_rate)
    est_minutes = est_time_seconds / 60
    print(f"\n    Parallel workers:        {args.workers}")
    print(f"    Estimated import time:   {est_minutes:.1f} minutes")

    print("-" * 60)

    # Step 4: Confirm with user
    if args.dry_run:
        print("\n[4] DRY RUN - Preview only (no changes will be made)")
        print("\n    Sample conversion (first lifelog):")
        if lifelogs:
            log = lifelogs[0]
            omi_payload = convert_lifelog_to_omi(log)
            print(f"      Title: {log.get('title', 'Untitled')[:50]}")
            print(f"      Time: {log.get('startTime', '')[:19]}")
            print(f"      Segments: {len(omi_payload['transcript_segments'])}")
            if omi_payload['transcript_segments']:
                first_seg = omi_payload['transcript_segments'][0]
                print(f"      First: {first_seg['speaker']}: {first_seg['text'][:60]}...")
        print("\n    Run without --dry-run to perform the actual import.")
        return

    if not args.yes:
        print(f"\n[4] Ready to import {stats['importable']} lifelogs to Omi.")
        confirm = input("    Continue? [y/N]: ").strip().lower()
        if confirm != 'y':
            print("    Cancelled.")
            return

    # Step 5: Import with parallel processing
    print(f"\n[5] Importing to Omi ({args.workers} parallel workers)...")
    print("-" * 60)

    total = len(lifelogs)
    success = 0
    failed = 0
    skipped = 0
    partial = 0
    completed = 0
    total_conversations = 0  # Track total Omi conversations created
    start_time = time.time()

    # Prepare work items
    work_items = [(i, log, omi) for i, log in enumerate(lifelogs)]

    # Process in parallel with thread pool
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        # Submit all tasks
        futures = {executor.submit(import_single_lifelog, item): item[0] for item in work_items}

        # Process results as they complete
        for future in as_completed(futures):
            completed += 1
            index, status, title, parts = future.result()

            if status == "success":
                success += 1
                total_conversations += parts
                status_char = "✓" if parts == 1 else f"✓({parts})"
            elif status == "partial":
                partial += 1
                total_conversations += parts
                status_char = f"~({parts})"
            elif status == "failed":
                failed += 1
                status_char = "✗"
            else:  # skipped
                skipped += 1
                status_char = "○"

            print_progress_bar(completed, total, prefix="    Progress", suffix=f"{status_char} {title:<30}")

    elapsed = time.time() - start_time
    print()  # New line after progress bar
    print("-" * 60)

    # Step 6: Final summary
    print(f"\n[6] Import Complete!")
    print(f"    Lifelogs processed:  {total}")
    print(f"    Successful:          {success}")
    if partial > 0:
        print(f"    Partial:             {partial}")
    print(f"    Failed:              {failed}")
    print(f"    Skipped (empty):     {skipped}")
    print(f"    Omi conversations:   {total_conversations}")
    print(f"    Time elapsed:        {elapsed/60:.1f} minutes")
    if total_conversations > 0:
        print(f"    Avg per conversation: {elapsed/total_conversations:.2f} seconds")

    print("\n" + "=" * 60)
    print("Done!")


if __name__ == "__main__":
    main()
