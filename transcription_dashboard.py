"""
Streamlit Dashboard for Transcription Processing
Tracks progress, statistics, and status of transcription jobs
"""

import streamlit as st
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from azure.storage.blob import BlobServiceClient
import pandas as pd
import time

# Page config
st.set_page_config(
    page_title="Transcription Dashboard",
    page_icon="🎙️",
    layout="wide"
)

# Initialize session state
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = None
if 'refresh_interval' not in st.session_state:
    st.session_state.refresh_interval = 30  # seconds


def get_blob_client(connection_string: str, container_name: str):
    """Get blob service client"""
    try:
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(container_name)
        return container_client
    except Exception as e:
        st.error(f"Error connecting to blob storage: {e}")
        return None


def count_blobs_in_folder(container_client, folder_prefix: str) -> int:
    """Count blobs in a specific folder"""
    try:
        count = 0
        for blob in container_client.list_blobs(name_starts_with=folder_prefix):
            count += 1
        return count
    except:
        return 0


def get_recent_files(container_client, folder_prefix: str, limit: int = 10) -> List[Dict]:
    """Get recent files from a folder"""
    try:
        files = []
        for blob in container_client.list_blobs(name_starts_with=folder_prefix):
            files.append({
                'name': blob.name,
                'size': blob.size,
                'last_modified': blob.last_modified
            })
        # Sort by last modified, most recent first
        files.sort(key=lambda x: x['last_modified'], reverse=True)
        return files[:limit]
    except:
        return []


