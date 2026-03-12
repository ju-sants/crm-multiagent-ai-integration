"""
Dev Chat Server - Flask Blueprint for development/testing chat interface.
Simulates the Callbell environment, allowing manual and automated testing
without touching production WhatsApp channels.
"""

import base64
import io
import json
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, send_from_directory, Response
import os

from app.services.redis_service import get_redis
from app.services.state_manager_service import StateManagerService
from app.core.logger import get_logger

logger = get_logger(__name__)
redis_client = get_redis()
state_manager = StateManagerService()

dev_chat_bp = Blueprint('dev_chat', __name__,
                        static_folder=os.path.join(os.path.dirname(__file__), 'static'))

# Constants
DEV_TEAM_UUID = "d468731afdba45c3a3a65895e4b08a5a"
DEV_PHONE = "+5500000000000"


def _get_contact_id(session_id: str) -> str:
    """Generate a deterministic dev contact_id from session_id."""
    return f"dev-{session_id}"


def _build_callbell_payload(contact_id: str, text: str, contact_name: str = "Dev Tester") -> dict:
    """Build a fake Callbell webhook payload."""
    return {
        "uuid": str(uuid.uuid4()),
        "status": "received",
        "text": text,
        "attachments": [],
        "messageContext": {},
        "contact": {
            "uuid": contact_id,
            "name": contact_name,
            "phoneNumber": DEV_PHONE,
            "team": {
                "uuid": DEV_TEAM_UUID
            }
        }
    }


# --- Routes ---

@dev_chat_bp.route('/')
def chat_ui():
    """Serve the chat HTML interface."""
    return send_from_directory(dev_chat_bp.static_folder, 'index.html')


@dev_chat_bp.route('/send', methods=['POST'])
def send_message():
    """
    Send a message as if it came from WhatsApp.
    Body: { "session_id": "...", "message": "...", "contact_name": "Dev Tester" }
    """
    from main import process_incoming_message

    data = request.get_json()
    session_id = data.get('session_id', 'default')
    message = data.get('message', '')
    contact_name = data.get('contact_name', 'Dev Tester')

    if not message:
        return jsonify({"error": "message is required"}), 400

    contact_id = _get_contact_id(session_id)

    # Store user message in dev history
    now = datetime.now(timezone.utc)
    user_msg = json.dumps({
        "uuid": str(uuid.uuid4()),
        "status": "received",
        "text": message,
        "createdAt": now.strftime('%Y-%m-%dT%H:%M:%SZ')
    })
    redis_client.rpush(f"dev:history:{contact_id}", user_msg)

    # Build and process fake Callbell payload
    payload = _build_callbell_payload(contact_id, message, contact_name)
    process_incoming_message(payload)

    return jsonify({"status": "sent", "contact_id": contact_id})


@dev_chat_bp.route('/audio/send', methods=['POST'])
def send_audio():
    """
    Send an audio message recorded in the dev chat.
    Transcribes the audio using OpenAI Whisper, stores the audio data in history,
    and processes the transcribed text as a regular message.

    Accepts multipart form:
      - audio: audio file (webm/ogg/mp3)
      - session_id: session identifier
      - contact_name: optional contact name
    """
    from main import process_incoming_message
    from openai import OpenAI
    from app.config.settings import settings as app_settings

    if 'audio' not in request.files:
        return jsonify({"error": "audio file required"}), 400

    audio_file = request.files['audio']
    session_id = request.form.get('session_id', 'default')
    contact_name = request.form.get('contact_name', 'Dev Tester')
    contact_id = _get_contact_id(session_id)

    # Read audio bytes
    audio_bytes = audio_file.read()
    if not audio_bytes:
        return jsonify({"error": "empty audio"}), 400

    # Store audio as base64 data URL for playback
    mime = audio_file.content_type or 'audio/webm'
    audio_b64 = base64.b64encode(audio_bytes).decode('ascii')
    audio_data_url = f"data:{mime};base64,{audio_b64}"

    # Transcribe using OpenAI Whisper
    transcription = ""
    try:
        client = OpenAI(api_key=app_settings.OPENAI_API_KEY)
        audio_io = io.BytesIO(audio_bytes)
        audio_io.name = "audio.webm"
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_io,
            language="pt",
        )
        transcription = result.text.strip()
    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        transcription = "(transcrição falhou)"

    # Store audio message in dev history with audio data
    now = datetime.now(timezone.utc)
    display_text = f"(Áudio): {transcription}" if transcription else "(Áudio sem transcrição)"
    user_msg = json.dumps({
        "uuid": str(uuid.uuid4()),
        "status": "received",
        "text": display_text,
        "audio_url": audio_data_url,
        "createdAt": now.strftime('%Y-%m-%dT%H:%M:%SZ')
    })
    redis_client.rpush(f"dev:history:{contact_id}", user_msg)

    # Process the transcription through the normal pipeline
    if transcription and transcription != "(transcrição falhou)":
        message_text = f"(Áudio transcrito): {transcription}"
        payload = _build_callbell_payload(contact_id, message_text, contact_name)
        process_incoming_message(payload)

    return jsonify({
        "status": "sent",
        "contact_id": contact_id,
        "transcription": transcription,
        "audio_url": audio_data_url,
    })


