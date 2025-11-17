"""
Example usage of the TranscriptionWorkflow class

This demonstrates how to use the transcription workflow programmatically
with proper configuration management.
"""

import os
from transcription_workflow import TranscriptionWorkflow


def main():
    """
    Example: Run transcription workflow with environment variables
    """
    
    # Load configuration from environment variables (recommended for security)
    voicegain_token = os.getenv(
        "VOICEGAIN_TOKEN",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."  # Default for testing
    )
    
    sql_connection_string = os.getenv(
        "SQL_CONNECTION_STRING",
        "Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=AutoQA;UID=user;PWD=password"
    )
    
    blob_connection_string = os.getenv(
        "BLOB_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;AccountName=myaccount;AccountKey=key;EndpointSuffix=core.windows.net"
    )
    
    azure_function_url = os.getenv("AZURE_FUNCTION_URL")  # Optional
    
    # SAS token for accessing audio files
    sas_token = os.getenv(
        "SAS_TOKEN",
        "sv=2024-11-04&ss=bfqt&srt=sco&sp=rwdlacupiytfx&se=2026-10-24T23:56:38Z&st=2025-10-24T15:41:38Z&spr=https&sig=..."
    )
    
    # Workflow parameters
    company_guid = os.getenv("COMPANY_GUID", "872F9103-326F-47C5-A3C2-566565F2F541")
    evaluation_date = os.getenv("EVALUATION_DATE", "2025-10-12")
    
    print("="*80)
    print("Transcription Workflow - Example Usage")
    print("="*80)
    print(f"Company GUID: {company_guid}")
    print(f"Evaluation Date: {evaluation_date}")
    print(f"Azure Function: {azure_function_url or 'Local formatting'}")
    print("="*80)
    print()
    
    # Initialize the workflow
    workflow = TranscriptionWorkflow(
        voicegain_bearer_token=voicegain_token,
        sql_connection_string=sql_connection_string,
        blob_connection_string=blob_connection_string,
        azure_function_url=azure_function_url
    )
    
    # Run the complete workflow
    try:
        workflow.run(
            company_guid=company_guid,
            evaluation_date=evaluation_date,
            sas_token=sas_token
        )
    except KeyboardInterrupt:
        print("\n\nWorkflow interrupted by user.")
    except Exception as e:
        print(f"\n\nWorkflow failed with error: {e}")
        raise


def example_process_single_file():
    """
    Example: Process a single audio file without SQL query
    """
    
    # Initialize workflow
    workflow = TranscriptionWorkflow(
        voicegain_bearer_token=os.getenv("VOICEGAIN_TOKEN"),
        sql_connection_string=os.getenv("SQL_CONNECTION_STRING"),
        blob_connection_string=os.getenv("BLOB_CONNECTION_STRING")
    )
    
    # Create a mock item (as if it came from SQL)
    item = {
        "audiopath": "recordings/2025-10-12/example.wav",
        "Companyguid": "872F9103-326F-47C5-A3C2-566565F2F541",
        "evaluationdate": "2025-10-12"
    }
    
    sas_token = os.getenv("SAS_TOKEN")
    
    # Process single file
    success = workflow.process_audio_file(item, sas_token)
    
    if success:
        print("✓ Audio file processed successfully")
    else:
        print("✗ Audio file processing failed")
    
    return success


def example_custom_polling():
    """
    Example: Custom polling configuration
    """
    
    workflow = TranscriptionWorkflow(
        voicegain_bearer_token=os.getenv("VOICEGAIN_TOKEN"),
        sql_connection_string=os.getenv("SQL_CONNECTION_STRING"),
        blob_connection_string=os.getenv("BLOB_CONNECTION_STRING")
    )
    
    # Override default polling behavior
    # Check every 15 seconds for up to 120 iterations (30 minutes)
    session_url = "https://api.voicegain.ai/v1/asr/transcribe/..."
    
    results, status = workflow.poll_transcription_status(
        session_url=session_url,
        max_iterations=120,
        delay_seconds=15
    )
    
    print(f"Results: {results}, Status: {status}")


def example_batch_by_date_range():
    """
    Example: Process multiple dates in a loop
    """
    from datetime import datetime, timedelta
    
    workflow = TranscriptionWorkflow(
        voicegain_bearer_token=os.getenv("VOICEGAIN_TOKEN"),
        sql_connection_string=os.getenv("SQL_CONNECTION_STRING"),
        blob_connection_string=os.getenv("BLOB_CONNECTION_STRING")
    )
    
    company_guid = "872F9103-326F-47C5-A3C2-566565F2F541"
    sas_token = os.getenv("SAS_TOKEN")
    
    # Process last 7 days
    start_date = datetime(2025, 10, 6)
    end_date = datetime(2025, 10, 12)
    
    current_date = start_date
    while current_date <= end_date:
        evaluation_date = current_date.strftime("%Y-%m-%d")
        
        print(f"\n{'='*80}")
        print(f"Processing date: {evaluation_date}")
        print(f"{'='*80}\n")
        
        try:
            workflow.run(company_guid, evaluation_date, sas_token)
        except Exception as e:
            print(f"Error processing {evaluation_date}: {e}")
            # Continue with next date
        
        current_date += timedelta(days=1)


if __name__ == "__main__":
    # Run the main workflow
    main()
    
    # Uncomment to try other examples:
    # example_process_single_file()
    # example_custom_polling()
    # example_batch_by_date_range()

