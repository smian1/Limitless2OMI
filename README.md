# Limitless to Omi Migration

Migrate your conversation transcripts from [Limitless](https://limitless.ai) to [Omi](https://omi.me).

## Features

- Fetches lifelogs from Limitless API with full transcript data
- Converts and imports to Omi as properly segmented conversations
- Parallel processing for faster imports
- Automatic splitting of large conversations (>500 segments)
- Progress bar with real-time status
- Dry-run mode for previewing changes
- Interactive API key setup

## Requirements

- Python 3.7+
- `requests` library

```bash
pip install requests
```

## Setup

### 1. Get Your API Keys

**Limitless API Key:**
- Go to [limitless.ai/developers](https://limitless.ai/developers)
- Create an API key

**Omi API Key:**
- Go to [docs.omi.me/developer/apps/Introduction](https://docs.omi.me/developer/apps/Introduction)
- Create a developer app and get your API key

### 2. Configure the Script

You have two options:

**Option A: Edit the script** (recommended for repeated use)
```python
# Open limitless_to_omi.py and add your keys at the top:
LIMITLESS_API_KEY = "your-limitless-api-key"
OMI_API_KEY = "your-omi-api-key"
```

**Option B: Interactive mode**
Just run the script without configuring keys - it will prompt you to enter them.

## Usage

### Import a specific date
```bash
python3 limitless_to_omi.py --date 2025-12-05
```

### Import a date range
```bash
python3 limitless_to_omi.py --from-date 2025-12-01 --to-date 2025-12-05
```

### Import all available lifelogs
```bash
python3 limitless_to_omi.py --all
```

### Preview without importing (dry run)
```bash
python3 limitless_to_omi.py --date 2025-12-05 --dry-run
```

### Skip confirmation prompt
```bash
python3 limitless_to_omi.py --date 2025-12-05 -y
```

## Command Line Options

| Option | Description |
|--------|-------------|
| `--date DATE` | Import lifelogs from a specific date (YYYY-MM-DD) |
| `--from-date DATE` | Start date for range import |
| `--to-date DATE` | End date for range import |
| `--all` | Import all available lifelogs |
| `--dry-run` | Preview without making changes |
| `--yes`, `-y` | Skip confirmation prompt |
| `--workers N` | Number of parallel workers (default: 3) |
| `--timezone TZ` | Timezone for date filtering (default: America/Los_Angeles) |
| `--limit N` | Max lifelogs when not using date filters (default: 3) |

## Example Output

```
============================================================
Limitless to Omi Migration
============================================================

[1] Analyzing Limitless data...

[2] Fetching lifelogs from Limitless...
    Date: 2025-12-05

[3] Analysis Summary:
------------------------------------------------------------
    Total lifelogs found:    36
    Total transcript segments: 2456
    Empty lifelogs (skip):   0
    Lifelogs to import:      36

    By date:
      2025-12-05: 36 lifelogs

    Parallel workers:        3
    Estimated import time:   0.4 minutes
------------------------------------------------------------

[4] Ready to import 36 lifelogs to Omi.
    Continue? [y/N]: y

[5] Importing to Omi (3 parallel workers)...
------------------------------------------------------------
    Progress |████████████████████████████████████████| 100.0% ✓ Last conversation title
------------------------------------------------------------

[6] Import Complete!
    Lifelogs processed:  36
    Successful:          35
    Failed:              1
    Skipped (empty):     0
    Omi conversations:   35
    Time elapsed:        2.5 minutes

============================================================
Done!
```

## How It Works

1. **Fetches** lifelogs from Limitless API (with pagination)
2. **Filters** content to only include actual transcript (`blockquote` type)
3. **Transforms** data to Omi's conversation format
4. **Splits** large conversations (>500 segments) into multiple parts
5. **Uploads** to Omi with rate limiting and parallel processing

See [DATA_MAPPING.md](DATA_MAPPING.md) for detailed field mapping information.

## Rate Limits

The script respects API rate limits:
- **Limitless**: 180 requests/minute (0.3s delay)
- **Omi**: 100 requests/minute (0.6s delay)

## Troubleshooting

### "Failed to fetch lifelogs"
- Check your Limitless API key is correct
- Verify you have lifelogs for the specified date

### Import failures
- Check your Omi API key is correct
- The Omi API requires `source` to be `"phone"`
- Large lifelogs (>500 segments) are automatically split

### Rate limit errors
- Reduce the number of workers with `--workers 1`
- The script has built-in rate limiting, but very large imports may still hit limits

## License

MIT
