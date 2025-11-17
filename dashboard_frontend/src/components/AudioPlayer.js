import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './AudioPlayer.css';

function AudioPlayer({ apiUrl, connectionString, containerName }) {
  const [audioFiles, setAudioFiles] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);
  const [transcript, setTranscript] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [audioUrl, setAudioUrl] = useState(null);
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const audioRef = useRef(null);

  useEffect(() => {
    fetchAudioFiles();
  }, [connectionString, containerName]);

  const fetchAudioFiles = async () => {
    if (!connectionString || connectionString.trim() === '') {
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const response = await axios.post(`${apiUrl}/api/files/processed`, {
        connection_string: connectionString,
        container_name: containerName,
        limit: 500
      });
      setAudioFiles(response.data.files || []);
    } catch (err) {
      console.error('Error fetching audio files:', err);
      setError(err.response?.data?.error || err.message || 'Failed to fetch audio files');
    } finally {
      setLoading(false);
    }
  };

  const handleFileSelect = async (file) => {
    // Stop current playback if any
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      setIsPlaying(false);
    }

    setSelectedFile(file);
    setTranscript(null);
    setAudioUrl(null);
    setTranscriptLoading(true);
    setError(null);
    setIsPlaying(false);

    try {
      // Get audio URL - try full_path first, then construct from name
      const blobPath = file.full_path || (file.name.startsWith('Processed/') ? file.name : `Processed/${file.name}`);
      const audioUrlResponse = await axios.post(`${apiUrl}/api/audio-url`, {
        connection_string: connectionString,
        container_name: containerName,
        blob_name: blobPath
      });
      setAudioUrl(audioUrlResponse.data.url);

      // Get transcript
      const transcriptName = file.name.replace(/\.(mp3|wav|m4a)$/i, '.txt');
      const transcriptResponse = await axios.post(`${apiUrl}/api/transcript`, {
        connection_string: connectionString,
        container_name: containerName,
        transcript_path: `Transcripts/formatted/${transcriptName}`
      });
      
      if (transcriptResponse.data.transcript) {
        setTranscript(transcriptResponse.data.transcript);
      } else {
        setError('Transcript not found for this file');
      }
    } catch (err) {
      console.error('Error loading audio/transcript:', err);
      setError(err.response?.data?.error || err.message || 'Failed to load audio or transcript');
    } finally {
      setTranscriptLoading(false);
    }
  };

  const handlePlayPause = () => {
    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause();
        setIsPlaying(false);
      } else {
        audioRef.current.play();
        setIsPlaying(true);
      }
    }
  };

  const handleAudioEnded = () => {
    setIsPlaying(false);
  };

  const handleAudioPlay = () => {
    setIsPlaying(true);
  };

  const handleAudioPause = () => {
    setIsPlaying(false);
  };

  return (
    <div className="audio-player-container">
      <div className="audio-player-header">
        <h3>🎧 Audio Player with Transcript</h3>
        <button onClick={fetchAudioFiles} className="refresh-button">
          🔄 Refresh
        </button>
      </div>

      <div className="audio-player-layout">
        <div className="audio-files-list">
          <h4>Processed Audio Files</h4>
          {loading ? (
            <div className="loading">Loading files...</div>
          ) : error ? (
            <div className="error">{error}</div>
          ) : audioFiles.length === 0 ? (
            <div className="empty">No processed audio files found</div>
          ) : (
            <div className="files-list">
              {audioFiles.map((file, idx) => (
                <div
                  key={idx}
                  className={`file-item ${selectedFile?.name === file.name ? 'selected' : ''}`}
                  onClick={() => handleFileSelect(file)}
                >
                  <div className="file-name">{file.name}</div>
                  <div className="file-size">{formatFileSize(file.size || 0)}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="audio-player-content">
          {selectedFile ? (
            <>
              <div className="audio-player-section">
                <h4>Now Playing: {selectedFile.name}</h4>
                {audioUrl ? (
                  <div className="audio-controls">
                    <div className="play-button-container">
                      <button 
                        onClick={handlePlayPause}
                        className={`play-button ${isPlaying ? 'playing' : ''}`}
                        disabled={transcriptLoading}
                      >
                        {isPlaying ? '⏸️ Pause' : '▶️ Play'}
                      </button>
                    </div>
                    <audio
                      ref={audioRef}
                      src={audioUrl}
                      onEnded={handleAudioEnded}
                      onPlay={handleAudioPlay}
                      onPause={handleAudioPause}
                      className="audio-element"
                      style={{ display: 'none' }}
                    />
                    <div className="audio-info">
                      <p className="audio-status">
                        {isPlaying ? '▶️ Playing' : '⏸️ Paused'}
                      </p>
                    </div>
                  </div>
                ) : transcriptLoading ? (
                  <div className="loading">Loading audio...</div>
                ) : (
                  <div className="error">Failed to load audio</div>
                )}
              </div>

              <div className="transcript-section">
                <h4>Transcript</h4>
                {transcriptLoading ? (
                  <div className="loading">Loading transcript...</div>
                ) : error ? (
                  <div className="error">{error}</div>
                ) : transcript ? (
                  <div className="transcript-content">
                    {transcript.split('\n').map((line, idx) => (
                      <div key={idx} className="transcript-line">
                        {line}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty">No transcript available</div>
                )}
              </div>
            </>
          ) : (
            <div className="no-selection">
              <p>Select an audio file from the list to play and view its transcript</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function formatFileSize(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

export default AudioPlayer;

