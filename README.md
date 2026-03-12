# CrewAI Sales & Support Autonomous Agent System

> A production-grade multi-agent AI platform that autonomously handles sales conversations, customer support, and CRM operations over WhatsApp — powered by 13 specialized CrewAI agents, real-time strategic planning, and a full-featured development environment.

---

## What This Is

This system replaces a human sales and support team with an autonomous AI workforce. A customer sends a WhatsApp message; 13 specialized AI agents collaborate to understand intent, build a sales strategy, query backend systems, and craft a natural response — all within seconds.

It's not a chatbot. It's an **autonomous business operation** that:

- **Sells** — qualifies leads, recommends products with upsell strategy, handles objections, closes deals, collects registration data
- **Supports** — diagnoses technical problems, queries vehicle tracking systems, sends hardware resets, calculates service costs
- **Remembers** — maintains rich conversation state, customer psychological profiles, and incrementally summarized history across sessions
- **Re-engages** — autonomously decides when and how to follow up with inactive customers based on behavioral analysis

---

## Architecture Overview

```
WhatsApp → Callbell Webhook → Flask → Celery Task Queue
                                          │
                    ┌─────────────────────┼──────────────────────┐
                    │                     │                      │
              RoutingAgent          StrategicAdvisor      VerifySystemAction
              (classify intent)    (build/refine plan)    (proactive diagnostics)
                    │                     │                      │
                    └─────────┬───────────┘                      │
                              │                                  │
                      BackendRouting ◄────────────────────────────┘
                    (state machine)
                     ┌────┴─────┐
                     │          │
              Communication  Registration
              Agent          Agent
              (craft reply)  (collect data)
                     │
                     ▼
              Post-Processing Pipeline (async)
              ├── Send Message (Callbell / Dev Chat)
              ├── HistorySummarizer (incremental)
              ├── StateSummarizer (compact state)
              └── ProfileEnhancer (customer 360°)
```

### The 13 Agents

| Agent | Role | Tools |
|-------|------|-------|
| **RoutingAgent** | Classifies intent, validates plan relevance, defines operational context | — |
| **StrategicAdvisor** | Builds conversation blueprints from scratch with product strategy | `knowledge_service_tool` |
| **IncrementalStrategicPlanner** | Refines existing plans: fills gaps, prunes obsolete info, enriches strategy | `knowledge_service_tool` |
| **SystemOperationsAgent** | Executes backend queries (vehicles, payments, positions, resets) | `system_operations_tool` |
| **CommunicationAgent** ("Alessandro") | Transforms strategy into natural WhatsApp dialogue with persuasion and proactivity | `drill_down_topic_tool` |
| **RegistrationDataCollector** | Collects customer registration data step-by-step post-sale | — |
| **PurchaseConfirmationAgent** | Contextual detection of purchase signals (avoids false positives) | — |
| **VerifySystemActionAgent** | Proactively diagnoses if backend actions are needed based on conversation | — |
| **HistorySummarizerAgent** | Incrementally summarizes conversation into topics with quality scores | — |
| **DataQualityAgent** | Cleans noisy conversation topics | — |
| **StateSummarizerAgent** | Compacts conversation state, deduplicates entities, formats data | — |
| **ProfileEnhancerAgent** | Builds psychological customer profiles (motivations, frustrations, interests) | — |
| **FollowUpAgent** | Decides if/when to re-engage inactive customers based on behavioral analysis | — |

### Key Design Patterns

- **Parallel Orchestration**: Routing and strategy run concurrently via Celery groups, synchronized through Redis flags
- **State Distillation**: Each agent receives only the state fields it needs (`agent_state_mapping`), reducing token usage and preventing interference
- **Semantic State Merge**: Lists with identity keys are merged by key (not overwritten), ensuring append-only fields never lose data
- **4-Second Debounce**: Multiple rapid messages are batched into a single agent invocation
- **Enrichment Pipeline**: After sending the response, 4 agents run asynchronously (history → state → profile → quality) to prepare for the next turn

---

## Dev Chat — Full-Stack Development Environment

The system ships with a complete development environment that mirrors production **without touching real WhatsApp channels**. This is not an afterthought — it's a first-class feature designed for iterating on agent behavior, benchmarking LLMs, and debugging conversational flows.

### Web UI

Start with `DEV_CHAT_MODE=true` and open `http://localhost:8080/dev/`

The interface provides:

- **Chat Mode** — WhatsApp-style conversation simulator with audio recording, session management, and message inspector
- **State Inspector** — Real-time view of `ConversationState` (4 tabs: State, History, Discriminator, Analytics)
- **Session Management** — Create, switch, reset sessions. Each session is an isolated conversation with its own state
- **State Override** — PUT any field in `ConversationState` mid-conversation to test edge cases

### CLI Runner

Automated testing with pre-built scenarios:

```bash
# Interactive chat
python -m dev_chat.runner --interactive

# Run a scenario
python -m dev_chat.runner --scenario dev_chat/scenarios/basic_sales_moto.json

# Single message
python -m dev_chat.runner --message "quero rastreamento pra minha moto"
```

