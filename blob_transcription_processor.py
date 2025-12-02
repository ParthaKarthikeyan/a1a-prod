"""
Azure Blob Storage Transcription Processor

This script connects to Azure Blob Storage, processes audio files through
the transcription workflow, and saves transcripts to a "Transcripts" folder.
"""

import os
import sys
import logging
import time
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Rate limiting: 3750 files per hour (based on 1200 audio hours/hour limit)
# Average file duration: ~18 minutes (1083 seconds)
# 3750 files/hour = 62.5 files/minute = ~1.04 files/second
MAX_FILES_PER_HOUR = 3750
SECONDS_PER_HOUR = 3600
MIN_DELAY_BETWEEN_SUBMISSIONS = max(1.0, SECONDS_PER_HOUR / MAX_FILES_PER_HOUR)  # At least 1 second between submissions

# Rate limiter state
_rate_limiter_lock = Lock()
_submission_times = []  # Track submission timestamps


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

# Try to import from amp_transcript_batch first (has batch processing support)
# Fall back to amp_transcript if batch version not available
batch_path = os.path.join(os.path.dirname(__file__), 'amp_transcript_batch')
transcript_path = os.path.join(os.path.dirname(__file__), 'amp_transcript')

if os.path.exists(batch_path):
    sys.path.insert(0, batch_path)
    logger.info("Using TranscriptionWorkflow from amp_transcript_batch (batch processing enabled)")
else:
    sys.path.insert(0, transcript_path)
    logger.info("Using TranscriptionWorkflow from amp_transcript")

from azure.storage.blob import (
    BlobServiceClient, 
    generate_container_sas, 
    ContainerSasPermissions
)
from function_app import TranscriptionWorkflow

# Import job tracker
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'dashboard_backend'))
try:
    from voicegain_tracker import submit_job, update_job_polling, complete_job, get_stats
    TRACKING_ENABLED = True
except ImportError:
    TRACKING_ENABLED = False
    logger.warning("VoiceGain tracker not available - job tracking disabled")


