"""
Debug script to test transcription with local audio files
and inspect the transcript data in detail.
"""

import os
import sys
import json
import logging
from pathlib import Path

# Add amp_transcript to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'amp_transcript'))

from function_app import TranscriptionWorkflow

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
VOICEGAIN_TOKEN = os.getenv(
    "VOICEGAIN_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJiOWE4Yzc4ZS1hNjU3LTRiNDItOGRmYy03NzgxOTkwYzJiMzEiLCJhdWQiOiJodHRwczovL2FwaS52b2ljZWdhaW4uYWkvdjEiLCJzdWIiOiI4Y2M0YjU3Yy0wYjdhLTQ0NDItOTkzOC0zMzg3MTc1OTA1YmMifQ.u0MXajHy51MzTfUl6RtabHMP-TRSxsZRjGfNsVtecIs"
)

def test_local_file_transcription(audio_file_path: str):
    """Test transcription with a local audio file"""
    
    audio_path = Path(audio_file_path)
    if not audio_path.exists():
        logger.error(f"Audio file not found: {audio_file_path}")
        return
    
    logger.info("="*80)
    logger.info(f"Testing transcription for: {audio_path.name}")
    logger.info("="*80)
    
    # Initialize workflow (no blob connection needed for local testing)
    workflow = TranscriptionWorkflow(
        voicegain_bearer_token=VOICEGAIN_TOKEN,
        blob_connection_string=None,  # Not needed for local testing
        azure_function_url=None
    )
    
    # For local files, we need to upload to a publicly accessible URL
    # For now, let's test with a blob URL if available, or we need to upload first
    # Actually, let's check if we can use a file:// URL or need to upload to blob first
    
    logger.info("Note: VoiceGain requires a publicly accessible URL.")
    logger.info("For local files, you need to either:")
    logger.info("  1. Upload to blob storage first")
    logger.info("  2. Use a local server with public access")
    logger.info("  3. Test with files already in blob storage")
    logger.info("")
    
    # Let's test the transcript retrieval and formatting with a mock response
    # or test with an actual blob URL
    
    # For debugging, let's create a test that shows what happens with transcript data
    test_transcript_data = {
        "utterances": [
            {
                "speakerId": "1",
                "start": 0,
                "transcript": "Hello, this is a test."
            },
            {
                "speakerId": "2", 
                "start": 3000,
                "transcript": "How are you today?"
            }
        ]
    }
    
    logger.info("Testing transcript formatting with sample data:")
    logger.info(f"Raw transcript data: {json.dumps(test_transcript_data, indent=2)}")
    
    formatted = workflow._format_transcript_locally(test_transcript_data)
    logger.info("")
    logger.info("Formatted transcript:")
    logger.info("-" * 80)
    logger.info(formatted)
    logger.info("-" * 80)
    logger.info("")
    
    # Now let's test with actual blob file if available
    # Or we can upload the local file to blob and test
    
    return formatted


