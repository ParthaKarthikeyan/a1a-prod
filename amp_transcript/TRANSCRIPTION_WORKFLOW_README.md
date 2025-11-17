# Transcription Workflow - Python Implementation

This is a Python implementation of the Azure Logic App workflow for processing audio transcriptions using the VoiceGain API.

## Overview

The workflow performs the following steps:

1. **Query SQL Database** - Fetches audio file metadata from `Autoqa_metadata` table
2. **Submit to VoiceGain API** - Sends each audio file URL for async transcription
3. **Poll for Completion** - Checks transcription status every 20 seconds (max 60 iterations)
4. **Retrieve Transcript** - Gets the completed transcript from VoiceGain
5. **Format Transcript** - Formats the transcript (via Azure Function or locally)
6. **Save to Blob Storage** - Stores the formatted transcript in Azure Blob Storage

## Features from Original Logic App

- ✅ SQL query execution with filters
- ✅ VoiceGain API integration with full configuration
- ✅ Rate limiting handling (HTTP 429)
- ✅ Session URL parsing and polling
- ✅ Error detection and handling
- ✅ Timeout protection (60 iterations × 20 seconds = 20 minutes)
- ✅ Azure Function integration for transcript formatting
- ✅ Blob storage upload with date-based folder structure
- ✅ Sequential processing (concurrency = 1)

## VoiceGain API Configuration

The implementation includes all formatters from the Logic App:

- **Diarization**: 2-3 speakers
- **Digits** formatter
- **Basic** formatter (enabled)
- **Enhanced** formatter (CC, EMAIL)
- **Profanity** filter (partial masking)
- **Spelling** (en-US)
- **Redact** formatter (full masking for PII: SSN, PHONE, CC, EMAIL, etc.)
- **Regex** formatters (custom patterns)

## Prerequisites

```bash
pip install -r requirements_transcription.txt
```

### Required Packages

- `requests` - HTTP client for API calls
- `pyodbc` - SQL Server database connectivity
- `azure-storage-blob` - Azure Blob Storage client

### System Requirements

- **ODBC Driver 17 for SQL Server** or newer
  - Windows: Usually pre-installed
  - Linux: `sudo apt-get install unixodbc-dev`
  - Mac: `brew install unixodbc`

## Configuration

Edit the configuration section in `transcription_workflow.py`:

```python
# VoiceGain API Token
VOICEGAIN_TOKEN = "your_bearer_token_here"

# SQL Server Connection String
SQL_CONNECTION_STRING = "Driver={ODBC Driver 17 for SQL Server};Server=your_server;Database=your_db;UID=your_user;PWD=your_password"

# Azure Blob Storage Connection String
BLOB_CONNECTION_STRING = "DefaultEndpointsProtocol=https;AccountName=your_account;AccountKey=your_key;EndpointSuffix=core.windows.net"

# Optional: Azure Function URL for transcript formatting
AZURE_FUNCTION_URL = "https://your-function-app.azurewebsites.net/api/format_audio"

# SAS Token for audio file access
SAS_TOKEN = "sv=2024-11-04&ss=bfqt&..."

# Workflow Parameters
COMPANY_GUID = "872F9103-326F-47C5-A3C2-566565F2F541"
EVALUATION_DATE = "2025-10-12"
```

## Usage

### Basic Usage

```bash
python transcription_workflow.py
```

### Programmatic Usage

```python
from transcription_workflow import TranscriptionWorkflow

# Initialize workflow
workflow = TranscriptionWorkflow(
    voicegain_bearer_token="your_token",
    sql_connection_string="your_connection_string",
    blob_connection_string="your_blob_connection",
    azure_function_url=None  # Optional, uses local formatting if None
)

# Run workflow
workflow.run(
    company_guid="872F9103-326F-47C5-A3C2-566565F2F541",
    evaluation_date="2025-10-12",
    sas_token="your_sas_token"
)
```

## Workflow Methods

### `execute_sql_query(company_guid, evaluation_date, interaction_direction)`

Queries the database for audio files matching criteria.

**Returns**: List of dictionaries containing audio metadata

### `submit_transcription_request(audio_url)`

Submits an audio file to VoiceGain for transcription.

**Returns**: Response JSON with session info, or `None` if rate limited (429)

### `poll_transcription_status(session_url, max_iterations=60, delay_seconds=20)`

Polls the transcription session until completion or timeout.

**Returns**: Tuple of `(results_phase, status)`

### `get_transcript(session_url)`

Retrieves the completed transcript from VoiceGain.

**Returns**: Transcript JSON data

### `format_transcript(transcript_data)`

