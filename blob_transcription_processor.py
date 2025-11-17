"""
Azure Blob Storage Transcription Processor

This script connects to Azure Blob Storage, processes audio files through
the transcription workflow, and saves transcripts to a "Transcripts" folder.
"""

import os
import sys
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

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
    """Extended TranscriptionWorkflow that saves to 'Transcripts' folder"""
    
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
    
    def save_transcript_to_blob(self, transcript_text: str, audio_identifier: str) -> Optional[str]:
        """Override to save to 'Transcripts' folder instead of default path"""
        if not self.blob_service_client:
            logger.warning(
                "Blob connection string not configured. Skipping upload for %s.",
                audio_identifier,
            )
            return None

        # Sanitize the audio identifier for filename
        sanitized_name = ""
        if ".mp3" in audio_identifier.lower():
            sanitized_name = audio_identifier.replace("/", "_").replace("\\", "_").replace(".mp3", ".txt")
        elif ".wav" in audio_identifier.lower():
            sanitized_name = audio_identifier.replace("/", "_").replace("\\", "_").replace(".wav", ".txt")
        elif ".m4a" in audio_identifier.lower():
            sanitized_name = audio_identifier.replace("/", "_").replace("\\", "_").replace(".m4a", ".txt")
        else:
            # For other formats, just replace path separators and add .txt
            sanitized_name = audio_identifier.replace("/", "_").replace("\\", "_") + ".txt"

        # Use the output_folder instead of hardcoded path
        full_blob_path = f"{self.output_folder}/{sanitized_name}"

        container_client = self.blob_service_client.get_container_client(
            self.blob_container_name
        )
        blob_client = container_client.get_blob_client(full_blob_path)
        blob_client.upload_blob(transcript_text, overwrite=True)
        logger.info("Transcript saved to blob path %s", full_blob_path)
        return full_blob_path


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
    move_to_processed: bool = True
):
    """
    Main function to process audio files from Azure Blob Storage.
    
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
    
    # Initialize transcription workflow
    workflow = CustomTranscriptionWorkflow(
        voicegain_bearer_token=voicegain_token,
        blob_connection_string=connection_string,
        blob_container_name=container_name,
        azure_function_url=azure_function_url,
        audio_base_url=audio_base_url,
        output_folder=output_folder
    )
    
    # Process each audio file
    successful = 0
    failed = 0
    results = []
    
    for idx, audio_file in enumerate(audio_files, 1):
        logger.info("")
        logger.info("="*80)
        logger.info(f"Processing {idx}/{len(audio_files)}")
        logger.info("="*80)
        logger.info(f"Audio file: {audio_file['audiopath']}")
        
        try:
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
                    logger.info(f"Generated blob URL for audio file")
                except Exception as e:
                    logger.warning(f"Could not generate blob URL: {e}. Using base_audio_url if provided.")
            
            result = workflow.process_audio_file(
                item=audio_file,
                sas_token=sas_token,
                base_audio_url=audio_base_url
            )
            
            if result.get("success"):
                successful += 1
                logger.info(f"✓ Successfully processed: {audio_file['audiopath']}")
                logger.info(f"  Transcript saved to: {result.get('transcript_blob_path')}")
                
                # Move file to Processed folder if enabled
                if move_to_processed:
                    processed_path = move_blob_to_processed(
                        connection_string=connection_string,
                        container_name=container_name,
                        blob_name=audio_file['audiopath']
                    )
                    if processed_path:
                        logger.info(f"  File moved to: {processed_path}")
                    else:
                        logger.warning(f"  Failed to move file to Processed folder")
            else:
                failed += 1
                status = result.get("status", "unknown")
                error = result.get("error", "No error message")
                logger.error(f"✗ Failed to process: {audio_file['audiopath']}")
                logger.error(f"  Status: {status}, Error: {error}")
            
            results.append(result)
            
        except Exception as e:
            failed += 1
            logger.exception(f"Exception processing {audio_file['audiopath']}: {e}")
            results.append({
                "audio_path": audio_file['audiopath'],
                "success": False,
                "error": str(e)
            })
    
    # Summary
    logger.info("")
    logger.info("="*80)
    logger.info("Processing Complete!")
    logger.info("="*80)
    logger.info(f"Total files: {len(audio_files)}")
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
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
        move_to_processed=True  # Move successfully processed files to Processed folder
    )


if __name__ == "__main__":
    main()