@dev_chat_bp.route('/audio/tts', methods=['POST'])
def generate_tts():
    """
    Generate TTS audio from text using ElevenLabs (same as production).
    Body: { "text": "..." }
    Returns: { "audio_url": "data:audio/mp3;base64,..." }
    """
    from app.services.eleven_labs_service import get_audio_bytes

    data = request.get_json()
    text = data.get('text', '').strip()
    if not text:
        return jsonify({"error": "text is required"}), 400

    try:
        audio_bytes = get_audio_bytes([text])
        audio_b64 = base64.b64encode(audio_bytes).decode('ascii')
        return jsonify({"audio_url": f"data:audio/mp3;base64,{audio_b64}"})
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        return jsonify({"error": str(e)}), 500


@dev_chat_bp.route('/messages/<session_id>', methods=['GET'])
def get_messages(session_id):
    """
    Poll for new bot responses. Returns and clears the outbox.
    """
    contact_id = _get_contact_id(session_id)
    messages = []

    while True:
        msg = redis_client.lpop(f"dev:outbox:{contact_id}")
        if msg is None:
            break
        messages.append(json.loads(msg))

    return jsonify({"messages": messages})


@dev_chat_bp.route('/history/<session_id>', methods=['GET'])
def get_history(session_id):
    """
    Get full conversation history for a session.
    """
    contact_id = _get_contact_id(session_id)
    raw = redis_client.lrange(f"dev:history:{contact_id}", 0, -1)
    messages = [json.loads(m) for m in raw]
    return jsonify({"messages": messages})


@dev_chat_bp.route('/state/<session_id>', methods=['GET'])
def get_state(session_id):
    """
    Get the current conversation state for inspection.
    """
    contact_id = _get_contact_id(session_id)
    state, is_new = state_manager.get_state(contact_id)
    return jsonify({
        "is_new": is_new,
        "state": state.model_dump()
    })


@dev_chat_bp.route('/state/<session_id>', methods=['PUT'])
def update_state(session_id):
    """
    Manually override parts of the conversation state.
    Body: { "field": "value", ... } — merged into current state.
    """
    from app.models.data_models import ConversationState

    contact_id = _get_contact_id(session_id)
    updates = request.get_json()

    with redis_client.lock(f"lock:state:{contact_id}", timeout=30):
        state, _ = state_manager.get_state(contact_id)
        merged = {**state.model_dump(), **updates}
        state = ConversationState(**merged)
        state_manager.save_state(contact_id, state)

    return jsonify({"status": "updated", "state": state.model_dump()})


@dev_chat_bp.route('/reset/<session_id>', methods=['POST'])
def reset_session(session_id):
    """
    Reset all data for a dev session (state, history, outbox, all redis keys).
    """
    contact_id = _get_contact_id(session_id)

    # Collect all known key patterns for this contact
    key_patterns = [
        f"state:{contact_id}",
        f"dev:history:{contact_id}",
        f"dev:outbox:{contact_id}",
        f"contact_info:{contact_id}",
        f"contacts_messages:waiting:{contact_id}",
        f"pending_task:{contact_id}",
        f"processing:{contact_id}",
        f"history:last_timestamp:{contact_id}",
        f"history:last_timestamp:to_follow_up:{contact_id}",
        f"history_raw:{contact_id}",
        f"shorterm_history:{contact_id}",
        f"longterm_history:{contact_id}",
        f"follow_up_level:{contact_id}",
        f"{contact_id}:attachments",
        f"{contact_id}:sended_catalogs",
        f"{contact_id}:last_processed_messages",
        f"{contact_id}:last_system_operation_output",
        f"{contact_id}:getting_data_from_user",
        f"{contact_id}:customer_profile",
        f"doing_strategy:{contact_id}",
        f"refining_strategy:{contact_id}",
        f"lock_enrichment_pipeline:{contact_id}",
        f"dev:discriminator:{contact_id}",
    ]

    pipe = redis_client.pipeline()
    for key in key_patterns:
        pipe.delete(key)
    pipe.srem("contacts", contact_id)
    pipe.execute()

    return jsonify({"status": "reset", "contact_id": contact_id})


