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

# VoiceGain token - hardcoded for convenience
VOICEGAIN_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJiOWE4Yzc4ZS1hNjU3LTRiNDItOGRmYy03NzgxOTkwYzJiMzEiLCJhdWQiOiJodHRwczovL2FwaS52b2ljZWdhaW4uYWkvdjEiLCJzdWIiOiI4Y2M0YjU3Yy0wYjdhLTQ0NDItOTkzOC0zMzg3MTc1OTA1YmMifQ.u0MXajHy51MzTfUl6RtabHMP-TRSxsZRjGfNsVtecIs"

# Simple cache for statistics (expires after 60 seconds)
import time
_stats_cache = {}
_cache_ttl = 60  # seconds

# Processing status tracker
_processing_status = {
    "is_running": False,
    "started_at": None,
    "files_submitted": 0,
    "files_completed": 0,
    "files_failed": 0,
    "current_file": None,
    "log_messages": [],
    "last_update": None
}


def get_blob_client(connection_string: str, container_name: str):
    """Get blob container client"""
    try:
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(container_name)
        return container_client
    except Exception as e:
        logger.error(f"Error connecting to blob storage: {e}")
        return None


def count_blobs_in_folder(container_client, folder_prefix: str, max_count: int = None) -> int:
    """Count blobs in a specific folder - optionally with limit to prevent timeout"""
    try:
        count = 0
        for blob in container_client.list_blobs(name_starts_with=folder_prefix):
            count += 1
            # Stop counting after max_count to prevent timeout on large containers (if limit is set)
            if max_count and count >= max_count:
                logger.info(f"Reached max count ({max_count}) for {folder_prefix}, returning estimate")
                return max_count  # Return the limit as estimate
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
    """Get transcription statistics from cache file (fast) or live scan (slow fallback)"""
    import json
    
    try:
        # Try to read from cache file first (instant response)
        cache_file = os.path.join(os.path.dirname(__file__), 'stats_cache.json')
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    cached_stats = json.load(f)
                logger.info(f"Returning cached stats (scanned: {cached_stats.get('last_scan', 'unknown')})")
                return jsonify(cached_stats)
            except Exception as e:
                logger.warning(f"Could not read cache file: {e}")
        
        # Fallback: Quick live scan with limits
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
        
        # Count all processed files from multiple locations
        # Files can be in Archive/, Processed/, or Transcripts/formatted/
        archive_count = count_blobs_in_folder(container_client, "Archive/", max_count=None)
        processed_count = count_blobs_in_folder(container_client, "Processed/", max_count=None)
        formatted_count = count_blobs_in_folder(container_client, "Transcripts/formatted/", max_count=None)
        raw_count = count_blobs_in_folder(container_client, "Transcripts/raw/", max_count=None)
        
        # Total processed files = sum of all locations (avoid double counting)
        # Archive/ contains the original audio files that were processed
        # Processed/ contains moved audio files
        # Transcripts/formatted/ contains the transcripts
        # We'll use Archive/ as the primary count since that's where processed audio goes
        # But also count transcripts to show what's been transcribed
        total_processed = max(archive_count, formatted_count)  # Use the larger of the two to avoid double counting
        
        # Quick pending sample (files in root, not in Archive/Processed/Transcripts/)
        pending_sample = 0
        for blob in container_client.list_blobs():
            if pending_sample >= 100:
                break
            blob_name = blob.name
            if (blob_name.endswith(('.wav', '.mp3', '.m4a')) and 
                not blob_name.startswith(('Archive/', 'Processed/', 'Transcripts/')) and
                '/' not in blob_name):
                pending_sample += 1
        
        result = {
            "total_audio_files": total_processed + pending_sample,
            "processed_files": total_processed,
            "pending_files": pending_sample,
            "formatted_transcripts": formatted_count,
            "raw_transcripts": raw_count,
            "archive_files": archive_count,
            "processed_folder_files": processed_count,
            "success_rate": 100.0,
            "progress_percent": round((total_processed / (total_processed + pending_sample) * 100) if (total_processed + pending_sample) > 0 else 0, 2),
            "taxonomy_files": 0,
            "latest_taxonomy_file": None,
            "latest_taxonomy_time": None,
            "note": "Live scan (limited) - start stats_updater.py for accurate counts"
        }
        
        return jsonify(result)
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
    """Get recent activity from cache or live scan"""
    import json
    
    try:
        # Try cache first
        cache_file = os.path.join(os.path.dirname(__file__), 'stats_cache.json')
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    cached_stats = json.load(f)
                if 'recent_activity' in cached_stats:
                    return jsonify({"activity": cached_stats['recent_activity']})
            except:
                pass
        
        # Fallback to live scan
        data = request.json
        connection_string = data.get('connection_string')
        container_name = data.get('container_name', 'audiofiles')
        limit = data.get('limit', 10)
        
        if not connection_string:
            return jsonify({"error": "Connection string is required"}), 400
        
        container_client = get_blob_client(connection_string, container_name)
        if not container_client:
            return jsonify({"error": "Failed to connect to blob storage"}), 500
        
        # Get recent archived files (processed audio)
        processed_files = get_recent_files(container_client, "Archive/", limit=limit)
        
        # Get recent transcripts (this shows active processing)
        formatted_transcripts = get_recent_files(container_client, "Transcripts/formatted/", limit=limit)
        raw_transcripts = get_recent_files(container_client, "Transcripts/raw/", limit=limit)
        
        activity = []
        
        # Add processed files
        for f in processed_files:
            file_name = f['name'].split('/')[-1] if '/' in f['name'] else f['name']
            last_modified = f.get('last_modified')
            if last_modified:
                try:
                    mod_time = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
                    now = datetime.now(mod_time.tzinfo)
                    time_diff = now - mod_time
                    
                    if time_diff.total_seconds() < 60:
                        time_str = f"{int(time_diff.total_seconds())} seconds ago"
                    elif time_diff.total_seconds() < 3600:
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
                'processed_at': last_modified,
                'type': 'processed'
            })
        
        # Add recent transcripts (indicates active processing)
        for f in formatted_transcripts:
            file_name = f['name'].split('/')[-1] if '/' in f['name'] else f['name']
            last_modified = f.get('last_modified')
            if last_modified:
                try:
                    mod_time = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
                    now = datetime.now(mod_time.tzinfo)
                    time_diff = now - mod_time
                    
                    if time_diff.total_seconds() < 60:
                        time_str = f"{int(time_diff.total_seconds())} seconds ago"
                    elif time_diff.total_seconds() < 3600:
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
                'file_name': f"📝 {file_name}",
                'time_ago': time_str,
                'processed_at': last_modified,
                'type': 'transcript'
            })
        
        # Sort by time (most recent first) and limit
        activity.sort(key=lambda x: x.get('processed_at', ''), reverse=True)
        activity = activity[:limit]
        
        return jsonify({"activity": activity})
    except Exception as e:
        logger.exception("Error getting recent activity")
        return jsonify({"error": str(e)}), 500