**8 built-in scenarios:** `basic_sales_moto`, `sales_carro_completo`, `sales_objecao_preco`, `multi_topic_switch`, `edge_saudacao_ambigua`, `stress_mensagens_curtas`, `support_reset_senha`, `support_veiculo_parado`

Interactive commands: `/reset`, `/state`, `/disc` (run discriminator), `/quit`

### Discriminator — Rubric-Based Quality Evaluation

An automated evaluator that scores agent responses across 5 weighted dimensions:

| Dimension | Weight | What it checks |
|-----------|--------|---------------|
| Factual Precision | 30% | Hallucination detection against knowledge base |
| Structural Compliance | 20% | JSON format, `messages_sequence` structure |
| Tone & Style | 20% | WhatsApp-native language, proactivity, conciseness |
| Rule Adherence | 15% | MANDATORY/PROHIBITED rules from agent prompts |
| Business Alignment | 15% | Product hierarchy, upsell strategy, disclosure compliance |

Rules are pre-extracted at module load (zero per-call overhead). Automatic penalties: -3 per factual hallucination, -2 per prohibited rule violation.

### LLM Benchmarks

Compare different LLMs on the same agent with identical context:

- Supports **xAI Grok**, **Google Gemini** (with thinking budget), **OpenAI** models
- Uses synthetic states (pre-populated scenarios) for controlled, reproducible comparisons
- Captures: duration, token usage, quality score, interpolated prompts
- Multiple iterations for statistical significance

### Analytics

Automatic instrumentation of `Crew.kickoff()` captures per-session and global metrics: timing, model used, token counts, errors.

---

## Knowledge System

Agents don't hallucinate product information — they query a structured knowledge base through tools.

The knowledge base is organized as domain-specific YAML files:

```
app/domain_knowledge/
├── business_rules.yaml          # Company info, upsell directives, customer profiles
├── communication.yaml           # Sales philosophy, support scripts, theft protocols
├── contracts.yaml               # Legal terms (standard, PGS motorcycle)
├── operational_procedures.yaml  # Installation, maintenance, compatibility, regional rules
├── application_features.yaml    # Mobile app capabilities
├── web_access_features.yaml     # Web platform features
└── products/
    ├── fleet_and_light_vehicles.yaml   # Car/truck plans (Satelital, GSM+WiFi, GSM 4G)
    ├── motorcycles.yaml                # Motorcycle plans (PGS, Basic)
    └── personal_mobility.yaml          # Personal mobility devices
```

**`knowledge_service_tool`** — Batch query interface with fuzzy matching (`thefuzz`, score > 85), topic aliases, and multi-topic resolution in a single call.

**`drill_down_topic_tool`** — Detailed sub-section lookup for specific plan attributes (pricing, FAQ, contract terms).

**`system_operations_tool`** — 13 backend operations: search clients, vehicle details, positions, trips, events, geofences, payment history, financials, tracker resets, displacement cost calculation.

---

## Voice & Audio Pipeline

```
INPUT (Speech-to-Text):
  WhatsApp audio → Gladia API v2 (async polling, 120s timeout, SHA256 cache)
  Dev Chat audio → OpenAI Whisper

OUTPUT (Text-to-Speech):
  ConversationState.prefers_audio == true
    → Text normalization (acronyms, numbers, abbreviations)
    → ElevenLabs API (multilingual_v2, 1.2x speed, custom voice)
    → Cached audio URL → sent as WhatsApp document via Callbell
```

Image attachments are described via a dedicated Image Description API with HMAC-SHA256 authentication.

---

## State Management

- **ConversationState** — Pydantic model with 20+ typed fields (metadata, entities, products discussed, disclosure checklist, strategic plan, qualification tracker, objections, goals)
- **Persistence** — Redis with key `state:{contact_id}`, JSON-serialized via Pydantic
- **Concurrency** — Distributed Redis locks (`lock:state:{id}`, 10s timeout)
- **Coordination Flags** — `doing_strategy`, `refining_strategy`, `doing_system_operations`, etc. with 300s safety TTL
- **Dual History** — `shorterm_history` (raw messages) + `longterm_history` (incrementally summarized topics with quality scores)

---

## NLP & Post-Processing