def test_blob_file_transcription(blob_connection_string: str, container_name: str, blob_name: str):
    """Test transcription with a file from blob storage"""
    
    logger.info("="*80)
    logger.info(f"Testing transcription for blob: {blob_name}")
    logger.info("="*80)
    
    # Initialize workflow
    workflow = TranscriptionWorkflow(
        voicegain_bearer_token=VOICEGAIN_TOKEN,
        blob_connection_string=blob_connection_string,
        blob_container_name=container_name
    )
    
    # Create item dict
    item = {
        "audiopath": blob_name,
        "audio_url": None
    }
    
    # Generate blob URL
    from blob_transcription_processor import generate_blob_url
    audio_url = generate_blob_url(
        connection_string=blob_connection_string,
        container_name=container_name,
        blob_name=blob_name
    )
    item["audio_url"] = audio_url
    
    logger.info(f"Audio URL: {audio_url}")
    logger.info("")
    
    # Process the file step by step to see what's happening
    logger.info("Submitting transcription request...")
    
    # Step 1: Submit request
    transcription_response = workflow.submit_transcription_request(item["audio_url"])
    if transcription_response is None:
        logger.error("Transcription request was rate limited or failed")
        return
    
    logger.info(f"Transcription response: {json.dumps(transcription_response, indent=2)}")
    session_url = transcription_response["sessions"][0]["sessionUrl"]
    logger.info(f"Session URL: {session_url}")
    logger.info("")
    
    # Step 2: Poll for status
    logger.info("Polling for transcription status...")
    results_phase, status = workflow.poll_transcription_status(session_url, max_iterations=10, delay_seconds=5)
    logger.info(f"Results phase: {results_phase}, Status: {status}")
    logger.info("")
    
    # Step 3: Check session details
    import requests
    headers = {"Authorization": f"Bearer {VOICEGAIN_TOKEN}"}
    session_response = requests.get(session_url, headers=headers, timeout=30)
    session_data = session_response.json()
    logger.info("Session data:")
    logger.info(json.dumps(session_data, indent=2))
    logger.info("")
    
    if status in {"fail", "timeout"}:
        logger.error(f"Transcription failed with status: {status}")
        logger.info("Checking for error details in session data...")
        if "error" in session_data:
            logger.error(f"Error: {session_data['error']}")
        if "progress" in session_data:
            progress = session_data.get("progress", {})
            logger.info(f"Progress details: {json.dumps(progress, indent=2)}")
        return
    
    # Step 4: Get transcript - but check if it exists first
    logger.info("Getting transcript...")
    try:
        transcript_data = workflow.get_transcript(session_url)
        logger.info("Raw transcript data:")
        logger.info(json.dumps(transcript_data, indent=2))
        logger.info("")
        
        # Check if transcript data is empty
        has_utterances = "utterances" in transcript_data and len(transcript_data.get("utterances", [])) > 0
        has_words = "words" in transcript_data and len(transcript_data.get("words", [])) > 0
        
        logger.info(f"Has utterances: {has_utterances} (count: {len(transcript_data.get('utterances', []))})")
        logger.info(f"Has words: {has_words} (count: {len(transcript_data.get('words', []))})")
        
        if not has_utterances and not has_words:
            logger.warning("WARNING: Transcript data appears to be empty!")
            logger.info("Checking full session response for transcript data...")
            # Sometimes transcript might be in the session response itself
            if "result" in session_data:
                result = session_data.get("result", {})
                logger.info(f"Result section: {json.dumps(result, indent=2)}")
        
        # Step 5: Format transcript
        logger.info("Formatting transcript...")
        formatted_transcript = workflow.format_transcript(transcript_data)
        logger.info(f"Formatted transcript length: {len(formatted_transcript)} characters")
        logger.info("Formatted transcript:")
        logger.info("-" * 80)
        if len(formatted_transcript) > 0:
            logger.info(formatted_transcript)
        else:
            logger.warning("FORMATTED TRANSCRIPT IS EMPTY!")
        logger.info("-" * 80)
    except Exception as e:
        logger.error(f"Error getting/formatting transcript: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Now process normally to save
    result = workflow.process_audio_file(item=item)
    
    logger.info("")
    logger.info("="*80)
    logger.info("Final Transcription Result:")
    logger.info("="*80)
    logger.info(f"Success: {result.get('success')}")
    logger.info(f"Status: {result.get('status')}")
    logger.info(f"Error: {result.get('error')}")
    logger.info(f"Transcript blob path: {result.get('transcript_blob_path')}")
    logger.info("")
    
    # If successful, let's download and inspect the transcript
    if result.get('success') and result.get('transcript_blob_path'):
        from azure.storage.blob import BlobServiceClient
        blob_service_client = BlobServiceClient.from_connection_string(blob_connection_string)
        container_client = blob_service_client.get_container_client(container_name)
        blob_client = container_client.get_blob_client(result.get('transcript_blob_path'))
        
        transcript_content = blob_client.download_blob().content_as_text()
        
        logger.info("="*80)
        logger.info("Downloaded Transcript Content:")
        logger.info("="*80)
        logger.info(f"Length: {len(transcript_content)} characters")
        logger.info(f"Content preview (first 500 chars):")
        logger.info("-" * 80)
        logger.info(transcript_content[:500])
        logger.info("-" * 80)
        
        if len(transcript_content) == 0:
            logger.error("WARNING: Transcript is empty!")
            logger.info("")
            logger.info("Let's check the raw transcript data from VoiceGain...")
            
            # Try to get the raw transcript data
            if hasattr(workflow, 'session_url') and workflow.session_url:
                try:
                    raw_transcript = workflow.get_transcript(workflow.session_url)
                    logger.info("")
                    logger.info("Raw transcript data from VoiceGain:")
                    logger.info(json.dumps(raw_transcript, indent=2))
                except Exception as e:
                    logger.error(f"Error getting raw transcript: {e}")
    
    return result


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Debug transcription process")
    parser.add_argument("--local-file", type=str, help="Path to local audio file")
    parser.add_argument("--blob-file", type=str, help="Blob name to test")
    parser.add_argument("--container", type=str, default="audiofiles", help="Container name")
    
    args = parser.parse_args()
    
    if args.local_file:
        test_local_file_transcription(args.local_file)
    elif args.blob_file:
        BLOB_CONNECTION_STRING = os.getenv("BLOB_CONNECTION_STRING")
        if not BLOB_CONNECTION_STRING:
            logger.error("BLOB_CONNECTION_STRING environment variable required for blob testing")
            sys.exit(1)
        test_blob_file_transcription(BLOB_CONNECTION_STRING, args.container, args.blob_file)
    else:
        # Test with one of the local files - but we need blob access
        logger.info("No file specified. Testing with a blob file...")
        logger.info("Usage:")
        logger.info("  python test_transcription_debug.py --blob-file <blob_name>")
        logger.info("  python test_transcription_debug.py --local-file <local_path>")