@app.route('/api/audio-url', methods=['POST'])
def get_audio_url():
    """Generate a SAS URL for an audio file"""
    try:
        data = request.json
        connection_string = data.get('connection_string')
        container_name = data.get('container_name', 'audiofiles')
        blob_name = data.get('blob_name')
        
        if not connection_string:
            return jsonify({"error": "Connection string is required"}), 400
        
        if not blob_name:
            return jsonify({"error": "Blob name is required"}), 400
        
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(container_name)
        
        # Generate SAS token
        from datetime import timedelta
        from azure.storage.blob import generate_container_sas, ContainerSasPermissions
        
        conn_parts = dict(part.split('=', 1) for part in connection_string.split(';') if '=' in part)
        account_key = conn_parts.get('AccountKey', '')
        account_name = blob_service_client.account_name
        
        if account_key:
            sas_token = generate_container_sas(
                account_name=account_name,
                container_name=container_name,
                account_key=account_key,
                permission=ContainerSasPermissions(read=True),
                expiry=datetime.utcnow() + timedelta(hours=24)
            )
            
            blob_url = f"https://{account_name}.blob.core.windows.net/{container_name}/{blob_name}"
            separator = "&" if "?" in blob_url else "?"
            blob_url = f"{blob_url}{separator}{sas_token}"
            
            return jsonify({"url": blob_url})
        else:
            return jsonify({"error": "Could not generate SAS token"}), 500
            
    except Exception as e:
        logger.exception("Error generating audio URL")
        return jsonify({"error": str(e)}), 500


