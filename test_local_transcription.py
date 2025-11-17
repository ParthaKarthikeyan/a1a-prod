"""
Test transcription with local audio files.
Uploads them to blob storage first, then tests transcription.
"""

import os
import sys
import json
import logging
from pathlib import Path

# Add amp_transcript to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'amp_transcript'))

from azure.storage.blob import BlobServiceClient
from function_app import TranscriptionWorkflow

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
VOICEGAIN_TOKEN = os.getenv(
    "VOICEGAIN_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJiOWE4Yzc4ZS1hNjU3LTRiNDItOGRmYy03NzgxOTkwYzJiMzEiLCJhdWQiOiJodHRwczovL2FwaS52b2ljZWdhaW4uYWkvdjEiLCJzdWIiOiI4Y2M0YjU3Yy0wYjdhLTQ0NDItOTkzOC0zMzg3MTc1OTA1YmMifQ.u0MXajHy51MzTfUl6RtabHMP-TRSxsZRjGfNsVtecIs"
)

BLOB_CONNECTION_STRING = os.getenv("BLOB_CONNECTION_STRING")
if not BLOB_CONNECTION_STRING:
    logger.error("BLOB_CONNECTION_STRING environment variable is required")
    sys.exit(1)

CONTAINER_NAME = "audiofiles"
TEST_FOLDER = "test_local"


def upload_local_file_to_blob(local_file_path: str, blob_name: str) -> str:
    """Upload a local file to blob storage and return the blob URL"""
    logger.info(f"Uploading {local_file_path} to blob storage as {blob_name}...")
    
    blob_service_client = BlobServiceClient.from_connection_string(BLOB_CONNECTION_STRING)
    container_client = blob_service_client.get_container_client(CONTAINER_NAME)
    
    # Upload file
    blob_client = container_client.get_blob_client(blob_name)
    with open(local_file_path, "rb") as data:
        blob_client.upload_blob(data, overwrite=True)
    
    logger.info(f"Uploaded to: {blob_name}")
    
    # Generate URL with SAS token
    from blob_transcription_processor import generate_blob_url
    blob_url = generate_blob_url(
        connection_string=BLOB_CONNECTION_STRING,
        container_name=CONTAINER_NAME,
        blob_name=blob_name
    )
    
    return blob_url


def test_transcription_with_local_file(local_file_path: str):
    """Test transcription with a local audio file"""
    
    audio_path = Path(local_file_path)
    if not audio_path.exists():
        logger.error(f"Audio file not found: {local_file_path}")
        return
    
    logger.info("="*80)
    logger.info(f"Testing transcription for local file: {audio_path.name}")
    logger.info("="*80)
    
    # Upload to blob storage
    blob_name = f"{TEST_FOLDER}/{audio_path.name}"
    audio_url = upload_local_file_to_blob(str(audio_path), blob_name)
    logger.info(f"Audio URL: {audio_url}")
    logger.info("")
    
    # Initialize workflow
    workflow = TranscriptionWorkflow(
        voicegain_bearer_token=VOICEGAIN_TOKEN,
        blob_connection_string=BLOB_CONNECTION_STRING,
        blob_container_name=CONTAINER_NAME
    )
    
    # Create item dict
    item = {
        "audiopath": blob_name,
        "audio_url": audio_url
    }
    
    # Step 1: Submit request
    logger.info("Submitting transcription request...")
    transcription_response = workflow.submit_transcription_request(audio_url)
    if transcription_response is None:
        logger.error("Transcription request was rate limited or failed")
        return
    
    session_url = transcription_response["sessions"][0]["sessionUrl"]
    logger.info(f"Session URL: {session_url}")
    logger.info("")
    
    # Step 2: Poll for status
    logger.info("Polling for transcription status...")
    results_phase, status = workflow.poll_transcription_status(session_url, max_iterations=30, delay_seconds=5)
    logger.info(f"Results phase: {results_phase}, Status: {status}")
    logger.info("")
    
    if status in {"fail", "timeout"}:
        logger.error(f"Transcription failed with status: {status}")
        import requests
        headers = {"Authorization": f"Bearer {VOICEGAIN_TOKEN}"}
        session_response = requests.get(session_url, headers=headers, timeout=30)
        session_data = session_response.json()
        if "progress" in session_data:
            progress = session_data.get("progress", {})
            logger.error(f"Error message: {progress.get('message', 'No error message')}")
        return
    
    # Step 3: Get transcript
    logger.info("Getting transcript...")
    transcript_data = workflow.get_transcript(session_url)
    
    logger.info("="*80)
    logger.info("RAW TRANSCRIPT DATA STRUCTURE:")
    logger.info("="*80)
    logger.info(f"Type: {type(transcript_data)}")
    if isinstance(transcript_data, list):
        logger.info(f"List length: {len(transcript_data)}")
        if len(transcript_data) > 0:
            logger.info(f"First item type: {type(transcript_data[0])}")
            logger.info(f"First item keys: {list(transcript_data[0].keys()) if isinstance(transcript_data[0], dict) else 'N/A'}")
    elif isinstance(transcript_data, dict):
        logger.info(f"Dict keys: {list(transcript_data.keys())}")
    
    logger.info("")
    logger.info("Full transcript data (first 3000 chars):")
    logger.info("-" * 80)
    transcript_json = json.dumps(transcript_data, indent=2)
    logger.info(transcript_json[:3000])
    if len(transcript_json) > 3000:
        logger.info(f"... (truncated, total length: {len(transcript_json)} chars)")
    logger.info("-" * 80)
    logger.info("")
    
    # Step 4: Format transcript
    logger.info("Formatting transcript...")
    formatted_transcript = workflow.format_transcript(transcript_data)
    logger.info(f"Formatted transcript length: {len(formatted_transcript)} characters")
    logger.info("")
    logger.info("="*80)
    logger.info("FORMATTED TRANSCRIPT:")
    logger.info("="*80)
    if len(formatted_transcript) > 0:
        logger.info(formatted_transcript)
    else:
        logger.warning("FORMATTED TRANSCRIPT IS EMPTY!")
    logger.info("="*80)
    
    # Save to local file for inspection
    output_file = audio_path.parent / f"{audio_path.stem}_transcript.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(formatted_transcript)
    logger.info(f"")
    logger.info(f"Transcript saved to: {output_file}")
    
    # Also save raw JSON
    json_file = audio_path.parent / f"{audio_path.stem}_transcript_raw.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(transcript_data, f, indent=2)
    logger.info(f"Raw transcript JSON saved to: {json_file}")


if __name__ == "__main__":
    # Find local audio files
    script_dir = Path(__file__).parent
    audio_files = list(script_dir.glob("*.wav"))
    
    if not audio_files:
        logger.error("No .wav files found in the script directory")
        logger.info(f"Looking in: {script_dir}")
        sys.exit(1)
    
    logger.info(f"Found {len(audio_files)} audio file(s):")
    for f in audio_files:
        logger.info(f"  - {f.name}")
    logger.info("")
    
    # Test with first file
    test_file = audio_files[0]
    logger.info(f"Testing with: {test_file.name}")
    logger.info("")
    
    test_transcription_with_local_file(str(test_file))
    
    if len(audio_files) > 1:
        logger.info("")
        logger.info(f"To test with other files, run:")
        logger.info(f"  python test_local_transcription.py")

