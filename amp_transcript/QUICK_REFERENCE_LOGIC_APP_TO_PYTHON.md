# Quick Reference: Logic App to Python

## Side-by-Side Comparison

### Initialize Variables
**Logic App:**
```json
{
  "type": "InitializeVariable",
  "inputs": {
    "variables": [
      {"name": "sessionURL", "type": "string"}
    ]
  }
}
```

**Python:**
```python
self.session_url = ""
```

---

### SQL Query
**Logic App:**
```json
{
  "type": "ApiConnection",
  "inputs": {
    "body": {
      "query": "SELECT * FROM Autoqa_metadata WHERE ..."
    },
    "path": "/v2/datasets/.../query/sql"
  }
}
```

**Python:**
```python
conn = pyodbc.connect(sql_connection_string)
cursor = conn.cursor()
cursor.execute(query, params)
results = cursor.fetchall()
```

---

### HTTP POST Request
**Logic App:**
```json
{
  "type": "Http",
  "inputs": {
    "uri": "https://api.voicegain.ai/v1/asr/transcribe/async",
    "method": "POST",
    "headers": {"Authorization": "Bearer ..."},
    "body": { ... }
  }
}
```

**Python:**
```python
headers = {"Authorization": f"Bearer {token}"}
response = requests.post(
    "https://api.voicegain.ai/v1/asr/transcribe/async",
    headers=headers,
    json=payload
)
```

---

### Conditional Logic
**Logic App:**
```json
{
  "type": "If",
  "expression": {
    "and": [
      {"equals": ["@outputs('HTTP')?['statusCode']", 429]}
    ]
  },
  "actions": { ... },
  "else": { ... }
}
```

**Python:**
```python
if response.status_code == 429:
    # Handle rate limiting
    pass
else:
    # Process normally
    pass
```

---

### Parse JSON
**Logic App:**
```json
{
  "type": "ParseJson",
  "inputs": {
    "content": "@body('HTTP')",
    "schema": { ... }
  }
}
```

**Python:**
```python
data = response.json()
session_url = data["sessions"][0]["sessionUrl"]
```

---

### Set Variable
**Logic App:**
```json
{
  "type": "SetVariable",
  "inputs": {
    "name": "sessionURL",
    "value": "@body('Parse_JSON')?['sessions']?[0]?['sessionUrl']"
  }
}
```

**Python:**
```python
self.session_url = data["sessions"][0]["sessionUrl"]
```

---

### Until Loop (Polling)
**Logic App:**
```json
{
  "type": "Until",
  "expression": "@equals(variables('results'), 'DONE')",
  "limit": {"count": 60, "timeout": "PT1H"},
  "actions": {
    "Delay": {
      "type": "Wait",
      "inputs": {"interval": {"count": 20, "unit": "Second"}}
    },
    "HTTP_1": { ... }
  }
}
```

**Python:**
```python
results = ""
iteration = 0
while results != "DONE" and iteration < 60:
    time.sleep(20)
    response = requests.get(session_url, headers=headers)
    data = response.json()
    results = data["progress"]["phase"]
    iteration += 1
```

---

### For Each Loop
**Logic App:**
```json
{
  "type": "Foreach",
  "foreach": "@body('Execute_a_SQL_query_(V2)')?['resultsets']?['Table1']",
  "actions": { ... },
  "runtimeConfiguration": {
    "concurrency": {"repetitions": 1}
  }
}
```

**Python:**
```python
for item in sql_results:
    # Process each item sequentially
    process_audio_file(item)
```

---

### Create Blob
**Logic App:**
```json
{
  "type": "ApiConnection",
  "inputs": {
    "body": "@body('Call_AmpPythonAzureFunctions-fromat_audio')",
    "path": "/v2/datasets/.../files",
    "queries": {
      "folderPath": "/autoqa/transcriptFiles/@{formatDateTime(utcNow(), 'yyyy-MM-dd')}/",
      "name": "@{...}.txt"
    }
  }
}
```

