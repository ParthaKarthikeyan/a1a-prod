# Azure Blob Transcription Processor

This script connects to Azure Blob Storage, processes audio files through the transcription workflow, and saves transcripts to a "Transcripts" folder in the same blob storage.

## Features

- Connects to Azure Blob Storage using connection string
- Lists audio files from specified container/folder
- Processes audio files through VoiceGain transcription API
- Automatically generates blob URLs with SAS tokens for audio file access
- Saves transcripts to "Transcripts" folder in the same blob storage
- Provides detailed logging and progress tracking

## Prerequisites

1. **Python packages** (install from `amp_transcript/requirements.txt`):
   ```bash
   pip install azure-storage-blob requests
   ```

2. **VoiceGain API Token**: You need a VoiceGain bearer token for transcription

## Configuration

### Required Environment Variables

- `BLOB_CONNECTION_STRING`: Azure Blob Storage connection string (required)
  - Get this from Azure Portal > Storage Account > Access Keys
  - Format: `DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;BlobEndpoint=...;`
  
- `VOICEGAIN_TOKEN`: Your VoiceGain API bearer token (required)
  - Get this from your VoiceGain account

### Optional Environment Variables

- `BLOB_CONTAINER_NAME`: Container name (default: "autoqa")
- `SOURCE_PREFIX`: Folder/prefix to process (default: "" = all files)
- `SAS_TOKEN`: Optional SAS token for audio file access (auto-generated if not provided)
- `AUDIO_BASE_URL`: Optional base URL for constructing audio URLs
- `AZURE_FUNCTION_URL`: Optional Azure Function URL for transcript formatting

## Usage

### Basic Usage

1. Set the required environment variables:
   ```bash
   # Windows
   set BLOB_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;BlobEndpoint=...;
   set VOICEGAIN_TOKEN=your_token_here
   
   # Linux/Mac
   export BLOB_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;BlobEndpoint=...;"
   export VOICEGAIN_TOKEN=your_token_here
   ```

2. Run the script:
   ```bash
   python blob_transcription_processor.py
   ```

### Process Specific Folder

To process files from a specific folder in the blob:

```bash
# Windows
set SOURCE_PREFIX=recordings/2025-01-15
set VOICEGAIN_TOKEN=your_token_here
python blob_transcription_processor.py

# Linux/Mac
export SOURCE_PREFIX=recordings/2025-01-15
export VOICEGAIN_TOKEN=your_token_here
python blob_transcription_processor.py
```

### Specify Container Name

```bash
# Windows
set BLOB_CONTAINER_NAME=mycontainer
set VOICEGAIN_TOKEN=your_token_here
python blob_transcription_processor.py

# Linux/Mac
export BLOB_CONTAINER_NAME=mycontainer
export VOICEGAIN_TOKEN=your_token_here
python blob_transcription_processor.py
```

## How It Works

1. **Connection**: Connects to Azure Blob Storage using the connection string (hardcoded in the script)

2. **Discovery**: Lists all audio files (`.wav`, `.mp3`, `.m4a`) from the specified container/folder

3. **URL Generation**: Automatically generates blob URLs with SAS tokens for each audio file so VoiceGain can access them

4. **Transcription**: For each audio file:
   - Submits to VoiceGain API for transcription
   - Polls for completion (every 20 seconds, max 60 iterations = 20 minutes)
   - Retrieves the transcript
   - Formats the transcript

5. **Output**: Saves formatted transcripts to the "Transcripts" folder in the same blob storage

## Output Structure

Transcripts are saved to:
```
{container_name}/
└── Transcripts/
    └── {sanitized_audio_filename}.txt
```

Example:
- Input: `recordings/2025-01-15/call_001.wav`
- Output: `Transcripts/recordings_2025-01-15_call_001.txt`

## Script Structure

- `blob_transcription_processor.py`: Main script
- Uses `TranscriptionWorkflow` class from `amp_transcript/function_app.py`
- Extends the workflow to save to "Transcripts" folder

## Error Handling

- Rate limiting (HTTP 429): Logs warning and continues
- Transcription errors: Logs error and continues with next file
- Timeouts: Logs timeout after 20 minutes and continues
- Connection errors: Logs error and stops

## Logging

The script provides detailed console output:
- Progress for each file
- Success/failure status
- Final summary with counts

Example output:
```
================================================================================
Azure Blob Transcription Processor
================================================================================
Container: autoqa
Source prefix: (root)
Output folder: Transcripts
================================================================================

Found 5 audio files

================================================================================
Processing 1/5
================================================================================
Audio file: recordings/2025-01-15/call_001.wav
Generated blob URL for audio file
✓ Successfully processed: recordings/2025-01-15/call_001.wav
  Transcript saved to: Transcripts/recordings_2025-01-15_call_001.txt

...

================================================================================
Processing Complete!
================================================================================
Total files: 5
Successful: 4
Failed: 1
================================================================================
```

## Notes

- The Azure Blob Storage connection string is hardcoded in the script (as provided)
- Transcripts are saved with `.txt` extension
- File paths are sanitized (replacing `/` and `\` with `_`)
- The script processes files sequentially (one at a time)
- SAS tokens are auto-generated if not provided (valid for 24 hours)

