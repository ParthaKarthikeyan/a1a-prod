"""
Backend API for Transcription Dashboard
Provides endpoints for blob storage statistics and file listings
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import logging
from typing import Dict, List, Optional
from datetime import datetime
from azure.storage.blob import BlobServiceClient

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_blob_client(connection_string: str, container_name: str):
    """Get blob container client"""
    try:
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(container_name)
        return container_client
    except Exception as e:
        logger.error(f"Error connecting to blob storage: {e}")
        return None


def count_blobs_in_folder(container_client, folder_prefix: str) -> int:
    """Count blobs in a specific folder"""
    try:
        count = 0
        for blob in container_client.list_blobs(name_starts_with=folder_prefix):
            count += 1
        return count
    except Exception as e:
        logger.error(f"Error counting blobs in {folder_prefix}: {e}")
        return 0


def get_recent_files(container_client, folder_prefix: str, limit: int = 100) -> List[Dict]:
    """Get recent files from a folder"""
    try:
        files = []
        blob_list = container_client.list_blobs(name_starts_with=folder_prefix)
        for blob in blob_list:
            try:
                files.append({
                    'name': blob.name,
                    'size': getattr(blob, 'size', 0),
                    'last_modified': blob.last_modified.isoformat() if blob.last_modified else None
                })
            except Exception as e:
                logger.warning(f"Error processing blob {blob.name}: {e}")
                continue
        
        # Sort by last modified, most recent first
        files.sort(key=lambda x: x['last_modified'] if x['last_modified'] else '', reverse=True)
        return files[:limit]
    except Exception as e:
        logger.error(f"Error getting files from {folder_prefix}: {e}")
        return []


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok"})


@app.route('/api/statistics', methods=['POST'])
def get_statistics():
    """Get transcription statistics"""
    try:
        data = request.json
        connection_string = data.get('connection_string')
        container_name = data.get('container_name', 'audiofiles')
        
        if not connection_string:
            return jsonify({"error": "Connection string is required"}), 400
        
        container_client = get_blob_client(connection_string, container_name)
        if not container_client:
            return jsonify({"error": "Failed to connect to blob storage"}), 500
        
        if not container_client.exists():
            return jsonify({"error": f"Container '{container_name}' does not exist"}), 404
        
        # Count files in different folders
        processed_count = count_blobs_in_folder(container_client, "Processed/")
        formatted_count = count_blobs_in_folder(container_client, "Transcripts/formatted/")
        raw_count = count_blobs_in_folder(container_client, "Transcripts/raw/")
        
        # Get audio files (excluding Processed and Transcripts folders)
        audio_files = []
        for blob in container_client.list_blobs():
            if blob.name.endswith(('.wav', '.mp3', '.m4a')):
                if not blob.name.startswith('Processed/') and not blob.name.startswith('Transcripts/'):
                    audio_files.append({
                        'name': blob.name,
                        'size': getattr(blob, 'size', 0),
                        'last_modified': blob.last_modified.isoformat() if blob.last_modified else None
                    })
        
        total_audio = len(audio_files)
        processed = processed_count
        pending = total_audio
        
        # Calculate success rate
        success_rate = (formatted_count / processed * 100) if processed > 0 else 0
        
        return jsonify({
            "total_audio_files": total_audio,
            "processed_files": processed,
            "pending_files": pending,
            "formatted_transcripts": formatted_count,
            "raw_transcripts": raw_count,
            "success_rate": round(success_rate, 2),
            "progress_percent": round((processed / total_audio * 100) if total_audio > 0 else 0, 2)
        })
    except Exception as e:
        logger.exception("Error getting statistics")
        return jsonify({"error": str(e)}), 500


@app.route('/api/files/pending', methods=['POST'])
def get_pending_files():
    """Get pending audio files"""
    try:
        data = request.json
        connection_string = data.get('connection_string')
        container_name = data.get('container_name', 'audiofiles')
        limit = data.get('limit', 100)
        
        if not connection_string:
            return jsonify({"error": "Connection string is required"}), 400
        
        container_client = get_blob_client(connection_string, container_name)
        if not container_client:
            return jsonify({"error": "Failed to connect to blob storage"}), 500
        
        # Get audio files (excluding Processed and Transcripts folders)
        audio_files = []
        for blob in container_client.list_blobs():
            if blob.name.endswith(('.wav', '.mp3', '.m4a')):
                if not blob.name.startswith('Processed/') and not blob.name.startswith('Transcripts/'):
                    audio_files.append({
                        'name': blob.name,
                        'size': getattr(blob, 'size', 0),
                        'last_modified': blob.last_modified.isoformat() if blob.last_modified else None
                    })
        
        return jsonify({
            "files": audio_files[:limit],
            "total": len(audio_files)
        })
    except Exception as e:
        logger.exception("Error getting pending files")
        return jsonify({"error": str(e)}), 500


@app.route('/api/files/processed', methods=['POST'])
def get_processed_files():
    """Get processed files"""
    try:
        data = request.json
        connection_string = data.get('connection_string')
        container_name = data.get('container_name', 'audiofiles')
        limit = data.get('limit', 500)
        
        if not connection_string:
            return jsonify({"error": "Connection string is required"}), 400
        
        container_client = get_blob_client(connection_string, container_name)
        if not container_client:
            return jsonify({"error": "Failed to connect to blob storage"}), 500
        
        processed_files = get_recent_files(container_client, "Processed/", limit=limit)
        
        # Format file names
        formatted_files = []
        for f in processed_files:
            file_name = f['name'].split('/')[-1] if '/' in f['name'] else f['name']
            formatted_files.append({
                'name': file_name,
                'full_path': f['name'],
                'size': f.get('size', 0),
                'processed_at': f.get('last_modified')
            })
        
        return jsonify({
            "files": formatted_files,
            "total": len(formatted_files)
        })
    except Exception as e:
        logger.exception("Error getting processed files")
        return jsonify({"error": str(e)}), 500


@app.route('/api/files/formatted', methods=['POST'])
def get_formatted_transcripts():
    """Get formatted transcript files"""
    try:
        data = request.json
        connection_string = data.get('connection_string')
        container_name = data.get('container_name', 'audiofiles')
        limit = data.get('limit', 100)
        
        if not connection_string:
            return jsonify({"error": "Connection string is required"}), 400
        
        container_client = get_blob_client(connection_string, container_name)
        if not container_client:
            return jsonify({"error": "Failed to connect to blob storage"}), 500
        
        formatted_files = get_recent_files(container_client, "Transcripts/formatted/", limit=limit)
        
        # Format file names
        formatted_list = []
        for f in formatted_files:
            file_name = f['name'].split('/')[-1] if '/' in f['name'] else f['name']
            formatted_list.append({
                'name': file_name,
                'full_path': f['name'],
                'size': f.get('size', 0),
                'created': f.get('last_modified')
            })
        
        return jsonify({
            "files": formatted_list,
            "total": len(formatted_list)
        })
    except Exception as e:
        logger.exception("Error getting formatted transcripts")
        return jsonify({"error": str(e)}), 500


@app.route('/api/files/raw', methods=['POST'])
def get_raw_transcripts():
    """Get raw transcript files"""
    try:
        data = request.json
        connection_string = data.get('connection_string')
        container_name = data.get('container_name', 'audiofiles')
        limit = data.get('limit', 100)
        
        if not connection_string:
            return jsonify({"error": "Connection string is required"}), 400
        
        container_client = get_blob_client(connection_string, container_name)
        if not container_client:
            return jsonify({"error": "Failed to connect to blob storage"}), 500
        
        raw_files = get_recent_files(container_client, "Transcripts/raw/", limit=limit)
        
        # Format file names
        formatted_list = []
        for f in raw_files:
            file_name = f['name'].split('/')[-1] if '/' in f['name'] else f['name']
            formatted_list.append({
                'name': file_name,
                'full_path': f['name'],
                'size': f.get('size', 0),
                'created': f.get('last_modified')
            })
        
        return jsonify({
            "files": formatted_list,
            "total": len(formatted_list)
        })
    except Exception as e:
        logger.exception("Error getting raw transcripts")
        return jsonify({"error": str(e)}), 500


@app.route('/api/recent-activity', methods=['POST'])
def get_recent_activity():
    """Get recent activity"""
    try:
        data = request.json
        connection_string = data.get('connection_string')
        container_name = data.get('container_name', 'audiofiles')
        limit = data.get('limit', 10)
        
        if not connection_string:
            return jsonify({"error": "Connection string is required"}), 400
        
        container_client = get_blob_client(connection_string, container_name)
        if not container_client:
            return jsonify({"error": "Failed to connect to blob storage"}), 500
        
        processed_files = get_recent_files(container_client, "Processed/", limit=limit)
        
        activity = []
        for f in processed_files:
            file_name = f['name'].split('/')[-1] if '/' in f['name'] else f['name']
            last_modified = f.get('last_modified')
            if last_modified:
                try:
                    mod_time = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
                    now = datetime.now(mod_time.tzinfo)
                    time_diff = now - mod_time
                    
                    if time_diff.total_seconds() < 3600:
                        time_str = f"{int(time_diff.total_seconds() / 60)} minutes ago"
                    elif time_diff.total_seconds() < 86400:
                        time_str = f"{int(time_diff.total_seconds() / 3600)} hours ago"
                    else:
                        time_str = f"{int(time_diff.days)} days ago"
                except:
                    time_str = "Unknown"
            else:
                time_str = "Unknown"
            
            activity.append({
                'file_name': file_name,
                'time_ago': time_str,
                'processed_at': last_modified
            })
        
        return jsonify({"activity": activity})
    except Exception as e:
        logger.exception("Error getting recent activity")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))  # Changed to 5001 to avoid conflicts
    app.run(host='0.0.0.0', port=port, debug=True)

