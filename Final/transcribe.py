"""
Simple Standalone Transcription Script

This script processes audio files from Azure Blob Storage through VoiceGain
and saves transcripts. No dashboard, no complex setup - just run it.

Configuration: Edit the values at the top of this file.
"""

import os
import sys
import logging
import time
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from threading import Lock

# ============================================================================
# CONFIGURATION - Edit these values
# ============================================================================

# Azure Blob Storage connection string
BLOB_CONNECTION_STRING = "YOUR_CONNECTION_STRING_HERE"

# VoiceGain API token
VOICEGAIN_TOKEN = "YOUR_VOICEGAIN_TOKEN_HERE"

# Azure Blob Storage container name
CONTAINER_NAME = "audiofiles"

# Maximum number of files to process (None = process all files)
MAX_FILES = None  # Set to a number like 10000 to limit processing

# ============================================================================
# RATE LIMITING CONFIGURATION
# ============================================================================

# Rate limit: 3750 files per hour
MAX_FILES_PER_HOUR = 3750
SECONDS_PER_HOUR = 3600
MIN_DELAY_BETWEEN_SUBMISSIONS = max(1.0, SECONDS_PER_HOUR / MAX_FILES_PER_HOUR)

# Rate limiter state
_rate_limiter_lock = Lock()
_submission_times = []


# ============================================================================
# SETUP LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


# ============================================================================
# RATE LIMITING FUNCTION
# ============================================================================

def wait_for_rate_limit():
    """Wait if necessary to respect rate limit of 3750 files/hour"""
    global _submission_times
    
    with _rate_limiter_lock:
        now = time.time()
        # Remove timestamps older than 1 hour
        _submission_times = [t for t in _submission_times if now - t < SECONDS_PER_HOUR]
        
        # If we've hit the limit, wait until oldest submission is 1 hour old
        if len(_submission_times) >= MAX_FILES_PER_HOUR:
            oldest_time = min(_submission_times)
            wait_time = SECONDS_PER_HOUR - (now - oldest_time) + 1  # Add 1 second buffer
            if wait_time > 0:
                logger.info(f"Rate limit reached ({len(_submission_times)}/{MAX_FILES_PER_HOUR} per hour). Waiting {wait_time:.1f}s...")
                time.sleep(wait_time)
                # Clean up again after waiting
                now = time.time()
                _submission_times = [t for t in _submission_times if now - t < SECONDS_PER_HOUR]
        
        # Add current submission time
        _submission_times.append(time.time())
        
        # Small delay between submissions to smooth out the rate
        time.sleep(MIN_DELAY_BETWEEN_SUBMISSIONS)


# ============================================================================
# IMPORT DEPENDENCIES
# ============================================================================

# Add parent directory to path to import TranscriptionWorkflow
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
batch_path = os.path.join(parent_dir, 'amp_transcript_batch')

if os.path.exists(batch_path):
    sys.path.insert(0, batch_path)
    logger.info("Using TranscriptionWorkflow from amp_transcript_batch")
else:
    logger.error(f"Could not find amp_transcript_batch directory at {batch_path}")
    sys.exit(1)

from azure.storage.blob import (
    BlobServiceClient, 
    generate_container_sas, 
    ContainerSasPermissions
)
from function_app import TranscriptionWorkflow


# ============================================================================
# CUSTOM TRANSCRIPTION WORKFLOW
# ============================================================================