@dev_chat_bp.route('/discriminator/analyze', methods=['POST'])
def discriminator_analyze():
    """
    Run the discriminator agent on a specific bot response.
    Body: {
        "session_id": "...",
        "bot_response": [...messages...],
        "conversation_state": {...} (optional, fetched if missing)
    }
    """
    from dev_chat.discriminator import analyze_response

    data = request.get_json()
    session_id = data.get('session_id', 'default')
    bot_response = data.get('bot_response', [])
    contact_id = _get_contact_id(session_id)

    # Get conversation state
    conv_state = data.get('conversation_state')
    if not conv_state:
        state, _ = state_manager.get_state(contact_id)
        conv_state = state.model_dump()

    # Get history
    raw = redis_client.lrange(f"dev:history:{contact_id}", 0, -1)
    history = [json.loads(m) for m in raw]

    analysis = analyze_response(
        bot_response=bot_response,
        conversation_state=conv_state,
        history=history
    )

    # Store result
    redis_client.rpush(
        f"dev:discriminator:{contact_id}",
        json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "analysis": analysis})
    )

    return jsonify({"analysis": analysis})


@dev_chat_bp.route('/discriminator/results/<session_id>', methods=['GET'])
def discriminator_results(session_id):
    """Get all discriminator analysis results for a session."""
    contact_id = _get_contact_id(session_id)
    raw = redis_client.lrange(f"dev:discriminator:{contact_id}", 0, -1)
    results = [json.loads(r) for r in raw]
    return jsonify({"results": results})


@dev_chat_bp.route('/sessions', methods=['GET'])
def list_sessions():
    """List all active dev sessions."""
    all_contacts = redis_client.smembers("contacts")
    dev_sessions = [c.replace("dev-", "") for c in all_contacts if c.startswith("dev-")]
    return jsonify({"sessions": dev_sessions})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ANALYTICS ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dev_chat_bp.route('/analytics', methods=['GET'])
def analytics_summary():
    """Get aggregate analytics summary."""
    from dev_chat.analytics import get_analytics_summary
    return jsonify(get_analytics_summary())


@dev_chat_bp.route('/analytics/<session_id>', methods=['GET'])
def analytics_session(session_id):
    """Get detailed analytics for a specific session."""
    from dev_chat.analytics import get_session_analytics
    contact_id = _get_contact_id(session_id)
    return jsonify({"metrics": get_session_analytics(contact_id)})


@dev_chat_bp.route('/analytics', methods=['DELETE'])
def analytics_clear_all():
    """Clear all analytics data."""
    from dev_chat.analytics import clear_all_analytics
    clear_all_analytics()
    return jsonify({"status": "cleared"})


@dev_chat_bp.route('/analytics/<session_id>', methods=['DELETE'])
def analytics_clear_session(session_id):
    """Clear analytics for a specific session."""
    from dev_chat.analytics import clear_session_analytics
    contact_id = _get_contact_id(session_id)
    clear_session_analytics(contact_id)
    return jsonify({"status": "cleared", "session_id": session_id})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BENCHMARKS ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dev_chat_bp.route('/benchmarks/models', methods=['GET'])
def benchmarks_models():
    """List available models for benchmarking."""
    from dev_chat.benchmarks import AVAILABLE_MODELS
    return jsonify({"models": AVAILABLE_MODELS})


@dev_chat_bp.route('/benchmarks/agents', methods=['GET'])
def benchmarks_agents():
    """List agents available for benchmarking."""
    from dev_chat.benchmarks import BENCHMARKABLE_AGENTS
    return jsonify({"agents": BENCHMARKABLE_AGENTS})