class CustomTranscriptionWorkflow(TranscriptionWorkflow):
    """Extended TranscriptionWorkflow that saves to 'Transcripts' folder with formatted and raw subfolders"""
    
    def __init__(
        self,
        voicegain_bearer_token: str,
        blob_connection_string: str,
        blob_container_name: str = "autoqa",
        azure_function_url: Optional[str] = None,
        audio_base_url: Optional[str] = None,
        output_folder: str = "Transcripts"
    ):
        super().__init__(
            voicegain_bearer_token=voicegain_bearer_token,
            blob_connection_string=blob_connection_string,
            azure_function_url=azure_function_url,
            audio_base_url=audio_base_url,
            blob_container_name=blob_container_name
        )
        self.output_folder = output_folder
        self.raw_transcript_data = None  # Store raw transcript data
    
    def poll_transcription_status(
        self,
        session_url: str,
        max_iterations: int = 60,
        delay_seconds: int = 20,
        job_id: Optional[str] = None
    ):
        """Override to add job tracking during polling"""
        import requests
        headers = {"Authorization": f"Bearer {self.voicegain_token}"}

        results = ""
        status = ""
        iteration_count = 0

        while results != "DONE" and iteration_count < max_iterations:
            time.sleep(delay_seconds)

            response = requests.get(session_url, headers=headers, timeout=30)
            response.raise_for_status()

            data = response.json()
            phase = data.get("progress", {}).get("phase", "")
            results = phase

            if results == "ERROR":
                results = "DONE"
                status = "fail"
                break

            iteration_count += 1
            
            # Track polling progress
            if TRACKING_ENABLED and job_id:
                update_job_polling(job_id, phase, iteration_count)
            
            logger.info(
                "Polling session %s iteration %d/%d phase=%s",
                session_url,
                iteration_count,
                max_iterations,
                phase,
            )

        if iteration_count >= max_iterations and results != "DONE":
            status = "timeout"
            results = "DONE"
            logger.error("Polling timeout reached for session %s", session_url)

        return results, status
    
    def process_audio_file(
        self,
        item: Dict[str, Any],
        sas_token: Optional[str] = None,
        base_audio_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Override to capture and save raw transcript data along with formatted"""
        audio_path = item.get("audiopath")
        audio_url = item.get("audio_url")
        chosen_base_url = base_audio_url or item.get("base_audio_url") or self.audio_base_url
        job_id = None

        response_payload: Dict[str, Any] = {
            "audio_path": audio_path,
            "audio_url": audio_url,
            "success": False,
            "status": "",
            "transcript_blob_path": None,
            "error": None,
        }

        try:
            if not audio_url:
                if not audio_path:
                    raise ValueError("Missing 'audiopath' or 'audio_url' in work item.")
                if not chosen_base_url:
                    raise ValueError("Audio base URL not provided for constructing audio_url.")
                audio_url = f"{chosen_base_url.rstrip('/')}/{audio_path.lstrip('/')}"
            if sas_token:
                separator = "&" if "?" in audio_url else "?"
                audio_url = f"{audio_url}{separator}{sas_token}"
            response_payload["audio_url"] = audio_url

            # Wait for rate limit before submitting
            wait_for_rate_limit()
            
            # Submit to VoiceGain
            transcription_response = self.submit_transcription_request(audio_url)
            if transcription_response is None:
                response_payload["status"] = "rate_limited"
                # Don't track rate-limited requests - they weren't actually submitted
                # This prevents inflating the submission count
                return response_payload

            # Track the job submission (only for successful submissions)
            if TRACKING_ENABLED:
                job_id = submit_job(audio_path or "unknown", audio_url, transcription_response)

            self.session_url = transcription_response["sessions"][0]["sessionUrl"]
            results_phase, status = self.poll_transcription_status(self.session_url, job_id=job_id)
            response_payload["status"] = status or results_phase

            if status in {"fail", "timeout"}:
                logger.error(
                    "Transcription %s for %s",
                    status,
                    audio_path or audio_url,
                )
                if TRACKING_ENABLED and job_id:
                    complete_job(job_id, False, f"Transcription {status}")
                return response_payload

            # Get raw transcript data
            raw_transcript_data = self.get_transcript(self.session_url)
            # Format transcript
            formatted_transcript = self.format_transcript(raw_transcript_data)
            
            # Save both formatted and raw transcripts
            blob_path = self.save_transcript_to_blob(
                formatted_transcript,
                audio_path or audio_url,
                raw_transcript_data=raw_transcript_data
            )
            response_payload["transcript_blob_path"] = blob_path
            response_payload["success"] = True
            
            # Mark job as completed
            if TRACKING_ENABLED and job_id:
                complete_job(job_id, True)
            
            return response_payload

        except Exception as exc:  # pylint: disable=broad-except
            response_payload["error"] = str(exc)
            logger.exception(
                "Error processing audio item %s: %s",
                audio_path or audio_url or "<unknown>",
                exc,
            )
            if TRACKING_ENABLED and job_id:
                complete_job(job_id, False, str(exc))
            return response_payload
    
    def save_transcript_to_blob(self, transcript_text: str, audio_identifier: str, raw_transcript_data: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Override to save to 'Transcripts/formatted' and 'Transcripts/raw' folders"""
        if not self.blob_service_client:
            logger.warning(
                "Blob connection string not configured. Skipping upload for %s.",
                audio_identifier,
            )
            return None

        # Sanitize the audio identifier for filename
        sanitized_name = ""
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
        
        # Save formatted transcript
        formatted_path = f"{self.output_folder}/formatted/{sanitized_name}"
        blob_client = container_client.get_blob_client(formatted_path)
        blob_client.upload_blob(transcript_text, overwrite=True)
        logger.info("Formatted transcript saved to: %s", formatted_path)
        
        # Save raw transcript JSON if provided
        if raw_transcript_data is not None:
            import json
            raw_json = json.dumps(raw_transcript_data, indent=2)
            raw_path = f"{self.output_folder}/raw/{base_name}.json"
            raw_blob_client = container_client.get_blob_client(raw_path)
            raw_blob_client.upload_blob(raw_json, overwrite=True)
            logger.info("Raw transcript saved to: %s", raw_path)
        
        return formatted_path


def list_audio_files_from_blob(
    connection_string: str,
    container_name: str,
    prefix: str = "",
    audio_extensions: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    List audio files from Azure Blob Storage container.
    
    Args:
        connection_string: Azure Storage connection string
        container_name: Name of the container
        prefix: Optional prefix/folder to filter blobs
        audio_extensions: List of audio file extensions to include
        
    Returns:
        List of dictionaries with 'audiopath' keys
    """
    audio_extensions = audio_extensions or [".wav", ".mp3", ".m4a"]
    
    try:
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(container_name)
        
        if not container_client.exists():
            logger.error(f"Container '{container_name}' does not exist")
            return []
        
        logger.info(f"Scanning container '{container_name}' with prefix '{prefix}' for audio files...")
        
        audio_files = []
        blob_list = container_client.list_blobs(name_starts_with=prefix)
        
        # Exclude files that are already processed (in Archive or Processed folders)
        exclude_prefixes = ['Archive/', 'Processed/', 'Transcripts/']
        
        for blob in blob_list:
            blob_name = blob.name.lower()
            # Skip files in Archive, Processed, or Transcripts folders
            if any(blob.name.startswith(exclude) for exclude in exclude_prefixes):
                continue
            if any(blob_name.endswith(ext) for ext in audio_extensions):
                audio_files.append({
                    "audiopath": blob.name,  # Use full blob name as path
                    "source_metadata": None
                })
        
        logger.info(f"Found {len(audio_files)} audio files")
        return audio_files
        
    except Exception as e:
        logger.error(f"Error listing audio files from blob: {e}")
        raise


def move_blob_to_processed(
    connection_string: str,
    container_name: str,
    blob_name: str,
    processed_folder: str = "Archive"
) -> Optional[str]:
    """
    Move a blob to the "Archive" folder after successful transcription.
    
    Args:
        connection_string: Azure Storage connection string
        container_name: Name of the container
        blob_name: Name/path of the blob to move
        processed_folder: Folder name for archived audio files (default: "Archive")
        
    Returns:
        New blob path if successful, None otherwise
    """
    try:
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(container_name)
        
        # Construct new blob path in Processed folder
        # Preserve the original filename but move to Processed folder
        original_name = blob_name.split('/')[-1]  # Get just the filename
        new_blob_path = f"{processed_folder}/{original_name}"
        
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
        logger.error(f"Error moving blob {blob_name} to Processed folder: {e}")
        return None


def generate_blob_url(
    connection_string: str,
    container_name: str,
    blob_name: str,
    sas_token: Optional[str] = None
) -> str:
    """
    Generate a URL for a blob that can be accessed externally.
    
    Args:
        connection_string: Azure Storage connection string
        container_name: Name of the container
        blob_name: Name/path of the blob
        sas_token: Optional SAS token (if not provided, generates one)
        
    Returns:
        Full URL to the blob with SAS token
    """
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    account_name = blob_service_client.account_name
    
    # If no SAS token provided, generate one
    if not sas_token:
        # Get account key from connection string
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


def process_single_audio_file(
    audio_file: Dict[str, Any],
    connection_string: str,
    voicegain_token: str,
    container_name: str,
    output_folder: str,
    sas_token: Optional[str],
    audio_base_url: Optional[str],
    azure_function_url: Optional[str],
    generate_blob_urls: bool,
    move_to_processed: bool,
    idx: int,
    total: int
) -> Dict[str, Any]:
    """Process a single audio file - used for parallel processing"""
    result = {
        "audio_path": audio_file.get('audiopath'),
        "success": False,
        "error": None,
        "transcript_path": None
    }
    
    try:
        logger.info(f"[{idx}/{total}] Processing: {audio_file['audiopath']}")
        
        # Generate blob URL if needed
        if generate_blob_urls and not audio_file.get('audio_url'):
            try:
                blob_url = generate_blob_url(
                    connection_string=connection_string,
                    container_name=container_name,
                    blob_name=audio_file['audiopath'],
                    sas_token=sas_token
                )
                audio_file['audio_url'] = blob_url
            except Exception as e:
                logger.warning(f"Could not generate blob URL for {audio_file['audiopath']}: {e}")
                result["error"] = f"URL generation failed: {e}"
                return result
        
        # Initialize workflow for this file
        workflow = CustomTranscriptionWorkflow(
            voicegain_bearer_token=voicegain_token,
            blob_connection_string=connection_string,
            blob_container_name=container_name,
            azure_function_url=azure_function_url,
            audio_base_url=audio_base_url,
            output_folder=output_folder
        )
        
        # Process the file (this will save both formatted and raw transcripts)
        process_result = workflow.process_audio_file(
            item=audio_file,
            sas_token=sas_token,
            base_audio_url=audio_base_url
        )
        
        if process_result.get("success"):
            result["success"] = True
            result["transcript_path"] = process_result.get('transcript_blob_path')
            
            # Move file to Processed folder if enabled
            if move_to_processed:
                processed_path = move_blob_to_processed(
                    connection_string=connection_string,
                    container_name=container_name,
                    blob_name=audio_file['audiopath']
                )
                if processed_path:
                    logger.info(f"[{idx}/{total}] ✓ Moved to: {processed_path}")
        else:
            result["error"] = process_result.get("error") or process_result.get("status", "Unknown error")
            logger.error(f"[{idx}/{total}] ✗ Failed: {audio_file['audiopath']} - {result['error']}")
            
    except Exception as e:
        result["error"] = str(e)
        logger.exception(f"[{idx}/{total}] Exception processing {audio_file.get('audiopath', 'unknown')}: {e}")
    
    return result


def process_blob_audio_files(
    connection_string: str,
    voicegain_token: str,
    container_name: str = "autoqa",
    source_prefix: str = "",
    output_folder: str = "Transcripts",
    sas_token: Optional[str] = None,
    audio_base_url: Optional[str] = None,
    azure_function_url: Optional[str] = None,
    generate_blob_urls: bool = True,
    max_files: Optional[int] = None,
    move_to_processed: bool = True,
    max_workers: int = 5
):
    """
    Main function to process audio files from Azure Blob Storage.
    
    Files are processed in batches of 200 (VoiceGain API rate limit: 1200 hrs/hr) to ensure
    we don't exceed the maximum concurrent requests. Within each batch,
    ALL files are processed in parallel (up to 200 simultaneous requests).
    Batches are processed sequentially to respect API rate limits.
    
    Args:
        connection_string: Azure Storage connection string
        voicegain_token: VoiceGain API bearer token
        container_name: Name of the blob container
        source_prefix: Prefix/folder in blob to process (empty = root)
        output_folder: Folder name for output transcripts
        sas_token: Optional SAS token for audio file access
        audio_base_url: Optional base URL for constructing audio URLs
        azure_function_url: Optional Azure Function URL for transcript formatting
        generate_blob_urls: If True, automatically generate blob URLs with SAS tokens
        max_files: Optional limit on number of files to process (None = process all)
        move_to_processed: If True, move successfully processed files to "Processed" folder
        max_workers: DEPRECATED - now uses batch size (100) for parallel processing
    """
    logger.info("="*80)
    logger.info("Azure Blob Transcription Processor")
    logger.info("="*80)
    logger.info(f"Container: {container_name}")
    logger.info(f"Source prefix: {source_prefix or '(root)'}")
    logger.info(f"Output folder: {output_folder}")
    logger.info("="*80)
    logger.info("")
    
    # List audio files from blob storage
    try:
        audio_files = list_audio_files_from_blob(
            connection_string=connection_string,
            container_name=container_name,
            prefix=source_prefix
        )
    except Exception as e:
        logger.error(f"Failed to list audio files: {e}")
        return
    
    if not audio_files:
        logger.warning("No audio files found to process")
        return
    
    # Limit number of files if specified
    if max_files and max_files > 0:
        audio_files = audio_files[:max_files]
        logger.info(f"Limited to processing first {len(audio_files)} files")
    
    # Pre-generate blob URLs for all files (can be done in parallel)
    logger.info("Generating blob URLs for all files...")
    for audio_file in audio_files:
        if generate_blob_urls and not audio_file.get('audio_url'):
            try:
                blob_url = generate_blob_url(
                    connection_string=connection_string,
                    container_name=container_name,
                    blob_name=audio_file['audiopath'],
                    sas_token=sas_token
                )
                audio_file['audio_url'] = blob_url
            except Exception as e:
                logger.warning(f"Could not generate blob URL for {audio_file['audiopath']}: {e}")
    
    logger.info("")
    logger.info("="*80)
    logger.info(f"Starting batched processing: 200 files per batch (with rate limiting)")
    logger.info("="*80)
    logger.info("")
    
    # Process files in batches of 200 (VoiceGain API rate limit: 1200 hrs/hr)
    # Within each batch, files are processed with rate limiting (3750 files/hour)
    # Batches are processed sequentially to respect API limits
    # Reduced from 1500 due to high failure rate - adaptive rate limiting will adjust if needed
    VOICEGAIN_BATCH_SIZE = 200
    MIN_BATCH_SIZE = 10  # Minimum batch size for adaptive rate limiting
    successful = 0
    failed = 0
    rate_limited = 0  # Track rate-limited requests
    results = []
    total_files = len(audio_files)
    
    # Adaptive rate limiting: track 429 errors and adjust batch size
    current_batch_size = VOICEGAIN_BATCH_SIZE
    batch_429_count = 0  # Count 429 errors in current batch
    batch_total_requests = 0  # Total requests in current batch
    
    # Process files in batches
    num_batches = (total_files + current_batch_size - 1) // current_batch_size
    
    batch_num = 0
    batch_start = 0
    
    while batch_start < total_files:
        # Recalculate number of batches with current batch size
        num_batches = (total_files + current_batch_size - 1) // current_batch_size
        batch_end = min(batch_start + current_batch_size, total_files)
        batch_files = audio_files[batch_start:batch_end]
        batch_size = len(batch_files)
        
        # Reset batch statistics
        batch_429_count = 0
        batch_total_requests = 0
        
        logger.info("")
        logger.info(f"Processing batch {batch_num + 1}/{num_batches} (items {batch_start + 1}-{batch_end} of {total_files}, batch size: {current_batch_size})")
        logger.info("-" * 80)
        
        # Process ALL items in this batch in parallel
        # Use max_workers equal to batch size to process all items simultaneously
        batch_workers = min(batch_size, current_batch_size)
        with ThreadPoolExecutor(max_workers=batch_workers) as executor:
            # Submit all tasks for this batch
            future_to_file = {
                executor.submit(
                    process_single_audio_file,
                    audio_file,
                    connection_string,
                    voicegain_token,
                    container_name,
                    output_folder,
                    sas_token,
                    audio_base_url,
                    azure_function_url,
                    generate_blob_urls,
                    move_to_processed,
                    batch_start + idx + 1,
                    total_files
                ): audio_file
                for idx, audio_file in enumerate(batch_files)
            }
            
            # Process completed tasks as they finish
            batch_completed = 0
            for future in as_completed(future_to_file):
                audio_file = future_to_file[future]
                try:
                    result = future.result()
                    results.append(result)
                    batch_completed += 1
                    batch_total_requests += 1
                    completed = batch_start + batch_completed
                    
                    # Track rate-limited requests
                    if result.get("status") == "rate_limited" or (result.get("error") and "rate" in result.get("error", "").lower()):
                        rate_limited += 1
                        batch_429_count += 1
                    
                    if result.get("success"):
                        successful += 1
                        logger.info(f"[Progress: {completed}/{total_files}] ✓ Success: {audio_file.get('audiopath', 'unknown')}")
                    else:
                        failed += 1
                        logger.warning(f"[Progress: {completed}/{total_files}] ✗ Failed: {audio_file.get('audiopath', 'unknown')}")
                except Exception as e:
                    failed += 1
                    batch_completed += 1
                    batch_total_requests += 1
                    completed = batch_start + batch_completed
                    logger.exception(f"[Progress: {completed}/{total_files}] Exception in parallel processing for {audio_file.get('audiopath', 'unknown')}: {e}")
                    results.append({
                        "audio_path": audio_file.get('audiopath'),
                        "success": False,
                        "error": str(e)
                    })
        
        # Adaptive rate limiting: adjust batch size based on 429 error rate
        rate_429_percentage = 0.0
        if batch_total_requests > 0:
            rate_429_percentage = (batch_429_count / batch_total_requests) * 100
            if rate_429_percentage > 5.0:  # If more than 5% of requests are rate-limited
                # Reduce batch size by 25% (minimum MIN_BATCH_SIZE)
                new_batch_size = max(MIN_BATCH_SIZE, int(current_batch_size * 0.75))
                if new_batch_size < current_batch_size:
                    logger.warning(
                        f"Rate limiting detected: {rate_429_percentage:.1f}% of requests rate-limited. "
                        f"Reducing batch size from {current_batch_size} to {new_batch_size}"
                    )
                    current_batch_size = new_batch_size
            elif rate_429_percentage == 0.0 and current_batch_size < VOICEGAIN_BATCH_SIZE:
                # Gradually increase batch size if no rate limiting (up to original size)
                new_batch_size = min(VOICEGAIN_BATCH_SIZE, int(current_batch_size * 1.1))
                if new_batch_size > current_batch_size:
                    logger.info(
                        f"No rate limiting detected. Increasing batch size from {current_batch_size} to {new_batch_size}"
                    )
                    current_batch_size = new_batch_size
        
        # Wait for batch to complete before starting next batch
        logger.info(
            f"Completed batch {batch_num + 1} - {batch_completed} items processed "
            f"(429 errors: {batch_429_count}/{batch_total_requests}, {rate_429_percentage:.1f}%)"
        )
        
        batch_num += 1
        batch_start = batch_end
        
        if batch_start < total_files:  # Don't wait after last batch
            logger.info("Waiting 10 seconds before starting next batch...")
            time.sleep(10)  # Delay between batches to give VoiceGain time to process requests
    
    # Summary
    logger.info("")
    logger.info("="*80)
    logger.info("Processing Complete!")
    logger.info("="*80)
    logger.info(f"Total files processed: {total_files}")
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Rate-limited: {rate_limited}")
    logger.info(f"Success rate: {(successful/total_files*100):.1f}%" if total_files > 0 else "N/A")
    if total_files > 0:
        logger.info(f"Rate limiting rate: {(rate_limited / total_files) * 100:.1f}%")
    logger.info("="*80)
    
    # Trigger taxonomy processing if transcripts were created
    if successful > 0:
        logger.info("")
        logger.info("Triggering taxonomy processing for new transcripts...")
        try:
            run_taxonomy_processor(connection_string, container_name, output_folder)
        except Exception as e:
            logger.error(f"Taxonomy processing failed: {e}")


def run_taxonomy_processor(
    connection_string: str,
    container_name: str,
    transcripts_folder: str = "Transcripts"
):
    """
    Run taxonomy processing on newly created transcripts.
    
    Args:
        connection_string: Azure Storage connection string
        container_name: Name of the container
        transcripts_folder: Folder where transcripts are stored
    """
    try:
        # Import taxonomy processor
        from taxonomy_processor import BlobTranscriptTagger
        
        logger.info("="*80)
        logger.info("Starting Taxonomy Processing")
        logger.info("="*80)
        
        # Create taxonomy processor
        processor = BlobTranscriptTagger(
            connection_string=connection_string,
            container_name=container_name,
            transcripts_folder=f"{transcripts_folder}/formatted",
            taxonomy_file="D:\\A1A\\A1A Taxonomy.xlsx",
            output_folder="Processed"
        )
        
        # Process all transcripts
        processor.process_all_transcripts()
        
        logger.info("Taxonomy processing completed successfully!")
        
    except ImportError as e:
        logger.error(f"Could not import taxonomy_processor: {e}")
        logger.error("Make sure taxonomy_processor.py is in the same directory")
    except Exception as e:
        logger.error(f"Error running taxonomy processor: {e}")
        raise


def main():
    """Main entry point with configuration"""
    
    # Azure Blob Storage connection string (from environment variable)
    BLOB_CONNECTION_STRING = os.getenv("BLOB_CONNECTION_STRING")
    
    if not BLOB_CONNECTION_STRING:
        logger.error("BLOB_CONNECTION_STRING environment variable is required")
        logger.error("Please set it before running the script:")
        logger.error("  Windows: set BLOB_CONNECTION_STRING=your_connection_string")
        logger.error("  Linux/Mac: export BLOB_CONNECTION_STRING=your_connection_string")
        return
    
    # VoiceGain API token (from environment variable)
    VOICEGAIN_TOKEN = os.getenv("VOICEGAIN_TOKEN")
    
    if not VOICEGAIN_TOKEN:
        logger.error("VOICEGAIN_TOKEN environment variable is required")
        logger.error("Please set it before running the script:")
        logger.error("  Windows: set VOICEGAIN_TOKEN=your_token_here")
        logger.error("  Linux/Mac: export VOICEGAIN_TOKEN=your_token_here")
        return
    
    # Configuration
    CONTAINER_NAME = os.getenv("BLOB_CONTAINER_NAME", "autoqa")  # Default container name
    SOURCE_PREFIX = os.getenv("SOURCE_PREFIX", "")  # Empty = process all files, or specify folder prefix
    OUTPUT_FOLDER = "Transcripts"  # Output folder name
    SAS_TOKEN = os.getenv("SAS_TOKEN")  # Optional SAS token for audio file access
    AUDIO_BASE_URL = os.getenv("AUDIO_BASE_URL")  # Optional base URL for audio files
    AZURE_FUNCTION_URL = os.getenv("AZURE_FUNCTION_URL")  # Optional Azure Function URL
    MAX_FILES = os.getenv("MAX_FILES")  # Optional limit on number of files to process
    MAX_FILES = int(MAX_FILES) if MAX_FILES else None
    # Note: max_workers parameter is now deprecated - batch processing uses 200 parallel workers per batch
    # This matches the VoiceGain API rate limit of 1200 hrs/hr (increased from 100 hrs/hr)
    
    # Run the processor
    process_blob_audio_files(
        connection_string=BLOB_CONNECTION_STRING,
        voicegain_token=VOICEGAIN_TOKEN,
        container_name=CONTAINER_NAME,
        source_prefix=SOURCE_PREFIX,
        output_folder=OUTPUT_FOLDER,
        sas_token=SAS_TOKEN,
        audio_base_url=AUDIO_BASE_URL,
        azure_function_url=AZURE_FUNCTION_URL,
        max_files=MAX_FILES,
        move_to_processed=True,  # Move successfully processed files to Processed folder
        max_workers=4000  # Process all 4000 items in batch in parallel
    )


if __name__ == "__main__":
    main()

