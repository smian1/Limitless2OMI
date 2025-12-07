# Data Mapping: Limitless to Omi

This document describes how data flows from the Limitless API to the Omi API during migration.

## Overview

```
Limitless Lifelog → Filter & Transform → Omi Conversation
     (input)            (script)            (output)
```

Each **Limitless lifelog** becomes one or more **Omi conversations** (split if >500 segments).

---

## Limitless API

### Endpoint
```
GET https://api.limitless.ai/v1/lifelogs
```

### Headers
```
X-API-Key: {your_api_key}
```

### Query Parameters
| Parameter | Description |
|-----------|-------------|
| `limit` | Max 10 per request |
| `cursor` | Pagination cursor |
| `date` | Filter by date (YYYY-MM-DD) |
| `timezone` | Timezone for date filtering |
| `includeContents` | Must be `true` to get transcript |

### Response Structure
```json
{
  "data": {
    "lifelogs": [
      {
        "id": "abc123",
        "title": "Meeting Notes",
        "startTime": "2025-12-05T16:10:19-08:00",
        "endTime": "2025-12-05T16:34:17-08:00",
        "contents": [
          {
            "type": "heading1",
            "content": "Meeting Notes",
            "speakerName": null
          },
          {
            "type": "blockquote",
            "content": "Hello everyone.",
            "speakerName": "Unknown",
            "startOffsetMs": 115000,
            "endOffsetMs": 116000
          }
        ]
      }
    ]
  },
  "meta": {
    "lifelogs": {
      "nextCursor": "xyz789"
    }
  }
}
```

### Content Types
| Type | Description | Action |
|------|-------------|--------|
| `heading1` | AI-generated title | **SKIP** |
| `heading2` | AI-generated section summary | **SKIP** |
| `blockquote` | Actual transcript segment | **INCLUDE** |

---

## Omi API

### Endpoint
```
POST https://api.omi.me/v1/dev/user/conversations/from-segments
```

### Headers
```
Authorization: Bearer {your_api_key}
Content-Type: application/json
```

### Request Body
```json
{
  "started_at": "2025-12-05T16:10:19-08:00",
  "finished_at": "2025-12-05T16:34:17-08:00",
  "source": "phone",
  "language": "en",
  "transcript_segments": [
    {
      "text": "Hello everyone.",
      "speaker": "SPEAKER_00",
      "speaker_id": 0,
      "is_user": false,
      "start": 115.0,
      "end": 116.0
    }
  ]
}
```

### What Omi Stores

| Field | Stored? | Notes |
|-------|---------|-------|
| `started_at` | Yes | Converted to UTC |
| `finished_at` | Yes | Converted to UTC |
| `source` | Yes | Must be `"phone"` |
| `language` | Yes | |
| `transcript_segments[].text` | Yes | |
| `transcript_segments[].speaker` | No | Discarded |
| `transcript_segments[].speaker_id` | Yes | Numeric only |
| `transcript_segments[].is_user` | No | Discarded |
| `transcript_segments[].start` | Yes | |
| `transcript_segments[].end` | Yes | |

---

## Field Mapping

### Conversation Level

| Limitless | Omi | Transformation |
|-----------|-----|----------------|
| `startTime` | `started_at` | Pass through (ISO 8601) |
| `endTime` | `finished_at` | Pass through (ISO 8601) |
| (none) | `source` | Fixed: `"phone"` |
| (none) | `language` | Fixed: `"en"` |

### Segment Level

| Limitless | Omi | Transformation |
|-----------|-----|----------------|
| `contents[].content` | `transcript_segments[].text` | Trim whitespace |
| `contents[].speakerName` | `transcript_segments[].speaker` | Map to `SPEAKER_XX` |
| (derived) | `transcript_segments[].speaker_id` | Sequential (0, 1, 2...) |
| (derived) | `transcript_segments[].is_user` | Always `false` |
| `contents[].startOffsetMs` | `transcript_segments[].start` | Divide by 1000 |
| `contents[].endOffsetMs` | `transcript_segments[].end` | Divide by 1000 |

---

## Speaker Mapping

All speakers are mapped to `SPEAKER_XX` format:

| Limitless `speakerName` | Omi `speaker` | `speaker_id` |
|-------------------------|---------------|--------------|
| First unique speaker | `SPEAKER_00` | 0 |
| Second unique speaker | `SPEAKER_01` | 1 |
| Third unique speaker | `SPEAKER_02` | 2 |
| ... | ... | ... |

---

## Timestamp Handling

Both APIs use ISO 8601 format with timezone offset:
```
2025-12-05T16:10:19-08:00
```

The script passes timestamps through unchanged. Omi converts to UTC internally.

### Segment Timing
```
Limitless: startOffsetMs = 115000, endOffsetMs = 116000
    ↓ divide by 1000
Omi: start = 115.0, end = 116.0 (seconds from conversation start)
```

---

## API Constraints

### Omi Requirements
1. `source` must be `"phone"` (other values cause 500 errors)
2. Speaker names must be `SPEAKER_XX` format
3. Maximum 500 segments per conversation (script auto-splits larger ones)

### Rate Limits
| API | Limit | Script Behavior |
|-----|-------|-----------------|
| Limitless | 180 req/min | 0.3s delay between requests |
| Omi | 100 req/min | 0.6s delay between requests |

---

## Omi Auto-Generated Fields

When you create a conversation, Omi automatically generates:
- `id` - Unique conversation ID
- `created_at` - Creation timestamp
- `structured.title` - AI-generated title
- `structured.overview` - AI-generated summary
- `structured.emoji` - Category emoji
- `structured.category` - Auto-categorization
- `structured.events` - Detected calendar events
- `structured.action_items` - Detected action items