@dev_chat_bp.route('/benchmarks/run', methods=['POST'])
def benchmarks_run():
    """
    Run a benchmark in background, return run_id immediately.
    Connect to /benchmarks/stream/<run_id> for live progress via SSE.
    """
    from dev_chat.benchmarks import run_benchmark

    data = request.get_json()
    agent = data.get('agent')
    session_id = data.get('session_id')
    models = data.get('models', [])
    temperature = data.get('temperature')
    top_p = data.get('top_p')
    max_tokens = data.get('max_tokens')
    model_params = data.get('model_params')
    run_disc = data.get('run_discriminator', True)
    iterations = data.get('iterations', 1)
    synthetic = data.get('synthetic_scenario')
    capture_prompt = data.get('capture_prompt', False)
    max_workers = data.get('max_workers')

    if not agent or not models:
        return jsonify({"error": "Required: agent, models"}), 400
    if not session_id and not synthetic:
        return jsonify({"error": "Required: session_id or synthetic_scenario"}), 400

    contact_id = _get_contact_id(session_id) if session_id else None

    # Generate run_id upfront so client can subscribe to SSE
    import uuid as _uuid
    run_id = str(_uuid.uuid4())[:8]

    def _run():
        run_benchmark(
            agent, contact_id or "", models,
            temperature=temperature, top_p=top_p, max_tokens=max_tokens,
            model_params=model_params,
            run_discriminator=run_disc,
            iterations=iterations, synthetic_scenario=synthetic,
            capture_prompt=capture_prompt, run_id=run_id,
            max_workers=max_workers,
        )

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"run_id": run_id, "status": "started"})


@dev_chat_bp.route('/benchmarks/results', methods=['GET'])
def benchmarks_results():
    """Get stored benchmark results."""
    from dev_chat.benchmarks import get_benchmark_results
    limit = request.args.get('limit', 50, type=int)
    return jsonify({"results": get_benchmark_results(limit)})


@dev_chat_bp.route('/benchmarks/stream/<run_id>')
def benchmarks_stream(run_id):
    """SSE endpoint — stream real-time benchmark progress events."""
    def _event_stream():
        pubsub = redis_client.pubsub()
        channel = f"bench:progress:{run_id}"
        pubsub.subscribe(channel)
        try:
            # Send initial keepalive
            yield f"data: {json.dumps({'type': 'connected', 'run_id': run_id})}\n\n"
            for message in pubsub.listen():
                if message['type'] == 'message':
                    yield f"data: {message['data']}\n\n"
                    try:
                        payload = json.loads(message['data'])
                        if payload.get('type') == 'finished':
                            break
                    except (json.JSONDecodeError, TypeError):
                        pass
        finally:
            pubsub.unsubscribe(channel)
            pubsub.close()

    return Response(
        _event_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )


@dev_chat_bp.route('/benchmarks/matrix', methods=['POST'])
def benchmarks_matrix():
    """
    Run a matrix benchmark in background, return run_id immediately.
    Connect to /benchmarks/stream/<run_id> for live progress via SSE.
    """
    from dev_chat.benchmarks import run_matrix_benchmark

    data = request.get_json()
    agents = data.get('agents', [])
    models = data.get('models', [])
    scenarios = data.get('scenarios', [])
    iterations = data.get('iterations', 1)
    scenario_order = data.get('scenario_order', 'sequential')
    temperature = data.get('temperature')
    top_p = data.get('top_p')
    max_tokens = data.get('max_tokens')
    model_params = data.get('model_params')
    run_disc = data.get('run_discriminator', True)
    capture_prompt = data.get('capture_prompt', False)
    max_workers = data.get('max_workers')

    if not agents or not models or not scenarios:
        return jsonify({"error": "Required: agents, models, scenarios"}), 400

    import uuid as _uuid
    run_id = str(_uuid.uuid4())[:8]

    def _run():
        run_matrix_benchmark(
            agents=agents,
            models=models,
            scenarios=scenarios,
            iterations=iterations,
            scenario_order=scenario_order,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            model_params=model_params,
            run_discriminator=run_disc,
            capture_prompt=capture_prompt,
            run_id=run_id,
            max_workers=max_workers,
        )

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"run_id": run_id, "status": "started"})


@dev_chat_bp.route('/benchmarks/discover', methods=['GET'])
def benchmarks_discover():
    """Discover all available models, agents, and scenarios for matrix configuration."""
    from dev_chat.benchmarks import discover_models, discover_agents
    from dev_chat.synthetic_states import list_synthetic_scenarios

    return jsonify({
        "models": discover_models(),
        "agents": discover_agents(),
        "scenarios": list_synthetic_scenarios(),
    })


@dev_chat_bp.route('/benchmarks/checkpoints', methods=['GET'])
def benchmarks_checkpoints():
    """List all active benchmark checkpoints that can be resumed."""
    from dev_chat.benchmarks import list_checkpoints
    return jsonify({"checkpoints": list_checkpoints()})


