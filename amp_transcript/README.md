# AMP Transcription Workflow

This directory contains a Python implementation of an Azure Logic App workflow for audio transcription using VoiceGain API.

## Purpose

This is a **standalone project** that converts an Azure Logic App workflow (originally defined in JSON) into Python code. It is **separate from the main autoqa_queueProcess project**.

## Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r requirements_transcription.txt
   ```

2. **Configure credentials:**
   ```bash
   cp transcription.env.example .env
   # Edit .env with your credentials
   ```

3. **Validate setup:**
   ```bash
   python validate_configuration.py
   ```

4. **Run workflow:**
   ```bash
   python transcription_workflow.py
   ```

## Documentation

- **`TRANSCRIPTION_WORKFLOW_README.md`** - Complete usage guide
- **`LOGIC_APP_TO_PYTHON_CONVERSION.md`** - Detailed conversion documentation
- **`QUICK_REFERENCE_LOGIC_APP_TO_PYTHON.md`** - Quick reference guide
- **`example_transcription_usage.py`** - Usage examples
- **`validate_configuration.py`** - Configuration validator

## Files

- `transcription_workflow.py` - Main workflow implementation
- `requirements_transcription.txt` - Python dependencies
- `transcription.env.example` - Environment variables template

## Note

This project is isolated from the main `autoqa_queueProcess` project and can be used independently.