**Python:**
```python
from azure.storage.blob import BlobServiceClient
from datetime import datetime

blob_service_client = BlobServiceClient.from_connection_string(conn_str)
container_client = blob_service_client.get_container_client("autoqa")

today = datetime.utcnow().strftime('%Y-%m-%d')
blob_path = f"autoqa/transcriptFiles/{today}/{filename}.txt"
blob_client = container_client.get_blob_client(blob_path)
blob_client.upload_blob(content, overwrite=True)
```

---

### Call Azure Function
**Logic App:**
```json
{
  "type": "Function",
  "inputs": {
    "method": "POST",
    "body": "@body('HTTP_3')",
    "function": {"connectionName": "azureFunctionOperation"}
  }
}
```

**Python:**
```python
response = requests.post(
    azure_function_url,
    json=transcript_data
)
formatted_text = response.text
```

---

## Expression Mappings

| Logic App Expression | Python Equivalent |
|---------------------|-------------------|
| `@variables('name')` | `self.name` |
| `@body('HTTP')` | `response.json()` |
| `@outputs('HTTP')?['statusCode']` | `response.status_code` |
| `@item()?['audiopath']` | `item['audiopath']` |
| `@equals(var, 'value')` | `var == 'value'` |
| `@formatDateTime(utcNow(), 'yyyy-MM-dd')` | `datetime.utcnow().strftime('%Y-%m-%d')` |
| `@replace(str, '/', '_')` | `str.replace('/', '_')` |
| `@encodeURIComponent(str)` | `urllib.parse.quote(str)` |
| `@body('Parse')?['sessions']?[0]` | `data.get('sessions', [{}])[0]` |

---

## Common Patterns

### Error Handling

**Logic App:**
```json
{
  "runAfter": {
    "HTTP": ["FAILED", "TIMEDOUT"]
  },
  "type": "Compose",
  "inputs": "@outputs('HTTP')"
}
```

**Python:**
```python
try:
    response = requests.post(url, json=data)
    response.raise_for_status()
except requests.exceptions.RequestException as e:
    print(f"Error: {e}")
    # Handle error
```

---

### Retry Logic

**Logic App:**
```json
{
  "retryPolicy": {
    "type": "exponential",
    "count": 3,
    "interval": "PT10S"
  }
}
```

**Python:**
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=10))
def make_request():
    return requests.post(url, json=data)
```

Or manual:
```python
max_retries = 3
for attempt in range(max_retries):
    try:
        response = requests.post(url, json=data)
        break
    except Exception as e:
        if attempt == max_retries - 1:
            raise
        time.sleep(10 * (2 ** attempt))  # Exponential backoff
```

---

### Parallel Processing

**Logic App:**
```json
{
  "runtimeConfiguration": {
    "concurrency": {"repetitions": 10}
  }
}
```

**Python:**
```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(process_item, item) for item in items]
    results = [f.result() for f in futures]
```

---

## Data Access Patterns

### Safe Navigation (Optional Chaining)

**Logic App:**
```
@body('Parse_JSON')?['sessions']?[0]?['sessionUrl']
```

**Python:**
```python
# Option 1: Using get()
session_url = data.get('sessions', [{}])[0].get('sessionUrl')

# Option 2: Try-except
try:
    session_url = data['sessions'][0]['sessionUrl']
except (KeyError, IndexError):
    session_url = None

# Option 3: Using a helper function
def safe_get(data, *keys):
    for key in keys:
        try:
            if isinstance(key, int):
                data = data[key]
            else:
                data = data[key]
        except (KeyError, IndexError, TypeError):
            return None
    return data

session_url = safe_get(data, 'sessions', 0, 'sessionUrl')
```

---

## Environment & Configuration

### Logic App Connections

**Logic App:**
- Configured in Azure Portal
- Uses managed connections
- Stored in connection strings

**Python:**
```python
# Use environment variables
import os
from dotenv import load_dotenv