class SimpleTranscriptionWorkflow(TranscriptionWorkflow):
    """Extended TranscriptionWorkflow that saves formatted and raw transcripts"""
    
    def __init__(
        self,
        voicegain_bearer_token: str,
        blob_connection_string: str,
        blob_container_name: str = "audiofiles",
        output_folder: str = "Transcripts"
    ):
        super().__init__(
            voicegain_bearer_token=voicegain_bearer_token,
            blob_connection_string=blob_connection_string,
            blob_container_name=blob_container_name
        )
        self.output_folder = output_folder
    
    def save_transcript_to_blob(
        self, 
        transcript_text: str, 
        audio_identifier: str, 
        raw_transcript_data: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Save formatted and raw transcripts to blob storage"""
        if not self.blob_service_client:
            logger.warning(f"Blob connection string not configured. Skipping upload for {audio_identifier}.")
            return None

        # Sanitize the audio identifier for filename
        sanitized_name = ""
        base_name = ""
        if ".mp3" in audio_identifier.lower():
            base_name = audio_identifier.replace("/", "_").replace("\\", "_").replace(".mp3", "")
            sanitized_name = base_name + ".txt"
        elif ".wav" in audio_identifier.lower():
            base_name = audio_identifier.replace("/", "_").replace("\\", "_").replace(".wav", "")
            sanitized_name = base_name + ".txt"
        elif ".m4a" in audio_identifier.lower():
            base_name = audio_identifier.replace("/", "_").replace("\\", "_").replace(".m4a", "")
            sanitized_name = base_name + ".txt"
        else:
            # For other formats, just replace path separators and add .txt
            base_name = audio_identifier.replace("/", "_").replace("\\", "_")
            sanitized_name = base_name + ".txt"

        container_client = self.blob_service_client.get_container_client(
            self.blob_container_name
        )
        
        # Save formatted transcript (double-space lines for readability)
        formatted_path = f"{self.output_folder}/formatted/{sanitized_name}"
        blob_client = container_client.get_blob_client(formatted_path)
        # Normalize newlines and insert an empty line before each existing newline
        normalized_text = transcript_text.replace('\r\n', '\n').replace('\r', '\n')
        formatted_text = normalized_text.replace('\n', '\n\n')
        blob_client.upload_blob(formatted_text, overwrite=True)
        logger.info(f"Formatted transcript saved to: {formatted_path}")
        
        # Save raw transcript JSON if provided
        if raw_transcript_data is not None:
            raw_json = json.dumps(raw_transcript_data, indent=2)
            raw_path = f"{self.output_folder}/raw/{base_name}.json"
            raw_blob_client = container_client.get_blob_client(raw_path)
            raw_blob_client.upload_blob(raw_json, overwrite=True)
            logger.info(f"Raw transcript saved to: {raw_path}")
        
        return formatted_path


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def list_audio_files_from_blob(
    connection_string: str,
    container_name: str,
    audio_extensions: Optional[List[str]] = None,
    max_files: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    List audio files from Azure Blob Storage container.
    Excludes files already in Archive/, Processed/, or Transcripts/ folders.
    """
    audio_extensions = audio_extensions or [".wav", ".mp3", ".m4a"]
    
    try:
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(container_name)
        
        if not container_client.exists():
            logger.error(f"Container '{container_name}' does not exist")
            return []
        
        logger.info(f"Scanning container '{container_name}' for audio files...")
        logger.info("This may take several minutes with large containers...")
        
        audio_files = []
        blob_list = container_client.list_blobs()
        
        # Exclude files that are already processed
        exclude_prefixes = ['Archive/', 'Processed/', 'Transcripts/']
        
        scanned_count = 0
        last_log_time = time.time()
        log_interval = 30  # Log progress every 30 seconds
        log_count_interval = 10000  # Also log every 10k blobs
        
        logger.info("Starting blob iteration...")
        sys.stdout.flush()
        
        for blob in blob_list:
            scanned_count += 1
            blob_name = blob.name.lower()
            
            # Log progress periodically
            current_time = time.time()
            should_log = False
            if current_time - last_log_time >= log_interval:
                should_log = True
                last_log_time = current_time
            elif scanned_count % log_count_interval == 0:
                should_log = True
            
            if should_log:
                logger.info(f"Scanning... checked {scanned_count:,} blobs, found {len(audio_files):,} audio files so far...")
                sys.stdout.flush()
            
            # Skip files in Archive, Processed, or Transcripts folders
            if any(blob.name.startswith(exclude) for exclude in exclude_prefixes):
                continue
            
            if any(blob_name.endswith(ext) for ext in audio_extensions):
                audio_files.append({
                    "audiopath": blob.name,
                    "source_metadata": None
                })
                
                # Stop scanning if we've reached the max_files limit
                if max_files and len(audio_files) >= max_files:
                    logger.info(f"Reached max_files limit ({max_files:,}). Stopping scan early.")
                    logger.info(f"Found {len(audio_files):,} audio files (scanned {scanned_count:,} total blobs)")
                    sys.stdout.flush()
                    break
        
        logger.info(f"Scanning complete! Found {len(audio_files):,} audio files (scanned {scanned_count:,} total blobs)")
        return audio_files
        
    except Exception as e:
        logger.error(f"Error listing audio files from blob: {e}")
        raise


def generate_blob_url(
    connection_string: str,
    container_name: str,
    blob_name: str
) -> str:
    """Generate a URL for a blob that can be accessed externally."""
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    account_name = blob_service_client.account_name
    
    # Parse connection string to get account key
    conn_parts = dict(part.split('=', 1) for part in connection_string.split(';') if '=' in part)
    account_key = conn_parts.get('AccountKey', '')
    
    if account_key:
        # Generate SAS token valid for 24 hours
        sas_token = generate_container_sas(
            account_name=account_name,
            container_name=container_name,
            account_key=account_key,
            permission=ContainerSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(hours=24)
        )
    
    # Construct blob URL
    blob_url = f"https://{account_name}.blob.core.windows.net/{container_name}/{blob_name}"
    
    # Add SAS token
    separator = "&" if "?" in blob_url else "?"
    blob_url = f"{blob_url}{separator}{sas_token}"
    
    return blob_url


def move_blob_to_archive(
    connection_string: str,
    container_name: str,
    blob_name: str,
    archive_folder: str = "Archive"
) -> Optional[str]:
    """Move a blob to the Archive folder after successful transcription."""
    try:
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(container_name)
        
        # Construct new blob path in Archive folder
        original_name = blob_name.split('/')[-1]  # Get just the filename
        new_blob_path = f"{archive_folder}/{original_name}"
        
        # Get source blob client
        source_blob_client = container_client.get_blob_client(blob_name)
        
        # Check if source blob exists
        if not source_blob_client.exists():
            logger.warning(f"Source blob {blob_name} does not exist, skipping move")
            return None
        
        # Get destination blob client
        dest_blob_client = container_client.get_blob_client(new_blob_path)
        
        # Copy blob to new location
        dest_blob_client.start_copy_from_url(source_blob_client.url)
        
        # Wait for copy to complete
        copy_props = dest_blob_client.get_blob_properties()
        max_wait_time = 30  # Maximum wait time in seconds
        wait_time = 0
        while copy_props.copy.status == 'pending' and wait_time < max_wait_time:
            time.sleep(0.5)
            wait_time += 0.5
            copy_props = dest_blob_client.get_blob_properties()
        
        if copy_props.copy.status == 'success':
            # Delete original blob after successful copy
            source_blob_client.delete_blob()
            logger.info(f"Moved {blob_name} to {new_blob_path}")
            return new_blob_path
        else:
            logger.error(f"Failed to copy blob: {copy_props.copy.status}")
            return None
            
    except Exception as e:
        logger.error(f"Error moving blob {blob_name} to Archive folder: {e}")
        return None


# ============================================================================
# MAIN PROCESSING FUNCTION
# ============================================================================

def process_audio_file(
    audio_file: Dict[str, Any],
    workflow: SimpleTranscriptionWorkflow,
    connection_string: str,
    container_name: str,
    idx: int,
    total: int
) -> Dict[str, Any]:
    """Process a single audio file through transcription."""
    result = {
        "audio_path": audio_file.get('audiopath'),
        "success": False,
        "error": None,
        "transcript_path": None
    }
    
    audio_path = audio_file.get('audiopath')
    if not audio_path:
        result["error"] = "Missing audiopath"
        return result
    
    try:
        logger.info(f"[{idx}/{total}] Processing: {audio_path}")
        
        # Generate blob URL
        audio_url = generate_blob_url(connection_string, container_name, audio_path)
        
        # Wait for rate limit before submitting
        wait_for_rate_limit()
        
        # Submit to VoiceGain
        transcription_response = workflow.submit_transcription_request(audio_url)
        if transcription_response is None:
            result["error"] = "Rate limited or submission failed"
            logger.warning(f"Failed to submit {audio_path}")
            return result
        
        # Get session URL
        session_url = transcription_response["sessions"][0]["sessionUrl"]
        
        # Poll for completion
        results_phase, status = workflow.poll_transcription_status(session_url)
        
        if status in {"fail", "timeout"}:
            result["error"] = f"Transcription {status}"
            logger.error(f"Transcription {status} for {audio_path}")
            return result
        
        # Get raw transcript data
        raw_transcript_data = workflow.get_transcript(session_url)
        
        # Format transcript
        formatted_transcript = workflow.format_transcript(raw_transcript_data)
        
        # Save both formatted and raw transcripts
        transcript_path = workflow.save_transcript_to_blob(
            formatted_transcript,
            audio_path,
            raw_transcript_data=raw_transcript_data
        )
        
        result["transcript_path"] = transcript_path
        result["success"] = True
        
        # Move file to Archive after successful transcription
        archive_path = move_blob_to_archive(connection_string, container_name, audio_path)
        if archive_path:
            logger.info(f"Successfully moved {audio_path} to Archive")
        else:
            logger.warning(f"Failed to move {audio_path} to Archive (transcript saved anyway)")
        
        logger.info(f"[SUCCESS] Completed {idx}/{total}: {audio_path}")
        return result
        
    except Exception as e:
        result["error"] = str(e)
        logger.exception(f"Error processing audio file {audio_path}: {e}")
        return result


def main():
    """Main function to run the transcription process."""
    logger.info("=" * 80)
    logger.info("Starting Simple Transcription Script")
    logger.info("=" * 80)
    
    # Validate configuration
    if BLOB_CONNECTION_STRING == "YOUR_CONNECTION_STRING_HERE":
        logger.error("Please set BLOB_CONNECTION_STRING in the script configuration")
        sys.exit(1)
    
    if VOICEGAIN_TOKEN == "YOUR_VOICEGAIN_TOKEN_HERE":
        logger.error("Please set VOICEGAIN_TOKEN in the script configuration")
        sys.exit(1)
    
    # List audio files
    logger.info("Listing audio files from blob storage...")
    audio_files = list_audio_files_from_blob(
        BLOB_CONNECTION_STRING,
        CONTAINER_NAME,
        max_files=MAX_FILES
    )
    
    if not audio_files:
        logger.warning("No audio files found to process")
        return
    
    total_files = len(audio_files)
    logger.info(f"Found {total_files:,} audio files to process")
    
    # Create transcription workflow
    workflow = SimpleTranscriptionWorkflow(
        voicegain_bearer_token=VOICEGAIN_TOKEN,
        blob_connection_string=BLOB_CONNECTION_STRING,
        blob_container_name=CONTAINER_NAME,
        output_folder="Transcripts"
    )
    
    # Process files
    logger.info("Starting transcription processing...")
    logger.info(f"Rate limit: {MAX_FILES_PER_HOUR} files per hour (~{MIN_DELAY_BETWEEN_SUBMISSIONS:.2f}s between submissions)")
    
    successful = 0
    failed = 0
    
    start_time = time.time()
    
    for idx, audio_file in enumerate(audio_files, 1):
        result = process_audio_file(
            audio_file,
            workflow,
            BLOB_CONNECTION_STRING,
            CONTAINER_NAME,
            idx,
            total_files
        )
        
        if result["success"]:
            successful += 1
        else:
            failed += 1
        
        # Log progress every 10 files
        if idx % 10 == 0:
            elapsed = time.time() - start_time
            rate = idx / elapsed if elapsed > 0 else 0
            remaining = (total_files - idx) / rate if rate > 0 else 0
            logger.info(f"Progress: {idx}/{total_files} ({successful} successful, {failed} failed) | "
                       f"Rate: {rate:.2f} files/sec | ETA: {remaining/60:.1f} minutes")
    
    # Summary
    elapsed_time = time.time() - start_time
    logger.info("=" * 80)
    logger.info("Processing Complete!")
    logger.info(f"Total files: {total_files:,}")
    logger.info(f"Successful: {successful:,}")
    logger.info(f"Failed: {failed:,}")
    logger.info(f"Total time: {elapsed_time/60:.1f} minutes")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()