@app.route('/api/transcript', methods=['POST'])
def get_transcript():
    """Get transcript content for a file"""
    try:
        data = request.json
        connection_string = data.get('connection_string')
        container_name = data.get('container_name', 'audiofiles')
        transcript_path = data.get('transcript_path')
        
        if not connection_string:
            return jsonify({"error": "Connection string is required"}), 400
        
        if not transcript_path:
            return jsonify({"error": "Transcript path is required"}), 400
        
        container_client = get_blob_client(connection_string, container_name)
        if not container_client:
            return jsonify({"error": "Failed to connect to blob storage"}), 500
        
        blob_client = container_client.get_blob_client(transcript_path)
        
        if not blob_client.exists():
            return jsonify({"error": "Transcript not found"}), 404
        
        # Download transcript content
        transcript_content = blob_client.download_blob().readall().decode('utf-8')
        
        return jsonify({
            "transcript": transcript_content,
            "path": transcript_path
        })
    except Exception as e:
        logger.exception("Error getting transcript")
        return jsonify({"error": str(e)}), 500


@app.route('/api/process/start', methods=['POST'])
def start_batch_processing():
    """Start batch transcription processing"""
    try:
        import subprocess
        import threading
        
        data = request.json
        connection_string = data.get('connection_string')
        container_name = data.get('container_name', 'audiofiles')
        source_prefix = data.get('source_prefix', '')
        max_files = data.get('max_files')  # Optional limit
        
        if not connection_string:
            return jsonify({"error": "Connection string is required"}), 400
        
        # Get VoiceGain token from hardcoded value or environment variable
        voicegain_token = VOICEGAIN_TOKEN or os.getenv('VOICEGAIN_TOKEN')
        if not voicegain_token:
            return jsonify({"error": "VOICEGAIN_TOKEN is not configured."}), 400
        
        # Set environment variables for the subprocess
        env = os.environ.copy()
        env['BLOB_CONNECTION_STRING'] = connection_string
        env['VOICEGAIN_TOKEN'] = voicegain_token
        env['BLOB_CONTAINER_NAME'] = container_name
        if source_prefix:
            env['SOURCE_PREFIX'] = source_prefix
        if max_files:
            env['MAX_FILES'] = str(max_files)
        
        # Get the path to blob_transcription_processor.py
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        processor_script = os.path.join(script_dir, 'blob_transcription_processor.py')
        
        if not os.path.exists(processor_script):
            return jsonify({"error": "Transcription processor script not found"}), 500
        
        # Start processing in a background thread with status tracking
        def run_processor():
            global _processing_status
            _processing_status["is_running"] = True
            _processing_status["started_at"] = datetime.now().isoformat()
            _processing_status["files_submitted"] = 0
            _processing_status["files_completed"] = 0
            _processing_status["files_failed"] = 0
            _processing_status["log_messages"] = ["Starting transcription processor..."]
            _processing_status["last_update"] = datetime.now().isoformat()
            
            try:
                # Run with real-time output capture
                process = subprocess.Popen(
                    ['python', '-u', processor_script],  # -u for unbuffered output
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )
                
                # Read output line by line
                for line in iter(process.stdout.readline, ''):
                    line = line.strip()
                    if line:
                        # Parse progress from log lines
                        import re
                        
                        # Extract progress from patterns like [Progress: 200/149779] or [200/149779]
                        progress_match = re.search(r'\[(?:Progress:\s*)?(\d+)/(\d+)\]', line)
                        if progress_match:
                            current = int(progress_match.group(1))
                            total = int(progress_match.group(2))
                            _processing_status["files_submitted"] = total
                            _processing_status["current_progress"] = current
                            _processing_status["current_file"] = line[-100:] if len(line) > 100 else line
                        
                        # Count successes - look for various success patterns
                        # Match: "✓ Success:" or "Success:" or "completed successfully"
                        if re.search(r'✓\s*Success|Success:|completed successfully', line, re.IGNORECASE):
                            _processing_status["files_completed"] += 1
                        
                        # Count failures - look for failure patterns
                        # Match: "✗ Failed:" or "Failed:" or "Error:" or "Exception"
                        if re.search(r'✗\s*Failed|Failed:|Error:|Exception', line, re.IGNORECASE):
                            _processing_status["files_failed"] += 1
                        
                        # Update current file for any processing line
                        if "Processing:" in line or "Progress:" in line:
                            _processing_status["current_file"] = line[-100:] if len(line) > 100 else line
                        # Log important messages
                        if any(x in line for x in ["batch", "Batch", "Starting", "Complete", "Error", "Progress"]):
                            _processing_status["log_messages"].append(line[:200])
                            _processing_status["log_messages"] = _processing_status["log_messages"][-20:]
                        _processing_status["last_update"] = datetime.now().isoformat()
                
                process.wait()
                _processing_status["log_messages"].append(f"Processing finished with code: {process.returncode}")
                logger.info(f"Processing completed with return code: {process.returncode}")
                
            except Exception as e:
                _processing_status["log_messages"].append(f"Error: {str(e)}")
                logger.exception(f"Error running processor: {e}")
            finally:
                _processing_status["is_running"] = False
                _processing_status["last_update"] = datetime.now().isoformat()
        
        # Start the processor in a background thread
        thread = threading.Thread(target=run_processor, daemon=True)
        thread.start()
        
        return jsonify({
            "status": "started",
            "message": "Batch processing started in background",
            "container": container_name,
            "source_prefix": source_prefix or "(root)",
            "max_files": max_files or "all"
        })
        
    except Exception as e:
        logger.exception("Error starting batch processing")
        return jsonify({"error": str(e)}), 500


