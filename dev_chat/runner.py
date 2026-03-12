"""
Dev Chat Test Runner — Programmatic interface for running automated test scenarios.
Sends messages, collects responses, optionally runs the discriminator, and generates reports.

Usage:
    python -m dev_chat.runner --scenario scenarios/basic_sales.json
    python -m dev_chat.runner --message "quero saber o preço"
    python -m dev_chat.runner --interactive
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.settings import settings

# Force dev mode
if not settings.DEV_CHAT_MODE:
    print("⚠  DEV_CHAT_MODE is not enabled. Set DEV_CHAT_MODE=true in .env or environment.")
    print("   Proceeding anyway for the test runner...")


from app.services.redis_service import get_redis
from app.services.state_manager_service import StateManagerService
from app.core.logger import get_logger

logger = get_logger(__name__)
redis_client = get_redis()
state_manager = StateManagerService()


def get_contact_id(session_id: str) -> str:
    return f"dev-{session_id}"


def send_message(session_id: str, message: str, contact_name: str = "Test Runner"):
    """Send a message through the full pipeline (simulating Callbell webhook)."""
    from main import process_incoming_message

    contact_id = get_contact_id(session_id)

    # Store user message in dev history
    now = datetime.now(timezone.utc)
    user_msg = json.dumps({
        "uuid": str(uuid.uuid4()),
        "status": "received",
        "text": message,
        "createdAt": now.strftime('%Y-%m-%dT%H:%M:%SZ')
    })
    redis_client.rpush(f"dev:history:{contact_id}", user_msg)

    # Build fake Callbell payload
    payload = {
        "uuid": str(uuid.uuid4()),
        "status": "received",
        "text": message,
        "attachments": [],
        "messageContext": {},
        "contact": {
            "uuid": contact_id,
            "name": contact_name,
            "phoneNumber": "+5500000000000",
            "team": {"uuid": "d468731afdba45c3a3a65895e4b08a5a"}
        }
    }

    process_incoming_message(payload)


def wait_for_response(session_id: str, timeout: int = 120, poll_interval: float = 2.0) -> list:
    """Wait for bot response messages to appear in the dev outbox."""
    contact_id = get_contact_id(session_id)
    elapsed = 0
    messages = []

    # Wait a bit before first poll (debounce is 4s + processing time)
    time.sleep(5)

    while elapsed < timeout:
        msg = redis_client.lpop(f"dev:outbox:{contact_id}")
        if msg is not None:
            messages.append(json.loads(msg))
            # Keep draining for a short window in case multiple messages arrive
            time.sleep(1)
            while True:
                extra = redis_client.lpop(f"dev:outbox:{contact_id}")
                if extra is None:
                    break
                messages.append(json.loads(extra))
            break

        time.sleep(poll_interval)
        elapsed += poll_interval

    return messages


def run_discriminator(session_id: str, bot_messages: list) -> dict:
    """Run the discriminator agent on bot response."""
    from dev_chat.discriminator import analyze_response

    contact_id = get_contact_id(session_id)
    state, _ = state_manager.get_state(contact_id)

    raw_history = redis_client.lrange(f"dev:history:{contact_id}", 0, -1)
    history = [json.loads(m) for m in raw_history]

    return analyze_response(
        bot_response=[m.get('text', '') for m in bot_messages],
        conversation_state=state.model_dump(),
        history=history
    )


def reset_session(session_id: str):
    """Reset all data for a dev session."""
    contact_id = get_contact_id(session_id)
    keys = [
        f"state:{contact_id}", f"dev:history:{contact_id}", f"dev:outbox:{contact_id}",
        f"contact_info:{contact_id}", f"contacts_messages:waiting:{contact_id}",
        f"pending_task:{contact_id}", f"processing:{contact_id}",
        f"history:last_timestamp:{contact_id}", f"history:last_timestamp:to_follow_up:{contact_id}",
        f"history_raw:{contact_id}", f"shorterm_history:{contact_id}",
        f"longterm_history:{contact_id}", f"follow_up_level:{contact_id}",
        f"{contact_id}:attachments", f"{contact_id}:sended_catalogs",
        f"{contact_id}:last_processed_messages", f"{contact_id}:last_system_operation_output",
        f"{contact_id}:getting_data_from_user", f"{contact_id}:customer_profile",
        f"doing_strategy:{contact_id}", f"refining_strategy:{contact_id}",
        f"lock_enrichment_pipeline:{contact_id}", f"dev:discriminator:{contact_id}",
    ]
    pipe = redis_client.pipeline()
    for key in keys:
        pipe.delete(key)
    pipe.srem("contacts", contact_id)
    pipe.execute()


def run_scenario(scenario: dict, use_discriminator: bool = False):
    """
    Run a test scenario.

    scenario format:
    {
        "name": "Basic Sales Flow",
        "session_id": "test-sales-basic",
        "contact_name": "João Silva",
        "messages": [
            {"text": "oi", "wait": 30},
            {"text": "quero saber sobre rastreamento pra moto", "wait": 60},
            {"text": "quanto custa?", "wait": 60}
        ]
    }
    """
    session_id = scenario.get('session_id', f"scenario-{int(time.time())}")
    contact_name = scenario.get('contact_name', 'Test Runner')
    messages = scenario.get('messages', [])

    print(f"\n{'='*60}")
    print(f"  Scenario: {scenario.get('name', session_id)}")
    print(f"  Session:  {session_id}")
    print(f"  Messages: {len(messages)}")
    print(f"{'='*60}\n")

    # Reset first
    reset_session(session_id)
    time.sleep(1)

    results = []

    for i, msg_config in enumerate(messages):
        text = msg_config if isinstance(msg_config, str) else msg_config.get('text', '')
        wait = msg_config.get('wait', 60) if isinstance(msg_config, dict) else 60

        print(f"[{i+1}/{len(messages)}] User: {text}")

        send_message(session_id, text, contact_name)
        bot_messages = wait_for_response(session_id, timeout=wait)

        if bot_messages:
            for m in bot_messages:
                bot_text = (m.get('text', '') or '').replace('*Alessandro Assistente Global:*\n', '')
                print(f"  Bot: {bot_text[:100]}{'...' if len(bot_text) > 100 else ''}")
        else:
            print("  Bot: [NO RESPONSE - TIMEOUT]")

        result = {
            "turn": i + 1,
            "user_message": text,
            "bot_messages": [m.get('text', '') for m in bot_messages],
            "response_received": len(bot_messages) > 0
        }

        if use_discriminator and bot_messages:
            print("  🔍 Running discriminator...")
            analysis = run_discriminator(session_id, bot_messages)
            result["discriminator"] = analysis
            score = analysis.get('overall_score', 'N/A')
            print(f"  📊 Score: {score}/10")
            if analysis.get('gaps'):
                for gap in analysis['gaps'][:3]:
                    print(f"  ⚠  {gap}")

        results.append(result)
        print()

    # Summary
    print(f"\n{'='*60}")
    print(f"  RESULTS SUMMARY")
    print(f"{'='*60}")
    total = len(results)
    responded = sum(1 for r in results if r['response_received'])
    print(f"  Turns: {total} | Responses: {responded}/{total}")

    if use_discriminator:
        scores = [r['discriminator']['overall_score'] for r in results
                  if 'discriminator' in r and isinstance(r['discriminator'].get('overall_score'), (int, float))]
        if scores:
            avg = sum(scores) / len(scores)
            print(f"  Avg Score: {avg:.1f}/10 | Min: {min(scores)} | Max: {max(scores)}")

    print()
    return results


def interactive_mode(session_id: str = "interactive", use_discriminator: bool = False):
    """Interactive chat mode from the terminal."""
    print(f"\n🔧 Dev Chat Interactive Mode (session: {session_id})")
    print(f"   Discriminator: {'ON' if use_discriminator else 'OFF'}")
    print(f"   Commands: /reset, /state, /disc, /quit\n")

    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not text:
            continue

        if text == '/quit':
            break
        elif text == '/reset':
            reset_session(session_id)
            print("  ✓ Session reset\n")
            continue
        elif text == '/state':
            contact_id = get_contact_id(session_id)
            state, _ = state_manager.get_state(contact_id)
            print(json.dumps(state.model_dump(), indent=2, ensure_ascii=False, default=str))
            continue
        elif text == '/disc':
            use_discriminator = not use_discriminator
            print(f"  Discriminator: {'ON' if use_discriminator else 'OFF'}\n")
            continue

        send_message(session_id, text)
        print("  ⏳ Waiting for response...")
        bot_messages = wait_for_response(session_id)

        if bot_messages:
            for m in bot_messages:
                bot_text = (m.get('text', '') or '').replace('*Alessandro Assistente Global:*\n', '')
                print(f"  Alessandro: {bot_text}")

            if use_discriminator:
                print("\n  🔍 Discriminator analysis...")
                analysis = run_discriminator(session_id, bot_messages)
                score = analysis.get('overall_score', 'N/A')
                print(f"  📊 Score: {score}/10")
                if analysis.get('gaps'):
                    print("  Gaps:")
                    for gap in analysis['gaps']:
                        print(f"    - {gap}")
                if analysis.get('suggestions'):
                    print("  Sugestões:")
                    for s in analysis['suggestions']:
                        print(f"    - {s}")
        else:
            print("  ❌ No response (timeout)")

        print()


def main():
    parser = argparse.ArgumentParser(description='Dev Chat Test Runner')
    parser.add_argument('--scenario', type=str, help='Path to scenario JSON file')
    parser.add_argument('--message', type=str, help='Send a single message')
    parser.add_argument('--interactive', action='store_true', help='Interactive chat mode')
    parser.add_argument('--session', type=str, default='runner', help='Session ID')
    parser.add_argument('--discriminator', action='store_true', help='Enable discriminator analysis')
    parser.add_argument('--reset', action='store_true', help='Reset session before running')
    parser.add_argument('--output', type=str, help='Save results to JSON file')

    args = parser.parse_args()

    if args.reset:
        reset_session(args.session)
        print(f"Session {args.session} reset.")

    if args.interactive:
        interactive_mode(args.session, args.discriminator)

    elif args.scenario:
        with open(args.scenario, 'r', encoding='utf-8') as f:
            scenario = json.load(f)
        results = run_scenario(scenario, args.discriminator)
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"Results saved to {args.output}")

    elif args.message:
        send_message(args.session, args.message)
        print(f"Message sent. Waiting for response...")
        bot_messages = wait_for_response(args.session)
        if bot_messages:
            for m in bot_messages:
                print(f"Bot: {m.get('text', '')}")
            if args.discriminator:
                analysis = run_discriminator(args.session, bot_messages)
                print(f"\nDiscriminator: {json.dumps(analysis, indent=2, ensure_ascii=False)}")
        else:
            print("No response (timeout)")

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
