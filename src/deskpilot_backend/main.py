from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from deskpilot_backend.actions import ProcessLauncher, UnsupportedActionError, execute_action
from deskpilot_backend.assistant import handle_assistant_command
from deskpilot_backend.commands import route_command
from deskpilot_backend.models import (
    ActionExecutionRequest,
    ActionExecutionResponse,
    AssistantCommandRequest,
    AssistantCommandResponse,
    CommandRequest,
    CommandResponse,
    MicrophoneCommandRequest,
    SpeechRequest,
    SpeechResponse,
    TranscriptionResponse,
    VoiceCommandResponse,
)
from deskpilot_backend.microphone import (
    AudioRecorder,
    MicrophoneError,
    record_microphone_wav,
)
from deskpilot_backend.speech import SpeechEngineError, SpeechEngineFactory, speak_text
from deskpilot_backend.transcription import (
    EmptyAudioError,
    TranscriptionServiceError,
    UnsupportedAudioError,
    WhisperTranscriptionService,
)
from deskpilot_backend.voice import handle_voice_command

app = FastAPI(title="DeskPilot")
transcription_service = WhisperTranscriptionService()
STATIC_DIR = Path(__file__).resolve().parent / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def get_process_launcher() -> ProcessLauncher | None:
    return None


def get_speech_engine_factory() -> SpeechEngineFactory | None:
    return None


def get_transcription_service() -> WhisperTranscriptionService:
    return transcription_service


def get_audio_recorder() -> AudioRecorder:
    return record_microphone_wav


@app.get("/", include_in_schema=False)
def serve_interface() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/v1/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "deskpilot"}


@app.post(
    "/api/v1/commands",
    response_model=CommandResponse,
    response_model_exclude_none=True,
)
def create_command(command: CommandRequest) -> CommandResponse:
    return route_command(command.text)


@app.post("/api/v1/actions/execute", response_model=ActionExecutionResponse)
def execute_planned_action(
    action: ActionExecutionRequest,
) -> ActionExecutionResponse:
    try:
        return execute_action(action)
    except UnsupportedActionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post(
    "/api/v1/assistant/commands",
    response_model=AssistantCommandResponse,
    response_model_exclude_none=True,
)
def create_assistant_command(
    command: AssistantCommandRequest,
    process_launcher: ProcessLauncher | None = Depends(get_process_launcher),
    speech_engine_factory: SpeechEngineFactory | None = Depends(
        get_speech_engine_factory
    ),
) -> AssistantCommandResponse:
    try:
        return handle_assistant_command(
            command,
            launcher=process_launcher,
            speech_engine_factory=speech_engine_factory,
        )
    except UnsupportedActionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/v1/speech/speak", response_model=SpeechResponse)
def create_speech(
    speech: SpeechRequest,
    engine_factory: SpeechEngineFactory | None = Depends(get_speech_engine_factory),
) -> SpeechResponse:
    try:
        return speak_text(speech.text, engine_factory=engine_factory)
    except SpeechEngineError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/api/v1/transcriptions", response_model=TranscriptionResponse)
async def create_transcription(
    audio_file: Annotated[UploadFile, File()],
    service: WhisperTranscriptionService = Depends(get_transcription_service),
) -> TranscriptionResponse:
    audio_bytes = await audio_file.read()

    try:
        return service.transcribe(
            audio_bytes,
            content_type=audio_file.content_type,
            filename=audio_file.filename,
        )
    except EmptyAudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except UnsupportedAudioError as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    except TranscriptionServiceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post(
    "/api/v1/voice/commands",
    response_model=VoiceCommandResponse,
    response_model_exclude_none=True,
)
async def create_voice_command(
    audio_file: Annotated[UploadFile, File()],
    speak: Annotated[bool, Form()] = False,
    service: WhisperTranscriptionService = Depends(get_transcription_service),
    process_launcher: ProcessLauncher | None = Depends(get_process_launcher),
    speech_engine_factory: SpeechEngineFactory | None = Depends(
        get_speech_engine_factory
    ),
) -> VoiceCommandResponse:
    audio_bytes = await audio_file.read()

    try:
        return handle_voice_command(
            audio_bytes,
            content_type=audio_file.content_type,
            filename=audio_file.filename,
            speak=speak,
            transcription_service=service,
            launcher=process_launcher,
            speech_engine_factory=speech_engine_factory,
        )
    except EmptyAudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except UnsupportedAudioError as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    except TranscriptionServiceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except UnsupportedActionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post(
    "/api/v1/microphone/commands",
    response_model=VoiceCommandResponse,
    response_model_exclude_none=True,
)
def create_microphone_command(
    request: MicrophoneCommandRequest,
    recorder: AudioRecorder = Depends(get_audio_recorder),
    service: WhisperTranscriptionService = Depends(get_transcription_service),
    process_launcher: ProcessLauncher | None = Depends(get_process_launcher),
    speech_engine_factory: SpeechEngineFactory | None = Depends(
        get_speech_engine_factory
    ),
) -> VoiceCommandResponse:
    try:
        audio_bytes = recorder(request.duration_seconds)
        return handle_voice_command(
            audio_bytes,
            content_type="audio/wav",
            filename="microphone.wav",
            speak=request.speak,
            transcription_service=service,
            launcher=process_launcher,
            speech_engine_factory=speech_engine_factory,
        )
    except MicrophoneError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except EmptyAudioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except UnsupportedAudioError as error:
        raise HTTPException(status_code=415, detail=str(error)) from error
    except TranscriptionServiceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except UnsupportedActionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