@app.route('/api/process/status', methods=['GET'])
def get_processing_status():
    """Get current processing status"""
    return jsonify(_processing_status)


@app.route('/api/process/stop', methods=['POST'])
def stop_batch_processing():
    """Stop batch transcription processing"""
    global _processing_status
    try:
        import psutil
        import os
        
        # Find and kill blob_transcription_processor.py processes
        killed_count = 0
        current_pid = os.getpid()
        
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] and 'python' in proc.info['name'].lower():
                    cmdline = proc.info.get('cmdline', [])
                    if cmdline and any('blob_transcription_processor.py' in str(arg) for arg in cmdline):
                        if proc.info['pid'] != current_pid:
                            proc.kill()
                            killed_count += 1
                            logger.info(f"Killed transcription process: PID {proc.info['pid']}")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        # Reset processing status
        _processing_status["is_running"] = False
        _processing_status["last_update"] = datetime.now().isoformat()
        _processing_status["log_messages"].append("Processing stopped by user")
        
        return jsonify({
            "status": "stopped",
            "message": f"Stopped {killed_count} transcription process(es)",
            "killed_processes": killed_count
        })
        
    except ImportError:
        # Fallback if psutil not available - just update status
        _processing_status["is_running"] = False
        _processing_status["last_update"] = datetime.now().isoformat()
        _processing_status["log_messages"].append("Processing stopped (manual stop requested)")
        
        return jsonify({
            "status": "stopped",
            "message": "Processing status set to stopped. You may need to manually kill Python processes.",
            "note": "Install psutil for automatic process termination"
        })
    except Exception as e:
        logger.exception("Error stopping batch processing")
        return jsonify({"error": str(e)}), 500


@app.route('/api/voicegain/stats', methods=['GET'])
def get_voicegain_stats():
    """Get VoiceGain job statistics"""
    try:
        from voicegain_tracker import get_stats
        return jsonify(get_stats())
    except ImportError:
        return jsonify({"error": "VoiceGain tracker not available"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/voicegain/jobs', methods=['GET'])
def get_voicegain_jobs():
    """Get recent VoiceGain jobs"""
    try:
        from voicegain_tracker import get_recent_jobs
        limit = request.args.get('limit', 50, type=int)
        return jsonify({"jobs": get_recent_jobs(limit)})
    except ImportError:
        return jsonify({"error": "VoiceGain tracker not available"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/queue/stats', methods=['GET'])
def get_queue_stats_api():
    """Get job queue statistics"""
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from job_queue import get_queue_stats
        return jsonify(get_queue_stats())
    except ImportError:
        return jsonify({"error": "Job queue not available"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))  # Changed to 5001 to avoid conflicts
    app.run(host='0.0.0.0', port=port, debug=True)

