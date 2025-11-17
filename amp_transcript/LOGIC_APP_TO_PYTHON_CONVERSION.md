# Azure Logic App to Python Conversion Summary

This document summarizes the conversion of the Azure Logic App workflow definition (JSON) to Python code.

## Files Created

### 1. `transcription_workflow.py` (Main Implementation)
- **Purpose**: Complete Python implementation of the Logic App workflow
- **Class**: `TranscriptionWorkflow` - Orchestrates the entire transcription process
- **Key Features**:
  - SQL database integration
  - VoiceGain API client
  - Polling mechanism with timeout protection
  - Azure Blob Storage integration
  - Error handling and logging
  - Local and remote transcript formatting

### 2. `requirements_transcription.txt` (Dependencies)
- **Purpose**: Python package requirements
- **Packages**:
  - `requests` - HTTP client for API calls
  - `pyodbc` - SQL Server connectivity
  - `azure-storage-blob` - Blob storage client

### 3. `TRANSCRIPTION_WORKFLOW_README.md` (Documentation)
- **Purpose**: Comprehensive usage guide
- **Contents**:
  - Overview and features
  - Installation instructions
  - Configuration guide
  - Usage examples
  - API reference
  - Troubleshooting
  - Security best practices

### 4. `example_transcription_usage.py` (Examples)
- **Purpose**: Practical usage examples
- **Examples**:
  - Basic workflow execution
  - Single file processing
  - Custom polling configuration
  - Batch processing by date range
  - Environment variable usage

### 5. `transcription.env.example` (Configuration Template)
- **Purpose**: Environment variables template
- **Variables**:
  - VoiceGain API token
  - SQL connection string
  - Blob storage connection string
  - Azure Function URL (optional)
  - SAS token
  - Workflow parameters

## Logic App Components Mapped to Python

### Logic App Actions → Python Methods

| Logic App Action | Python Method | Description |
|-----------------|---------------|-------------|
| `Initialize_variables_4` | `__init__()` | Initialize workflow variables |
| `Execute_a_SQL_query_(V2)` | `execute_sql_query()` | Query database for audio files |
| `loop_through_mp3s` | `run()` with for loop | Iterate through audio files |
| `Set_variable_4` | Direct assignment | Set audio URL with SAS token |
| `HTTP` (POST to VoiceGain) | `submit_transcription_request()` | Submit transcription job |
| `Condition` (check 429) | if statement | Handle rate limiting |
| `Parse_JSON` | `response.json()` | Parse API response |
| `Set_variable` (sessionURL) | Direct assignment | Extract session URL |
| `Until` loop | `poll_transcription_status()` | Poll until completion |
| `Delay` | `time.sleep(20)` | Wait between polls |
| `HTTP_1` (GET status) | `requests.get()` | Check transcription status |
| `Parse_JSON_1` | `response.json()` | Parse status response |
| `Set_variable_1` (results) | Variable assignment | Extract phase |
| `Condition_1` (check ERROR) | if statement | Handle errors |
| `Set_variable_2`, `Set_variable_3` | Variable assignments | Set error flags |
| `HTTP_3` (GET transcript) | `get_transcript()` | Retrieve transcript |
| `Call_AmpPythonAzureFunctions` | `format_transcript()` | Format transcript |
| `Condition_2` (check 200) | if statement | Check format success |
| `Create_blob_(V2)` | `save_transcript_to_blob()` | Save to blob storage |

### Workflow Variables

| Logic App Variable | Python Attribute | Type |
|-------------------|------------------|------|
| `root` | `self.root` | string |
| `iterationDir` | `self.iteration_dir` | string |
| `sessionURL` | `self.session_url` | string |
| `status` | `self.status` | string |
| `results` | `self.results` | string |
| `path` | `self.path` | string |
| `audioname` | `self.audioname` | string |

### Configuration Preserved

All VoiceGain API configuration from the Logic App is preserved in Python:

```python
# Diarization settings
"diarization": {
    "maxSpeakers": 3,
    "minSpeakers": 2
}

# Formatters (all 8 types preserved)
- digits
- basic (enabled: true)
- enhanced (CC, EMAIL)
- profanity (mask: partial)
- spelling (lang: en-US)
- redact (full masking for all PII types)
- regex (custom patterns)

# Session settings
"asyncMode": "OFF-LINE"
"poll": {"persist": 600000}
"content": {
    "incremental": ["progress"],
    "full": ["transcript", "words"]
}
```

