"""
Azure Durable Functions implementation of the transcription workflow.
The orchestrator can discover work items either inside an Azure Storage
container (via Blob/SFTP endpoint) or a local directory, and schedules
each transcription as a separate activity function.
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import azure.durable_functions as df  # type: ignore[import]
import azure.functions as func  # type: ignore[import]
import requests
from azure.storage.blob import BlobServiceClient

# Configure module-level logger for Azure Functions
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class TranscriptionWorkflow:
    """Encapsulates the transcription process for a single audio asset."""

    def __init__(
        self,
        voicegain_bearer_token: str,
        blob_connection_string: Optional[str] = None,
        azure_function_url: Optional[str] = None,
        audio_base_url: Optional[str] = None,
        blob_container_name: str = "autoqa",
    ) -> None:
        self.voicegain_token = voicegain_bearer_token
        self.azure_function_url = azure_function_url
        self.audio_base_url = audio_base_url.rstrip("/") if audio_base_url else None
        self.blob_service_client = (
            BlobServiceClient.from_connection_string(blob_connection_string)
            if blob_connection_string
            else None
        )
        self.blob_container_name = blob_container_name

        # Runtime variables populated during execution
        self.session_url: Optional[str] = None
        self.results_phase: str = ""
        self.status: str = ""

    @staticmethod
    def _ensure_iterable(value: Any) -> Iterable[Dict[str, Any]]:
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
        return []

    def list_audio_items_from_directory(
        self,
        target_directory: str,
        metadata_extensions: Optional[List[str]] = None,
        audio_extensions: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Parse the target directory to discover audio items. Metadata JSON files
        can optionally provide structured records that include 'audiopath' entries.

        Args:
            target_directory: The root directory to inspect.
            metadata_extensions: File extensions considered metadata (default: .json).
            audio_extensions: File extensions treated as raw audio (default: .wav, .mp3, .m4a).

        Returns:
            A list of dictionaries representing audio records.
        """
        metadata_extensions = metadata_extensions or [".json"]
        audio_extensions = audio_extensions or [".wav", ".mp3", ".m4a"]

        discovered: Dict[str, Dict[str, Any]] = {}
        logger.info("Scanning directory %s for transcription work items", target_directory)

        for root, _, files in os.walk(target_directory):
            for filename in files:
                file_path = os.path.join(root, filename)
                lower_name = filename.lower()

                if any(lower_name.endswith(ext) for ext in metadata_extensions):
                    try:
                        with open(file_path, "r", encoding="utf-8") as handle:
                            payload = json.load(handle)
                    except (json.JSONDecodeError, OSError) as exc:
                        logger.warning(
                            "Skipping metadata file %s due to error: %s",
                            file_path,
                            exc,
                        )
                        continue

                    for record in self._ensure_iterable(payload):
                        if not isinstance(record, dict):
                            continue
                        audio_path = record.get("audiopath")
                        if not audio_path:
                            continue
                        key = audio_path.replace("\\", "/")
                        discovered[key] = {
                            **record,
                            "audiopath": key,
                            "source_metadata": file_path,
                        }

                elif any(lower_name.endswith(ext) for ext in audio_extensions):
                    key = os.path.relpath(file_path, target_directory).replace("\\", "/")
                    discovered.setdefault(
                        key,
                        {
                            "audiopath": key,
                            "source_metadata": None,
                        },
                    )

        records = list(discovered.values())
        logger.info("Discovered %d audio items to process", len(records))
        return records

    def list_audio_items_from_storage(
        self,
        connection_string: str,
        container_name: str,
        directory: str = "",
        metadata_extensions: Optional[List[str]] = None,
        audio_extensions: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Discover audio items within an Azure Storage container directory.

        Args:
            connection_string: Azure Storage connection string with SFTP/Blob access.
            container_name: Name of the container holding audio artifacts.
            directory: Directory/prefix to scan for blobs.
            metadata_extensions: File extensions considered metadata (default: .json).
            audio_extensions: File extensions treated as raw audio.

        Returns:
            A list of dictionaries representing audio records.
        """
        metadata_extensions = metadata_extensions or [".json"]
        audio_extensions = audio_extensions or [".wav", ".mp3", ".m4a"]

        service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = service_client.get_container_client(container_name)

        prefix = directory or ""
        if prefix and not prefix.endswith("/"):
            prefix = f"{prefix}/"

        discovered: Dict[str, Dict[str, Any]] = {}
        logger.info(
            "Scanning storage container %s (prefix=%s) for transcription items",
            container_name,
            prefix,
        )

        for blob in container_client.list_blobs(name_starts_with=prefix):
            blob_name = blob.name
            lower_name = blob_name.lower()
            rel_name = blob_name[len(prefix) :] if blob_name.startswith(prefix) else blob_name

            if any(lower_name.endswith(ext) for ext in metadata_extensions):
                try:
                    blob_data = container_client.download_blob(blob_name).content_as_text(
                        encoding="utf-8"
                    )
                    payload = json.loads(blob_data)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(
                        "Skipping metadata blob %s due to error: %s",
                        blob_name,
                        exc,
                    )
                    continue

                for record in self._ensure_iterable(payload):
                    if not isinstance(record, dict):
                        continue
                    audio_path = record.get("audiopath")
                    if not audio_path:
                        continue
                    key = audio_path.replace("\\", "/")
                    discovered[key] = {
                        **record,
                        "audiopath": key,
                        "source_metadata": blob_name,
                    }

            elif any(lower_name.endswith(ext) for ext in audio_extensions):
                # Use the full blob_name (with directory) as the key
                key = blob_name.replace("\\", "/")
                discovered.setdefault(
                    key,
                    {
                        "audiopath": key,
                        "source_metadata": None,
                    },
                )

        records = list(discovered.values())
        logger.info("Discovered %d audio items in container %s", len(records), container_name)
        return records

    def submit_transcription_request(self, audio_url: str) -> Optional[Dict[str, Any]]:
        headers = {
            "Authorization": f"Bearer {self.voicegain_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        payload = {
            "modelName": "VoiceGain-Omega:2",
            "audio": {"source": {"fromUrl": {"url": audio_url}}},  # type: ignore[dict-item]
            "settings": {
                "asr": {
                    "diarization": {
                        "maxSpeakers": 3,
                        "minSpeakers": 2,
                    }
                },
                "formatters": [
                    {"type": "digits"},
                    {"parameters": {"enabled": "true"}, "type": "basic"},
                    {"parameters": {"CC": True, "EMAIL": "true"}, "type": "enhanced"},
                    {"parameters": {"mask": "partial"}, "type": "profanity"},
                    {"parameters": {"lang": "en-US"}, "type": "spelling"},
                    {
                        "parameters": {
                            "ADDRESS": "full",
                            "CARDINAL": "full",
                            "CC": "full",
                            "DATE": "full",
                            "EMAIL": "full",
                            "EVENT": "full",
                            "FAC": "full",
                            "GPE": "full",
                            "LANGUAGE": "full",
                            "LAW": "full",
                            "NORP": "full",
                            "MONEY": "full",
                            "ORDINAL": "full",
                            "ORG": "full",
                            "PERCENT": "full",
                            "PERSON": "full",
                            "PHONE": "full",
                            "PRODUCT": "full",
                            "QUANTITY": "full",
                            "SSN": "full",
                            "TIME": "full",
                            "WORK_OF_ART": "full",
                            "ZIP": "full",
                        },
                        "type": "redact",
                    },
                    {
                        "parameters": {
                            "mask": "full",
                            "options": "IA",
                            "pattern": "[1-9][0-9]{3}[ ]?[a-zA-Z]{2}",
                        },
                        "type": "regex",
                    },
                    {
                        "parameters": {
                            "mask": "full",
                            "options": "IA",
                            "pattern": "\\d+\\.",
                        },
                        "type": "regex",
                    },
                ],
                "preemptible": False,
            },
            "sessions": [
                {
                    "asyncMode": "OFF-LINE",
                    "poll": {"persist": 600000},
                    "content": {
                        "incremental": ["progress"],
                        "full": ["transcript", "words"],
                    },
                }
            ],
        }

        response = requests.post(
            "https://api.voicegain.ai/v1/asr/transcribe/async",
            headers=headers,
            json=payload,
            timeout=30,
        )

        if response.status_code == 429:
            logger.warning("Rate limited by VoiceGain while submitting %s", audio_url)
            return None

        response.raise_for_status()
        return response.json()

    def poll_transcription_status(
        self,
        session_url: str,
        max_iterations: int = 60,
        delay_seconds: int = 20,
    ) -> Tuple[str, str]:
        headers = {"Authorization": f"Bearer {self.voicegain_token}"}

        results = ""
        status = ""
        iteration_count = 0

        while results != "DONE" and iteration_count < max_iterations:
            time.sleep(delay_seconds)

            response = requests.get(session_url, headers=headers, timeout=30)
            response.raise_for_status()

            data = response.json()
            phase = data.get("progress", {}).get("phase", "")
            results = phase

            if results == "ERROR":
                results = "DONE"
                status = "fail"
                break

            iteration_count += 1
            logger.info(
                "Polling session %s iteration %d/%d phase=%s",
                session_url,
                iteration_count,
                max_iterations,
                phase,
            )

        if iteration_count >= max_iterations and results != "DONE":
            status = "timeout"
            results = "DONE"
            logger.error("Polling timeout reached for session %s", session_url)

        return results, status

    def get_transcript(self, session_url: str) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.voicegain_token}"}
        transcript_url = f"{session_url}/transcript"
        response = requests.get(transcript_url, headers=headers, timeout=30)
        response.raise_for_status()
        transcript_data = response.json()
        
        # Handle case where transcript is returned as a list (array of sessions)
        if isinstance(transcript_data, list):
            logger.debug(f"Transcript data is a list with {len(transcript_data)} items")
            if len(transcript_data) > 0:
                # Usually the first item contains the transcript
                transcript_data = transcript_data[0]
                logger.debug(f"Using first item, type: {type(transcript_data)}")
            else:
                logger.warning("Transcript data is an empty list")
                return {}
        
        # Log transcript data structure for debugging
        if isinstance(transcript_data, dict):
            logger.debug(f"Transcript data keys: {list(transcript_data.keys())}")
            if "utterances" in transcript_data:
                logger.debug(f"Utterances count: {len(transcript_data.get('utterances', []))}")
            if "words" in transcript_data:
                logger.debug(f"Words count: {len(transcript_data.get('words', []))}")
        else:
            logger.warning(f"Unexpected transcript data type: {type(transcript_data)}")
        
        return transcript_data if isinstance(transcript_data, dict) else {}

    def format_transcript(self, transcript_data: Dict[str, Any]) -> str:
        if self.azure_function_url:
            response = requests.post(
                self.azure_function_url,
                json=transcript_data,
                timeout=30,
            )
            if response.status_code == 200:
                return response.text
            logger.warning(
                "Formatter function returned %s. Falling back to local formatter.",
                response.status_code,
            )

        return self._format_transcript_locally(transcript_data)

    def _format_transcript_locally(self, transcript_data: Dict[str, Any]) -> str:
        formatted_lines: List[str] = []

        # Check for utterances first (preferred format)
        if "utterances" in transcript_data and transcript_data["utterances"]:
            for utterance in transcript_data["utterances"]:
                speaker = utterance.get("speakerId", "Unknown")
                text = utterance.get("transcript", "")
                start_time = utterance.get("start", 0) / 1000
                if text:  # Only add non-empty transcripts
                    formatted_lines.append(f"[{start_time:.2f}s] Speaker {speaker}: {text}")
        # Check for words (alternative format)
        elif "words" in transcript_data and transcript_data["words"]:
            current_speaker = None
            current_text: List[str] = []

            for word in transcript_data["words"]:
                speaker = word.get("speakerId")
                word_text = word.get("text", "").strip()
                if not word_text:  # Skip empty words
                    continue
                    
                if speaker != current_speaker:
                    if current_text:
                        formatted_lines.append(
                            f"Speaker {current_speaker}: {' '.join(current_text)}"
                        )
                    current_speaker = speaker
                    current_text = [word_text]
                else:
                    current_text.append(word_text)

            if current_text:
                formatted_lines.append(
                    f"Speaker {current_speaker}: {' '.join(current_text)}"
                )
        else:
            # No transcript data found
            logger.warning("No utterances or words found in transcript data")
            logger.debug(f"Transcript data structure: {list(transcript_data.keys())}")
            # Return a message indicating no transcript was found
            return "No transcript available - audio may be silent or transcription failed."

        if not formatted_lines:
            return "No transcript available - audio may be silent or transcription failed."
        
        return "\n".join(formatted_lines)

    def save_transcript_to_blob(self, transcript_text: str, audio_identifier: str) -> Optional[str]:
        if not self.blob_service_client:
            logger.warning(
                "Blob connection string not configured. Skipping upload for %s.",
                audio_identifier,
            )
            return None

        sanitized_name = ""
        if ".mp3" in audio_identifier:
            sanitized_name = audio_identifier.replace("/", "_").replace("\\", "_").replace(".mp3", ".txt")
        elif ".wav" in audio_identifier:
            sanitized_name = audio_identifier.replace("/", "_").replace("\\", "_").replace(".wav", ".txt")

        today = datetime.utcnow().strftime("%Y-%m-%d")
        full_blob_path = f"autoqa/transcriptFiles/{today}/{sanitized_name}"

        container_client = self.blob_service_client.get_container_client(
            self.blob_container_name
        )
        blob_client = container_client.get_blob_client(full_blob_path)
        blob_client.upload_blob(transcript_text, overwrite=True)
        logger.info("Transcript saved to blob path %s", full_blob_path)
        return full_blob_path

    def process_audio_file(
        self,
        item: Dict[str, Any],
        sas_token: Optional[str] = None,
        base_audio_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        audio_path = item.get("audiopath")
        audio_url = item.get("audio_url")
        chosen_base_url = base_audio_url or item.get("base_audio_url") or self.audio_base_url

        response_payload: Dict[str, Any] = {
            "audio_path": audio_path,
            "audio_url": audio_url,
            "success": False,
            "status": "",
            "transcript_blob_path": None,
            "error": None,
        }

        try:
            if not audio_url:
                if not audio_path:
                    raise ValueError("Missing 'audiopath' or 'audio_url' in work item.")
                if not chosen_base_url:
                    raise ValueError("Audio base URL not provided for constructing audio_url.")
                audio_url = f"{chosen_base_url.rstrip('/')}/{audio_path.lstrip('/')}"
            if sas_token:
                separator = "&" if "?" in audio_url else "?"
                audio_url = f"{audio_url}{separator}{sas_token}"
            response_payload["audio_url"] = audio_url

            transcription_response = self.submit_transcription_request(audio_url)
            if transcription_response is None:
                response_payload["status"] = "rate_limited"
                return response_payload

            self.session_url = transcription_response["sessions"][0]["sessionUrl"]
            results_phase, status = self.poll_transcription_status(self.session_url)
            response_payload["status"] = status or results_phase

            if status in {"fail", "timeout"}:
                logger.error(
                    "Transcription %s for %s",
                    status,
                    audio_path or audio_url,
                )
                return response_payload

            transcript_data = self.get_transcript(self.session_url)
            formatted_transcript = self.format_transcript(transcript_data)
            blob_path = self.save_transcript_to_blob(
                formatted_transcript,
                audio_path or audio_url,
            )
            response_payload["transcript_blob_path"] = blob_path
            response_payload["success"] = True
            return response_payload

        except Exception as exc:  # pylint: disable=broad-except
            response_payload["error"] = str(exc)
            logger.exception(
                "Error processing audio item %s: %s",
                audio_path or audio_url or "<unknown>",
                exc,
            )
            return response_payload


# Azure Durable Functions setup (new Python programming model)
app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)



def _build_workflow(settings: Dict[str, Any]) -> TranscriptionWorkflow:
    required_token = settings.get("voicegain_bearer_token")
    if not required_token:
        raise ValueError("voicegain_bearer_token is required in workflow_settings.")

    return TranscriptionWorkflow(
        voicegain_bearer_token=required_token,
        blob_connection_string=settings.get("blob_connection_string"),
        azure_function_url=settings.get("azure_function_url"),
        audio_base_url=settings.get("audio_base_url"),
        blob_container_name=settings.get("blob_container_name", "autoqa"),
    )


@app.orchestration_trigger(context_name="context")
def transcription_orchestrator(context: df.DurableOrchestrationContext):
    """Durable orchestrator that fans out transcription activities."""
    orchestration_input = context.get_input() or {}
    source_storage = orchestration_input.get("source_storage")
    target_directory = orchestration_input.get("target_directory")
    metadata_extensions = orchestration_input.get("metadata_extensions")
    audio_extensions = orchestration_input.get("audio_extensions")
    workflow_settings = orchestration_input.get("workflow_settings", {})
    sas_token = orchestration_input.get("sas_token")

    listing_payload = {
        "source_storage": source_storage,
        "target_directory": target_directory,
        "metadata_extensions": metadata_extensions,
        "audio_extensions": audio_extensions,
    }

    audio_items = yield context.call_activity(
        "ListTranscriptionItems",
        listing_payload,
    )

    task_inputs = [
        {
            "item": item,
            "workflow_settings": workflow_settings,
            "sas_token": sas_token,
        }
        for item in audio_items
    ]

    activity_tasks = [
        context.call_activity("ProcessTranscriptionItem", payload)
        for payload in task_inputs
    ]

    activity_results = yield context.task_all(activity_tasks)

    succeeded = [result for result in activity_results if result.get("success")]
    failed = [result for result in activity_results if not result.get("success")]

    return {
        "total": len(activity_results),
        "succeeded": len(succeeded),
        "failed": len(failed),
        "failures": failed,
    }


@app.route(route="transcription/start", methods=["POST"])
@app.durable_client_input(client_name="client")
async def http_start(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError as exc:
        return func.HttpResponse(
            json.dumps({"error": f"Invalid JSON payload: {exc}"}),
            status_code=400,
            mimetype="application/json",
        )

    instance_id = await client.start_new(
        orchestration_function_name="transcription_orchestrator",
        client_input=body,
    )

    logger.info("Started orchestration with ID = %s", instance_id)

    return client.create_check_status_response(req, instance_id)


@app.activity_trigger(input_name="payload")
def ListTranscriptionItems(payload: Dict[str, Any]) -> List[Dict[str, Any]]:  # noqa: N802
    source_storage = payload.get("source_storage")
    target_directory = payload.get("target_directory")
    metadata_extensions = payload.get("metadata_extensions")
    audio_extensions = payload.get("audio_extensions")

    workflow = TranscriptionWorkflow(voicegain_bearer_token="placeholder-token")
    # Using a temporary workflow with dummy token because listing does not require API access.

    if source_storage:
        connection_string = source_storage.get("connection_string")
        container_name = source_storage.get("container_name")
        directory = source_storage.get("directory", "")
        if not all([connection_string, container_name]):
            raise ValueError(
                "source_storage must include 'connection_string' and 'container_name'."
            )
        return workflow.list_audio_items_from_storage(
            connection_string=connection_string,
            container_name=container_name,
            directory=directory,
            metadata_extensions=metadata_extensions,
            audio_extensions=audio_extensions,
        )

    if target_directory:
        return workflow.list_audio_items_from_directory(
            target_directory=target_directory,
            metadata_extensions=metadata_extensions,
            audio_extensions=audio_extensions,
        )

    raise ValueError(
        "Either 'source_storage' or 'target_directory' must be provided for listing activity."
    )


@app.activity_trigger(input_name="payload")
def ProcessTranscriptionItem(payload: Dict[str, Any]) -> Dict[str, Any]:  # noqa: N802
    workflow_settings = payload.get("workflow_settings") or {}
    workflow = _build_workflow(workflow_settings)
    item = payload.get("item") or {}
    sas_token = payload.get("sas_token")
    base_audio_url = workflow_settings.get("audio_base_url")
    return workflow.process_audio_file(
        item=item,
        sas_token=sas_token,
        base_audio_url=base_audio_url,
    )