def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def main():
    st.title("🎙️ Transcription Processing Dashboard")
    st.markdown("---")
    
    # Sidebar for configuration
    with st.sidebar:
        st.header("Configuration")
        
        # Connection string input
        blob_conn_str = st.text_input(
            "Blob Connection String",
            type="password",
            value=os.getenv("BLOB_CONNECTION_STRING", ""),
            help="Azure Blob Storage connection string"
        )
        
        container_name = st.text_input(
            "Container Name",
            value=os.getenv("BLOB_CONTAINER_NAME", "audiofiles"),
            help="Name of the blob container"
        )
        
        # Refresh settings
        st.header("Refresh Settings")
        auto_refresh = st.checkbox("Auto Refresh", value=True)
        refresh_interval = st.slider(
            "Refresh Interval (seconds)",
            min_value=5,
            max_value=300,
            value=30,
            step=5
        )
        st.session_state.refresh_interval = refresh_interval
        
        if st.button("🔄 Refresh Now"):
            st.rerun()
    
    if not blob_conn_str:
        st.warning("⚠️ Please enter Blob Connection String in the sidebar to view statistics")
        st.stop()
    
    # Get container client
    container_client = get_blob_client(blob_conn_str, container_name)
    if not container_client:
        st.error("Failed to connect to blob storage. Please check your connection string.")
        st.stop()
    
    # Check if container exists
    try:
        if not container_client.exists():
            st.error(f"Container '{container_name}' does not exist")
            st.stop()
    except Exception as e:
        st.error(f"Error checking container: {e}")
        st.stop()
    
    # Main dashboard
    col1, col2, col3, col4 = st.columns(4)
    
    # Get statistics
    with st.spinner("Loading statistics..."):
        # Count files in different folders
        total_audio = count_blobs_in_folder(container_client, "")
        processed_count = count_blobs_in_folder(container_client, "Processed/")
        formatted_count = count_blobs_in_folder(container_client, "Transcripts/formatted/")
        raw_count = count_blobs_in_folder(container_client, "Transcripts/raw/")
        
        # Calculate pending
        pending_count = total_audio - processed_count - formatted_count - raw_count
        # Exclude Processed and Transcripts folders from total
        audio_files = [b for b in container_client.list_blobs() 
                      if b.name.endswith(('.wav', '.mp3', '.m4a')) 
                      and not b.name.startswith('Processed/') 
                      and not b.name.startswith('Transcripts/')]
        actual_pending = len(audio_files)
        actual_processed = processed_count
    
    # Statistics Cards
    with col1:
        st.metric(
            "📁 Total Audio Files",
            f"{len(audio_files):,}",
            help="Total audio files in container (excluding Processed/Transcripts)"
        )
    
    with col2:
        st.metric(
            "✅ Processed Files",
            f"{actual_processed:,}",
            delta=f"{actual_processed - actual_pending if actual_processed > actual_pending else 0}",
            help="Files moved to Processed folder"
        )
    
    with col3:
        st.metric(
            "📝 Formatted Transcripts",
            f"{formatted_count:,}",
            help="Formatted transcript files in Transcripts/formatted/"
        )
    
    with col4:
        st.metric(
            "📄 Raw Transcripts",
            f"{raw_count:,}",
            help="Raw JSON transcript files in Transcripts/raw/"
        )
    
    # Progress bar
    st.markdown("---")
    st.subheader("📊 Processing Progress")
    
    if len(audio_files) > 0:
        progress_percent = (actual_processed / len(audio_files)) * 100
        st.progress(progress_percent / 100)
        st.caption(f"Processed: {actual_processed:,} / {len(audio_files):,} ({progress_percent:.1f}%)")
    else:
        st.info("No audio files found in container")
    
    # Detailed Statistics
    st.markdown("---")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📈 Statistics")
        
        # Calculate success rate
        if formatted_count > 0:
            success_rate = (formatted_count / actual_processed * 100) if actual_processed > 0 else 0
        else:
            success_rate = 0
        
        stats_data = {
            "Metric": [
                "Total Audio Files",
                "Processed Files",
                "Pending Files",
                "Formatted Transcripts",
                "Raw Transcripts",
                "Success Rate"
            ],
            "Value": [
                f"{len(audio_files):,}",
                f"{actual_processed:,}",
                f"{actual_pending:,}",
                f"{formatted_count:,}",
                f"{raw_count:,}",
                f"{success_rate:.1f}%"
            ]
        }
        stats_df = pd.DataFrame(stats_data)
        st.dataframe(stats_df, use_container_width=True, hide_index=True)
    
    with col2:
        st.subheader("📋 Recent Activity")
        
        # Get recent processed files
        recent_processed = get_recent_files(container_client, "Processed/", limit=10)
        recent_formatted = get_recent_files(container_client, "Transcripts/formatted/", limit=10)
        
        if recent_processed:
            st.write("**Recently Processed:**")
            for file in recent_processed[:5]:
                file_name = file['name'].split('/')[-1]
                time_ago = datetime.now(file['last_modified'].tzinfo) - file['last_modified']
                if time_ago.total_seconds() < 3600:
                    time_str = f"{int(time_ago.total_seconds() / 60)} minutes ago"
                elif time_ago.total_seconds() < 86400:
                    time_str = f"{int(time_ago.total_seconds() / 3600)} hours ago"
                else:
                    time_str = f"{int(time_ago.days)} days ago"
                st.caption(f"• {file_name} ({time_str})")
        else:
            st.info("No processed files yet")
    
    # File Lists
    st.markdown("---")
    tab1, tab2, tab3 = st.tabs(["📁 Pending Files", "✅ Processed Files", "📝 Transcripts"])
    
    with tab1:
        st.subheader("Pending Audio Files")
        if audio_files:
            # Show first 100 pending files
            pending_list = [
                {
                    "File Name": b.name,
                    "Size": format_file_size(b.size),
                    "Last Modified": b.last_modified.strftime("%Y-%m-%d %H:%M:%S") if b.last_modified else "N/A"
                }
                for b in audio_files[:100]
            ]
            pending_df = pd.DataFrame(pending_list)
            st.dataframe(pending_df, use_container_width=True, hide_index=True)
            if len(audio_files) > 100:
                st.caption(f"Showing first 100 of {len(audio_files):,} files")
        else:
            st.success("✅ No pending files! All files have been processed.")
    
    with tab2:
        st.subheader("Processed Files")
        processed_files = get_recent_files(container_client, "Processed/", limit=500)
        if processed_files:
            processed_list = [
                {
                    "File Name": f['name'].split('/')[-1],
                    "Size": format_file_size(f['size']),
                    "Processed At": f['last_modified'].strftime("%Y-%m-%d %H:%M:%S") if f['last_modified'] else "N/A"
                }
                for f in processed_files
            ]
            processed_df = pd.DataFrame(processed_list)
            st.dataframe(processed_df, use_container_width=True, hide_index=True)
            st.caption(f"Showing {len(processed_files)} most recently processed files")
        else:
            st.info("No processed files yet")
    
    with tab3:
        st.subheader("Transcripts")
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**Formatted Transcripts:**")
            formatted_files = get_recent_files(container_client, "Transcripts/formatted/", limit=100)
            if formatted_files:
                formatted_list = [
                    {
                        "File Name": f['name'].split('/')[-1],
                        "Size": format_file_size(f['size']),
                        "Created": f['last_modified'].strftime("%Y-%m-%d %H:%M:%S") if f['last_modified'] else "N/A"
                    }
                    for f in formatted_files
                ]
                formatted_df = pd.DataFrame(formatted_list)
                st.dataframe(formatted_df, use_container_width=True, hide_index=True)
            else:
                st.info("No formatted transcripts yet")
        
        with col2:
            st.write("**Raw Transcripts (JSON):**")
            raw_files = get_recent_files(container_client, "Transcripts/raw/", limit=100)
            if raw_files:
                raw_list = [
                    {
                        "File Name": f['name'].split('/')[-1],
                        "Size": format_file_size(f['size']),
                        "Created": f['last_modified'].strftime("%Y-%m-%d %H:%M:%S") if f['last_modified'] else "N/A"
                    }
                    for f in raw_files
                ]
                raw_df = pd.DataFrame(raw_list)
                st.dataframe(raw_df, use_container_width=True, hide_index=True)
            else:
                st.info("No raw transcripts yet")
    
    # Auto refresh
    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()
    
    # Footer
    st.markdown("---")
    st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()