- **Contact Name Extraction** — Fine-tuned NER model ([`ju-sants/contact-name-extractor`](https://huggingface.co/ju-sants/contact-name-extractor)) extracts real names from WhatsApp display names (e.g., "João 🚗 Silva" → "João Silva")
- **Verbal Tic Removal** — Detects and removes LLM artifacts ("Entendi que...", "Obrigado por perguntar...") using sequence matching
- **Name Over-Repetition Fix** — Post-generation pass removes excessive customer name mentions from agent responses
- **Text Normalization for TTS** — Converts abbreviations, numbers, and technical terms to speakable Portuguese

---

## Monkey Patches

Three surgical patches for third-party library issues:

| Patch | Problem | Solution |
|-------|---------|----------|
| `litellm_patch` | Grok/o4 models crash on `stop` parameter | Strips `stop` from completion calls, fixes model name prefixes |
| `crewai_telemetry_patch` | CrewAI phones home with telemetry | All telemetry methods replaced with no-ops |
| `crewai_tool_input_patch` | LLMs generate malformed tool inputs, agent gives up | Resilient regex parser extracts valid params from broken JSON |

---

## Autonomous Re-engagement

A Celery Beat worker runs every 5 minutes, scanning for inactive contacts:

1. Applies escalating backoff: 5min → 1h → 1d → 3d
2. Triggers `FollowUpAgent` for behavioral analysis (profile, history, time elapsed)
3. If approved, mounts a follow-up context and sends through the full agent pipeline
4. Tracks attempts to avoid harassment

---

## Quick Start

### Prerequisites

- Python 3.9+
- Redis server
- API keys: at least one LLM provider (Gemini, xAI, or OpenAI)

### Installation

```bash
git clone https://github.com/ju-sants/crm-multiagent-ai-integration.git
cd crm-multiagent-ai-integration

python -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file (see `app/config/settings.py` for all options):

```env
# LLM Providers (at least one required)
XAI_API_KEY="..."
GEMINI_API_KEY="..."
OPENAI_API_KEY="..."

# Redis
REDIS_HOST="localhost"
REDIS_PORT=6379

# WhatsApp Gateway (production only)
CALLBELL_API_KEY="..."

# Optional Services
ELEVEN_LABS_API_KEY="..."    # TTS
X_GLADIA_KEY="..."           # Audio transcription
GMAPS_API_KEY="..."          # Displacement cost calculation
```

### Running in Dev Chat Mode

```bash
# Terminal 1: Redis (if not already running)
redis-server

# Terminal 2: Celery Worker
DEV_CHAT_MODE=true celery -A app.services.celery_service.celery_app worker --loglevel=INFO --concurrency=2

# Terminal 3: Flask
DEV_CHAT_MODE=true python main.py
```

Open **http://localhost:8080/dev/** — you're talking to the full agent pipeline.

### Testing with Refactored Prompts

The system supports hot-swapping prompt files via environment variables:

```bash
export AGENTS_PROMPT_FILE='app/crews/agents_definitions/prompts/agents.refactored.yaml'
export TASKS_PROMPT_FILE='app/crews/agents_definitions/prompts/tasks.refactored.yaml'
```

### Running in Production

```bash
# All-in-one (Gunicorn + Celery Worker + Celery Beat)
./start.sh
```

Configure the Callbell webhook to point to `https://your-server/receive_message`.

---

## Project Structure

```
├── main.py                    # Flask app, webhook, Celery task orchestration
├── start.sh                   # Production startup (Gunicorn + Celery)
├── app/
│   ├── config/                # Settings, LLM provider configuration
│   ├── core/                  # Logger
│   ├── crews/
│   │   ├── agents_definitions/
│   │   │   ├── obj_declarations/  # Agent & task factory functions
│   │   │   └── prompts/          # Agent personalities & task specs (YAML)
│   │   └── src/
│   │       ├── main_crews/       # Core pipeline crews (routing, strategy, communication)
│   │       └── secondary_crews/  # Post-processing (enrichment, follow-up)
│   ├── domain_knowledge/      # Structured knowledge base (products, rules, procedures)
│   ├── models/                # Pydantic data models (ConversationState)
│   ├── patches/               # Monkey patches for CrewAI & LiteLLM
│   ├── services/              # External integrations (Callbell, Redis, Celery, audio, maps)
│   ├── tools/                 # LangChain tools for agents (knowledge, system operations)
│   ├── utils/                 # Callbacks, text normalization, reset integrations
│   └── workers/               # Celery Beat tasks (inactivity monitor)
└── dev_chat/
    ├── server.py              # Dev Chat Flask blueprint (15+ REST endpoints)
    ├── runner.py              # CLI test runner (scenarios, interactive, single message)
    ├── discriminator.py       # Rubric-based quality evaluator
    ├── evaluators.py          # Per-agent specialized evaluators
    ├── benchmarks.py          # Multi-LLM comparison engine
    ├── analytics.py           # Automatic Crew.kickoff() instrumentation
    ├── synthetic_states.py    # Pre-built conversation states for benchmarks
    ├── scenarios/             # JSON test scenarios (8 built-in)
    └── static/                # Web UI (dark-mode chat + dashboard)
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.9+, Flask, Gunicorn |
| AI Orchestration | CrewAI, LangChain Tools |
| LLM Providers | xAI Grok, Google Gemini (with thinking budget), OpenAI |
| Task Queue | Celery (Redis broker) |
| State & Cache | Redis |
| Speech-to-Text | Gladia API, OpenAI Whisper |
| Text-to-Speech | ElevenLabs |
| WhatsApp Gateway | Callbell API |
| NLP | Fine-tuned NER model, fuzzy matching (thefuzz) |
| Data Validation | Pydantic |
| Distance/Cost | Google Maps API |
| Notifications | Telegram Bot API |

---

## Suggested Repository Names

If renaming the repository:

- **`autonomous-sales-agent`** — emphasizes the autonomous nature
- **`crewai-whatsapp-sales-platform`** — specific and descriptive
- **`multiagent-conversational-crm`** — broader scope
