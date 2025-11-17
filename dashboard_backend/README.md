# Transcription Dashboard - Backend API

Flask backend API for the transcription dashboard React frontend.

## Installation

```bash
pip install -r requirements.txt
```

## Running the API

```bash
python app.py
```

The API will start on http://localhost:5000

## Environment Variables

- `PORT`: Port number (default: 5000)

## API Endpoints

- `GET /api/health` - Health check
- `POST /api/statistics` - Get transcription statistics
- `POST /api/files/pending` - Get pending audio files
- `POST /api/files/processed` - Get processed files
- `POST /api/files/formatted` - Get formatted transcripts
- `POST /api/files/raw` - Get raw transcripts
- `POST /api/recent-activity` - Get recent processing activity

All POST endpoints require JSON body with:
```json
{
  "connection_string": "your_connection_string",
  "container_name": "audiofiles"
}
```