@dev_chat_bp.route('/benchmarks/resume/<run_id>', methods=['POST'])
def benchmarks_resume(run_id):
    """Resume an interrupted benchmark from its checkpoint.

    Runs in background thread and returns a new run_id for SSE streaming.
    """
    from dev_chat.benchmarks import resume_benchmark, get_checkpoint

    checkpoint = get_checkpoint(run_id)
    if not checkpoint:
        return jsonify({"error": f"No checkpoint found for '{run_id}'"}), 404

    import uuid as _uuid
    new_run_id = str(_uuid.uuid4())[:8]

    def _run():
        resume_benchmark(run_id, new_run_id=new_run_id)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({
        "run_id": new_run_id,
        "original_run_id": run_id,
        "status": "resuming",
        "remaining": len(checkpoint.get("remaining_items", [])),
        "completed": len(checkpoint.get("completed_results", [])),
    })


@dev_chat_bp.route('/benchmarks/checkpoints/<run_id>', methods=['DELETE'])
def benchmarks_delete_checkpoint(run_id):
    """Delete a specific checkpoint."""
    from dev_chat.benchmarks import get_checkpoint
    if not get_checkpoint(run_id):
        return jsonify({"error": "Checkpoint not found"}), 404
    from dev_chat.benchmarks import _delete_checkpoint
    _delete_checkpoint(run_id)
    return jsonify({"status": "deleted", "run_id": run_id})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BENCHMARK CONFIG EXPORT / IMPORT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dev_chat_bp.route('/benchmarks/config/export', methods=['POST'])
def benchmarks_config_export():
    """Export a benchmark configuration as downloadable JSON.

    Body: the full config object from the frontend form.
    Returns a cleaned JSON ready for re-import.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Empty config"}), 400

    allowed_keys = {
        'mode', 'agent', 'agents', 'models', 'scenarios', 'iterations',
        'scenario_order', 'model_params', 'run_discriminator', 'capture_prompt',
        'synthetic_scenario',
    }
    config = {k: v for k, v in data.items() if k in allowed_keys}
    config["_exported_at"] = datetime.now(timezone.utc).isoformat()

    return jsonify(config)


@dev_chat_bp.route('/benchmarks/config/import', methods=['POST'])
def benchmarks_config_import():
    """Validate and return an imported benchmark config.

    Body: a previously exported config JSON.
    Returns the validated config for the frontend to load.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Empty config"}), 400

    # Validate model_params structure if present
    model_params = data.get('model_params')
    if model_params and isinstance(model_params, dict):
        for model_key, params in model_params.items():
            if not isinstance(params, dict):
                return jsonify({"error": f"model_params['{model_key}'] must be a dict"}), 400
            for param_name, param_val in params.items():
                if param_name not in ('temperature', 'top_p', 'max_tokens'):
                    return jsonify({"error": f"Unknown param '{param_name}' for model '{model_key}'"}), 400
                if isinstance(param_val, list):
                    if not all(isinstance(v, (int, float)) for v in param_val):
                        return jsonify({"error": f"Range values for '{param_name}' must be numbers"}), 400

    return jsonify({"status": "valid", "config": data})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BENCHMARK REPORT ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dev_chat_bp.route('/benchmarks/report', methods=['POST'])
def benchmarks_report():
    """Generate a deep analysis report for a specific benchmark run.

    Body: {"run_id": "...", "model": "optional/model-key"}
    If run_id is omitted, analyzes the most recent benchmark result.
    """
    from dev_chat.report_generator import generate_report
    from dev_chat.benchmarks import get_benchmark_results

    data = request.get_json() or {}
    target_run_id = data.get('run_id')
    model = data.get('model')

    results = get_benchmark_results(50)
    if not results:
        return jsonify({"error": "Nenhum benchmark disponível."}), 404

    if target_run_id:
        target = next((r for r in results if r.get("run_id") == target_run_id), None)
        if not target:
            return jsonify({"error": f"Benchmark '{target_run_id}' não encontrado."}), 404
    else:
        target = results[-1]

    report = generate_report(target, model=model)
    return jsonify(report)


