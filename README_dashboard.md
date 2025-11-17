# Transcription Dashboard

A Streamlit dashboard to monitor transcription processing progress, statistics, and file status.

## Features

- **Real-time Statistics**: View total files, processed files, pending files, and transcript counts
- **Progress Tracking**: Visual progress bar showing processing completion percentage
- **File Lists**: Browse pending, processed, and transcript files
- **Recent Activity**: See recently processed files with timestamps
- **Auto Refresh**: Automatically refresh the dashboard at configurable intervals

## Installation

1. Install required packages:
   ```bash
   pip install -r requirements_dashboard.txt
   ```

## Usage

1. Set environment variables (optional, or enter in dashboard):
   ```bash
   # Windows
   set BLOB_CONNECTION_STRING=your_connection_string
   set BLOB_CONTAINER_NAME=audiofiles
   
   # Linux/Mac
   export BLOB_CONNECTION_STRING=your_connection_string
   export BLOB_CONTAINER_NAME=audiofiles
   ```

2. Run the dashboard:
   ```bash
   streamlit run transcription_dashboard.py
   ```

3. The dashboard will open in your browser (usually at http://localhost:8501)

## Dashboard Sections

### Statistics Cards
- **Total Audio Files**: All audio files in the container
- **Processed Files**: Files moved to Processed folder
- **Formatted Transcripts**: Count of formatted .txt files
- **Raw Transcripts**: Count of raw .json files

### Processing Progress
- Visual progress bar showing completion percentage
- Processed vs Total file counts

### Statistics Table
- Detailed metrics including success rate
- File counts by category

### Recent Activity
- Shows the 5 most recently processed files
- Displays time since processing

### File Lists Tabs
- **Pending Files**: Audio files waiting to be processed
- **Processed Files**: Successfully processed audio files
- **Transcripts**: Both formatted and raw transcript files

## Configuration

Use the sidebar to:
- Enter/update blob connection string
- Set container name
- Enable/disable auto-refresh
- Adjust refresh interval (5-300 seconds)
- Manually refresh the dashboard

## Notes

- The dashboard reads directly from Azure Blob Storage
- Auto-refresh will reload the page at the specified interval
- File lists show up to 100-500 most recent items
- All timestamps are in UTC

