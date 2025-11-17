# Transcription Dashboard - React Frontend

A modern React dashboard for monitoring transcription processing progress.

## Features

- Real-time statistics and progress tracking
- File management tabs (Pending, Processed, Transcripts)
- Auto-refresh functionality
- Responsive design
- Modern UI with smooth animations

## Prerequisites

- Node.js 16+ and npm
- Backend API running (see dashboard_backend)

## Installation

1. Install dependencies:
   ```bash
   npm install
   ```

2. Create `.env` file (optional):
   ```
   REACT_APP_API_URL=http://localhost:5000
   ```

## Running the App

1. Start the backend API (in `dashboard_backend` folder):
   ```bash
   python app.py
   ```

2. Start the React app:
   ```bash
   npm start
   ```

3. Open http://localhost:3000 in your browser

## Building for Production

```bash
npm run build
```

This creates an optimized production build in the `build` folder.