Formats the transcript using Azure Function or local formatting.

**Returns**: Formatted transcript string

### `save_transcript_to_blob(transcript_text, audio_path)`

Saves the formatted transcript to Azure Blob Storage.

**File Path**: `autoqa/transcriptFiles/{YYYY-MM-DD}/{sanitized_audio_name}.txt`

### `process_audio_file(item, sas_token)`

Processes a single audio file through the complete workflow.

**Returns**: `True` if successful, `False` otherwise

## Error Handling

- **Rate Limiting (429)**: Skips the request and logs a message
- **Transcription Errors**: Detected via `phase == "ERROR"`, marks as failed
- **Timeouts**: Max 60 iterations (20 minutes), marks as timeout
- **General Exceptions**: Caught and logged per audio file, workflow continues

## Output Structure

### Blob Storage Path

```
autoqa/
└── transcriptFiles/
    └── {YYYY-MM-DD}/
        └── {sanitized_audio_path}.txt
```

Example: `autoqa/transcriptFiles/2025-11-12/path_to_audio_file.txt`

### Transcript Format

**With Utterances** (preferred):
```
[0.00s] Speaker 1: Hello, how can I help you today?
[3.45s] Speaker 2: I'm calling about my account.
[7.89s] Speaker 1: Sure, let me look that up for you.
```

**With Words** (fallback):
```
Speaker 1: Hello how can I help you today
Speaker 2: I'm calling about my account
Speaker 1: Sure let me look that up for you
```

## Differences from Logic App

1. **Error Handling**: More granular exception handling in Python
2. **Logging**: Console output instead of Logic App execution history
3. **Formatting Fallback**: Local formatting when Azure Function is unavailable
4. **Type Safety**: Type hints for better code clarity
5. **Modularity**: Methods can be called independently

## Monitoring

The script provides detailed console output:

```
Starting transcription workflow...
Company GUID: 872F9103-326F-47C5-A3C2-566565F2F541
Evaluation Date: 2025-10-12
Found 15 audio files to process

============================================================
Processing 1/15
============================================================

Processing audio: recordings/2025-10-12/call001.wav
Session URL: https://api.voicegain.ai/v1/...
Polling iteration 1/60: Phase = QUEUED
Polling iteration 2/60: Phase = TRANSCRIBING
Polling iteration 3/60: Phase = DONE
Transcript saved to: autoqa/transcriptFiles/2025-11-12/recordings_2025-10-12_call001.txt
Successfully processed: recordings/2025-10-12/call001.wav

...

============================================================
Workflow completed!
Successful: 14
Failed: 1
============================================================
```

## Performance Considerations

- **Sequential Processing**: Processes one audio file at a time (matches Logic App concurrency = 1)
- **Polling Interval**: 20 seconds between status checks
- **Timeout**: 20 minutes per audio file (60 iterations × 20 seconds)
- **Total Time**: For 100 audio files at ~5 minutes each = ~8.5 hours

### Optimization Options

To speed up processing (requires code modification):

1. **Parallel Processing**: Use `concurrent.futures` or `asyncio`
2. **Reduce Polling Interval**: Change `delay_seconds` to 10-15 seconds
3. **Batch Submission**: Submit multiple files before polling

## Troubleshooting

### ODBC Driver Not Found

```bash
# Windows
# Download from Microsoft: https://docs.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server

# Ubuntu/Debian
sudo apt-get install unixodbc-dev
sudo apt-get install msodbcsql17

# Mac
brew install unixodbc
```

### Connection String Issues

Test your connection string:

```python
import pyodbc
conn = pyodbc.connect(SQL_CONNECTION_STRING)
print("Connection successful!")
```

### Blob Storage Issues

Verify container exists:

```python
from azure.storage.blob import BlobServiceClient

client = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
container_client = client.get_container_client("autoqa")
print(container_client.exists())
```

### VoiceGain API Issues

Test authentication:

```python
import requests
headers = {"Authorization": f"Bearer {VOICEGAIN_TOKEN}"}
response = requests.get("https://api.voicegain.ai/v1/asr/transcribe", headers=headers)
print(response.status_code)  # Should be 200
```

## Security Notes

⚠️ **Do not commit credentials to version control!**

Use environment variables or Azure Key Vault:

```python
import os

VOICEGAIN_TOKEN = os.getenv("VOICEGAIN_TOKEN")
SQL_CONNECTION_STRING = os.getenv("SQL_CONNECTION_STRING")
BLOB_CONNECTION_STRING = os.getenv("BLOB_CONNECTION_STRING")
```

## License

This implementation is based on the Azure Logic App workflow definition provided.

