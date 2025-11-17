import React from 'react';
import './StatisticsCards.css';

function StatisticsCards({ statistics }) {
  const cards = [
    {
      title: '📁 Total Audio Files',
      value: statistics.total_audio_files,
      help: 'Total audio files in container'
    },
    {
      title: '✅ Processed Files',
      value: statistics.processed_files,
      delta: statistics.processed_files,
      help: 'Files moved to Processed folder'
    },
    {
      title: '📝 Formatted Transcripts',
      value: statistics.formatted_transcripts,
      help: 'Formatted transcript files'
    },
    {
      title: '📄 Raw Transcripts',
      value: statistics.raw_transcripts,
      help: 'Raw JSON transcript files'
    }
  ];

  return (
    <div className="statistics-cards">
      {cards.map((card, idx) => (
        <div key={idx} className="stat-card">
          <div className="stat-card-title">{card.title}</div>
          <div className="stat-card-value">{card.value.toLocaleString()}</div>
          {card.delta !== undefined && (
            <div className="stat-card-delta">+{card.delta}</div>
          )}
          <div className="stat-card-help">{card.help}</div>
        </div>
      ))}
    </div>
  );
}

export default StatisticsCards;