load_dotenv()

SQL_CONN = os.getenv('SQL_CONNECTION_STRING')
BLOB_CONN = os.getenv('BLOB_CONNECTION_STRING')
API_KEY = os.getenv('VOICEGAIN_TOKEN')
```

---

## Complete Workflow Skeleton

**Logic App Structure:**
```
Initialize Variables
  ↓
Execute SQL Query
  ↓
For Each Record
  ├─ Set Variables
  ├─ HTTP POST (Submit)
  ├─ Parse Response
  ├─ Until Loop (Poll)
  │   ├─ Delay
  │   ├─ HTTP GET (Status)
  │   ├─ Parse Status
  │   └─ Check Conditions
  ├─ HTTP GET (Transcript)
  ├─ Call Function (Format)
  └─ Create Blob (Save)
```

**Python Structure:**
```python
class Workflow:
    def __init__(self):
        # Initialize variables
        pass
    
    def execute_sql_query(self):
        # Query database
        pass
    
    def submit_request(self, item):
        # HTTP POST
        pass
    
    def poll_status(self, session_url):
        # Until loop with delay
        pass
    
    def get_transcript(self, session_url):
        # HTTP GET
        pass
    
    def format_transcript(self, data):
        # Call function or local
        pass
    
    def save_to_blob(self, content, path):
        # Create blob
        pass
    
    def process_item(self, item):
        # Orchestrate single item
        url = self.submit_request(item)
        self.poll_status(url)
        transcript = self.get_transcript(url)
        formatted = self.format_transcript(transcript)
        self.save_to_blob(formatted, item['path'])
    
    def run(self):
        # Main workflow
        results = self.execute_sql_query()
        for item in results:
            self.process_item(item)
```

---

## Key Takeaways

1. **Variables**: Logic App variables → Python instance attributes
2. **HTTP Calls**: Logic App HTTP actions → `requests` library
3. **Loops**: Logic App loops → Python `for`/`while` loops
4. **Conditions**: Logic App If actions → Python `if` statements
5. **Delays**: Logic App Wait → `time.sleep()`
6. **JSON**: Logic App Parse → `response.json()`
7. **Connections**: Logic App managed connections → Python SDK clients
8. **Error Handling**: Logic App runAfter → Python try-except

---

## Quick Start Commands

```bash
# Install dependencies
pip install -r requirements_transcription.txt

# Set up environment
cp transcription.env.example .env
# Edit .env with your credentials

# Run workflow
python transcription_workflow.py

# Run with environment variables
export VOICEGAIN_TOKEN="your_token"
export SQL_CONNECTION_STRING="your_conn_string"
python transcription_workflow.py

# Run single example
python example_transcription_usage.py
```

---

## Testing Snippets

### Test SQL Connection
```python
import pyodbc
conn = pyodbc.connect(SQL_CONNECTION_STRING)
cursor = conn.cursor()
cursor.execute("SELECT TOP 1 * FROM Autoqa_metadata")
print(cursor.fetchone())
```

### Test Blob Storage
```python
from azure.storage.blob import BlobServiceClient
client = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
print(client.get_service_properties())
```

### Test VoiceGain API
```python
import requests
headers = {"Authorization": f"Bearer {VOICEGAIN_TOKEN}"}
r = requests.get("https://api.voicegain.ai/v1/asr/transcribe", headers=headers)
print(r.status_code)
```

---

## Resources

- **Logic App Docs**: https://docs.microsoft.com/azure/logic-apps/
- **Python Requests**: https://docs.python-requests.org/
- **Azure SDK for Python**: https://docs.microsoft.com/azure/developer/python/
- **VoiceGain API**: https://docs.voicegain.ai/
- **pyodbc**: https://github.com/mkleehammer/pyodbc

---

*Last Updated: 2025-11-12*

