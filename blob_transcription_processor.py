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

# Add amp_transcript to path to import TranscriptionWorkflow
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'amp_transcript'))

from azure.storage.blob import (
    BlobServiceClient, 
    generate_container_sas, 
    ContainerSasPermissions
)
from function_app import TranscriptionWorkflow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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

            transcription_response = self.submit_transcription_request(audio_url)
            if transcription_response is None:
                response_payload["status"] = "rate_limited"
                return response_payload

            self.session_url = transcription_response["sessions"][0]["sessionUrl"]
            results_phase, status = self.poll_transcription_status(self.session_url)
            response_payload["status"] = status or results_phase

            if status in {"fail", "timeout"}:
                logger.error(
                    "Transcription %s for %s",
                    status,
                    audio_path or audio_url,
                )
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
            return response_payload

        except Exception as exc:  # pylint: disable=broad-except
            response_payload["error"] = str(exc)
            logger.exception(
                "Error processing audio item %s: %s",
                audio_path or audio_url or "<unknown>",
                exc,
            )
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
        
        for blob in blob_list:
            blob_name = blob.name.lower()
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
    processed_folder: str = "Processed"
) -> Optional[str]:
    """
    Move a blob to the "Processed" folder after successful transcription.
    
    Args:
        connection_string: Azure Storage connection string
        container_name: Name of the container
        blob_name: Name/path of the blob to move
        processed_folder: Folder name for processed files (default: "Processed")
        
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
    
    Files are processed in batches of 100 (VoiceGain API limit) to ensure
    we don't exceed the maximum concurrent requests. Within each batch,
    files are processed in parallel using ThreadPoolExecutor.
    
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
        max_workers: Number of parallel workers per batch (default: 5, max recommended: 100)
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
    logger.info(f"Starting batched processing: {max_workers} workers per batch, max 100 files per batch")
    logger.info("="*80)
    logger.info("")
    
    # Process files in batches of 100 (VoiceGain limit)
    VOICEGAIN_BATCH_SIZE = 100
    successful = 0
    failed = 0
    results = []
    total_files = len(audio_files)
    
    # Process files in batches
    num_batches = (total_files + VOICEGAIN_BATCH_SIZE - 1) // VOICEGAIN_BATCH_SIZE
    
    for batch_num in range(num_batches):
        batch_start = batch_num * VOICEGAIN_BATCH_SIZE
        batch_end = min(batch_start + VOICEGAIN_BATCH_SIZE, total_files)
        batch_files = audio_files[batch_start:batch_end]
        
        logger.info("")
        logger.info(f"Processing batch {batch_num + 1}/{num_batches} ({len(batch_files)} files)")
        logger.info("-" * 80)
        
        # Process this batch in parallel (but limited to max_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit tasks for this batch
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
                    completed = batch_start + batch_completed
                    if result.get("success"):
                        successful += 1
                        logger.info(f"[Progress: {completed}/{total_files}] ✓ Success: {audio_file.get('audiopath', 'unknown')}")
                    else:
                        failed += 1
                        logger.warning(f"[Progress: {completed}/{total_files}] ✗ Failed: {audio_file.get('audiopath', 'unknown')}")
                except Exception as e:
                    failed += 1
                    batch_completed += 1
                    completed = batch_start + batch_completed
                    logger.exception(f"[Progress: {completed}/{total_files}] Exception in parallel processing for {audio_file.get('audiopath', 'unknown')}: {e}")
                    results.append({
                        "audio_path": audio_file.get('audiopath'),
                        "success": False,
                        "error": str(e)
                    })
        
        # Wait for batch to complete before starting next batch
        logger.info(f"Batch {batch_num + 1}/{num_batches} complete. Waiting before next batch...")
        if batch_num < num_batches - 1:  # Don't wait after last batch
            time.sleep(2)  # Small delay between batches to avoid overwhelming the system
    
    # Summary
    logger.info("")
    logger.info("="*80)
    logger.info("Processing Complete!")
    logger.info("="*80)
    logger.info(f"Total files processed: {total_files}")
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Success rate: {(successful/total_files*100):.1f}%" if total_files > 0 else "N/A")
    logger.info("="*80)


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
    MAX_WORKERS = os.getenv("MAX_WORKERS", "5")  # Number of parallel workers
    MAX_WORKERS = int(MAX_WORKERS) if MAX_WORKERS else 5
    
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
        max_workers=MAX_WORKERS  # Parallel processing workers
    )


if __name__ == "__main__":
    main()