@dev_chat_bp.route('/benchmarks/report/cross', methods=['POST'])
def benchmarks_cross_report():
    """Generate a cross-analysis report comparing multiple benchmark runs.

    Body: {"run_ids": ["id1", "id2", ...], "model": "optional/model-key"}
    If run_ids is omitted or empty, analyzes ALL available benchmark results.
    """
    from dev_chat.report_generator import generate_cross_report
    from dev_chat.benchmarks import get_benchmark_results

    data = request.get_json() or {}
    run_ids = data.get('run_ids', [])
    model = data.get('model')

    results = get_benchmark_results(100)
    if not results:
        return jsonify({"error": "Nenhum benchmark disponível."}), 404

    if run_ids:
        selected = [r for r in results if r.get("run_id") in run_ids]
        if not selected:
            return jsonify({"error": "Nenhum dos run_ids fornecidos foi encontrado."}), 404
    else:
        selected = results

    report = generate_cross_report(selected, model=model)
    return jsonify(report)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MODEL CONFIGURATION ENDPOINTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dev_chat_bp.route('/models/mapping', methods=['GET'])
def models_mapping():
    """Get default agent -> model mapping and active overrides."""
    from dev_chat.benchmarks import get_default_model_mapping, get_model_overrides
    return jsonify({
        "defaults": get_default_model_mapping(),
        "overrides": get_model_overrides(),
    })


@dev_chat_bp.route('/models/override', methods=['PUT'])
def models_set_override():
    """
    Set a model override for an agent.
    Body: { "agent": "CommunicationAgent", "model": "o3-mini-2025-01-31", "session_id": null }
    session_id=null means global override.
    """
    from dev_chat.benchmarks import set_model_override

    data = request.get_json()
    agent = data.get('agent')
    model = data.get('model')
    session_id = data.get('session_id')

    if not agent or not model:
        return jsonify({"error": "Required: agent, model"}), 400

    contact_id = _get_contact_id(session_id) if session_id else None
    try:
        set_model_override(agent, model, contact_id)
        return jsonify({"status": "set", "agent": agent, "model": model,
                        "scope": session_id or "global"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@dev_chat_bp.route('/models/override', methods=['DELETE'])
def models_remove_override():
    """
    Remove a model override.
    Body: { "agent": "CommunicationAgent", "session_id": null }
    """
    from dev_chat.benchmarks import remove_model_override

    data = request.get_json()
    agent = data.get('agent')
    session_id = data.get('session_id')

    if not agent:
        return jsonify({"error": "Required: agent"}), 400

    contact_id = _get_contact_id(session_id) if session_id else None
    remove_model_override(agent, contact_id)
    return jsonify({"status": "removed", "agent": agent})


@dev_chat_bp.route('/models/overrides', methods=['GET'])
def models_list_overrides():
    """List all active model overrides."""
    from dev_chat.benchmarks import get_model_overrides
    session_id = request.args.get('session_id')
    contact_id = _get_contact_id(session_id) if session_id else None
    return jsonify({
        "global": get_model_overrides(None),
        "session": get_model_overrides(contact_id) if contact_id else {},
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SCENARIOS ENDPOINT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dev_chat_bp.route('/synthetic/scenarios', methods=['GET'])
def synthetic_list():
    """List available synthetic test scenarios."""
    from dev_chat.synthetic_states import list_synthetic_scenarios
    return jsonify({"scenarios": list_synthetic_scenarios()})


@dev_chat_bp.route('/synthetic/inject', methods=['POST'])
def synthetic_inject():
    """
    Inject a synthetic state into Redis for testing.
    Body: { "scenario": "moto_mid_funnel", "contact_id": null }
    """
    from dev_chat.synthetic_states import inject_synthetic_state
    data = request.get_json()
    scenario = data.get('scenario')
    contact_id = data.get('contact_id')
    if not scenario:
        return jsonify({"error": "Required: scenario"}), 400
    try:
        cid = inject_synthetic_state(scenario, contact_id)
        return jsonify({"status": "injected", "contact_id": cid, "scenario": scenario})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@dev_chat_bp.route('/scenarios', methods=['GET'])
def list_scenarios():
    """List available test scenarios."""
    scenarios_dir = os.path.join(os.path.dirname(__file__), 'scenarios')
    scenarios = []
    if os.path.isdir(scenarios_dir):
        for fname in sorted(os.listdir(scenarios_dir)):
            if fname.endswith('.json'):
                filepath = os.path.join(scenarios_dir, fname)
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                scenarios.append({
                    "file": fname,
                    "name": data.get("name", fname),
                    "description": data.get("description", ""),
                    "messages_count": len(data.get("messages", [])),
                })
    return jsonify({"scenarios": scenarios})
