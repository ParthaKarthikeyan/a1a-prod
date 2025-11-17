import React from 'react';
import './FileTable.css';

function FileTable({ files, columns }) {
  if (!files || files.length === 0) {
    return <div className="empty-table">No files to display</div>;
  }

  return (
    <div className="file-table-container">
      <table className="file-table">
        <thead>
          <tr>
            {columns.map((col, idx) => (
              <th key={idx}>{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {files.map((file, idx) => (
            <tr key={idx}>
              <td className="file-name">{file.name}</td>
              <td className="file-size">{file.size}</td>
              <td className="file-date">{file.modified}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default FileTable;