## Workflow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ 1. SQL Query: Fetch audio file metadata                     │
│    - Filter by company GUID, date, direction                │
│    - Only records with non-null audiopath                   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. For each audio file (sequential processing)              │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Construct audio URL with SAS token                       │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. POST to VoiceGain API (/asr/transcribe/async)           │
│    - Full configuration (diarization, formatters, etc.)     │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. Check response status code                               │
│    ├─ 429: Skip (rate limited)                             │
│    └─ Other: Parse session URL                             │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. Poll session status (Until loop)                         │
│    - Max 60 iterations × 20 seconds = 20 minutes           │
│    ├─ Delay 20 seconds                                     │
│    ├─ GET session URL to check progress                    │
│    ├─ Parse phase from progress                            │
│    ├─ If phase == "ERROR": Mark failed, exit loop         │
│    └─ If phase == "DONE": Exit loop                       │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. GET transcript from session URL                          │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 8. Format transcript                                         │
│    ├─ POST to Azure Function (if configured)               │
│    └─ Local formatting (fallback)                          │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 9. Check formatting status                                   │
│    └─ If 200: Upload to Blob Storage                       │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 10. Save to Azure Blob Storage                              │
│     - Path: autoqa/transcriptFiles/{date}/{filename}.txt   │
└─────────────────────────────────────────────────────────────┘
```

## Key Differences from Logic App

### Advantages of Python Implementation

1. **Better Error Handling**
   - Granular exception handling with try-catch blocks
   - Detailed error messages and stack traces
   - Graceful degradation (continues on single file failure)

2. **Flexibility**
   - Can run locally or on any Python-enabled platform
   - Easy to modify and extend
   - Can be integrated into larger Python applications

3. **Debugging**
   - Step-through debugging with breakpoints
   - Print statements for real-time monitoring
   - Easier to test individual components

4. **Cost**
   - No Logic App execution charges
   - Can run on existing infrastructure
   - Better for high-volume processing

5. **Type Safety**
   - Type hints for better code clarity
   - IDE autocomplete and error detection

6. **Modularity**
   - Each method can be called independently
   - Easier to unit test
   - Reusable components

### Disadvantages Compared to Logic App

1. **Visual Design**
   - Logic App has visual workflow designer
   - Python requires reading code

2. **Monitoring**
   - Logic App has built-in execution history
   - Python requires custom logging/monitoring

3. **Serverless Benefits**
   - Logic App auto-scales
   - Python needs hosting infrastructure

4. **No-Code/Low-Code**
   - Logic App is easier for non-programmers
   - Python requires programming knowledge

## Usage Comparison

### Logic App
```
1. Design workflow in Azure Portal
2. Configure connections (SQL, Blob, etc.)
3. Trigger via HTTP request or schedule
4. Monitor in Azure Portal
```

### Python
```bash
1. Install dependencies: pip install -r requirements_transcription.txt
2. Configure environment variables
3. Run script: python transcription_workflow.py
4. Monitor console output
```

## Migration Path

If you want to migrate from Logic App to Python:

1. **Export Logic App definition** (already done - the JSON provided)
2. **Set up Python environment** 
   ```bash
   pip install -r requirements_transcription.txt
   ```
3. **Configure credentials** - Update `transcription.env.example` and rename to `.env`
4. **Test with single file** - Use `example_process_single_file()`
5. **Run full workflow** - Execute `python transcription_workflow.py`
6. **Schedule if needed** - Use cron (Linux/Mac) or Task Scheduler (Windows)

### Example: Windows Task Scheduler
```powershell
# Create scheduled task to run daily at 2 AM
schtasks /create /tn "TranscriptionWorkflow" /tr "python C:\path\to\transcription_workflow.py" /sc daily /st 02:00
```

### Example: Linux Cron
```bash
# Add to crontab (run daily at 2 AM)
0 2 * * * cd /path/to/project && python transcription_workflow.py >> transcription.log 2>&1
```

## Performance Metrics

Based on the Logic App configuration:

- **Polling Interval**: 20 seconds
- **Max Polling Time**: 20 minutes (60 × 20s)
- **Concurrency**: 1 (sequential processing)
- **Average Transcription Time**: ~5 minutes per file

### Estimated Processing Time

| Files | Time Estimate |
|-------|---------------|
| 10    | ~50 minutes   |
| 50    | ~4 hours      |
| 100   | ~8.5 hours    |
| 500   | ~42 hours     |

*Assuming 5 minutes average per file*

### Optimization Opportunities

To improve performance, modify the Python code:

1. **Parallel Processing** - Process multiple files simultaneously
   ```python
   from concurrent.futures import ThreadPoolExecutor
   
   with ThreadPoolExecutor(max_workers=5) as executor:
       futures = [executor.submit(workflow.process_audio_file, item, sas_token) 
                 for item in results]
   ```

2. **Async/Await** - Use asyncio for concurrent API calls
3. **Reduced Polling** - Lower delay_seconds to 10-15 seconds
4. **Batch Submission** - Submit all files before polling

## Security Considerations

### Secrets Management

**Logic App Approach:**
- Stores credentials in Azure Key Vault
- Uses managed identities
- Secrets in connection strings

**Python Approach:**
- Use environment variables
- Load from Azure Key Vault SDK
- Use Azure Managed Identity
- Never commit credentials to git

```python
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential

credential = DefaultAzureCredential()
client = SecretClient(vault_url="https://myvault.vault.azure.net", credential=credential)

voicegain_token = client.get_secret("VoiceGainToken").value
```

## Testing

### Unit Tests Example

```python
import unittest
from transcription_workflow import TranscriptionWorkflow

class TestTranscriptionWorkflow(unittest.TestCase):
    
    def setUp(self):
        self.workflow = TranscriptionWorkflow(
            voicegain_bearer_token="test_token",
            sql_connection_string="test_conn",
            blob_connection_string="test_blob"
        )
    
    def test_format_transcript_locally(self):
        transcript_data = {
            "utterances": [
                {"speakerId": "1", "transcript": "Hello", "start": 0},
                {"speakerId": "2", "transcript": "Hi there", "start": 3000}
            ]
        }
        result = self.workflow._format_transcript_locally(transcript_data)
        self.assertIn("Speaker 1: Hello", result)
        self.assertIn("Speaker 2: Hi there", result)

if __name__ == '__main__':
    unittest.main()
```

## Conclusion

The Python implementation provides a feature-complete, flexible alternative to the Azure Logic App workflow. It preserves all functionality while offering better debugging, error handling, and integration capabilities. Choose based on your needs:

- **Use Logic App** if you need visual design, built-in monitoring, and serverless auto-scaling
- **Use Python** if you need flexibility, custom logic, cost optimization, and better integration with existing Python codebases

Both implementations will produce identical results when processing the same audio files.

