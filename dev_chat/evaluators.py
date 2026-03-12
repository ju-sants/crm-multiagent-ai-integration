"""
Agent Evaluators — Rubric-based quality scoring for any benchmarkable agent.

Architecture mirrors discriminator.py: Pre-Computed Rule Registries + Structured
Rubric Scoring per agent type. Rules and pricing are extracted once at module load;
the LLM focuses purely on evaluation against weighted dimensions.

Covers: StrategicAdvisor, IncrementalStrategicPlanner, RoutingAgent.
CommunicationAgent delegates to discriminator.py.
"""

import json
import os
import yaml

from app.config.llm_config import create_llm
from app.core.logger import get_logger
from dev_chat.eval_utils import (
    multi_model_evaluate, compute_weighted_score, check_prompt_staleness,
)

logger = get_logger(__name__)

_BASE_DIR = os.path.join(os.path.dirname(__file__), '..')
_PROMPTS_DIR = os.path.join(_BASE_DIR, 'app', 'crews', 'agents_definitions', 'prompts')
_KNOWLEDGE_DIR = os.path.join(_BASE_DIR, 'app', 'domain_knowledge')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STATIC PRE-COMPUTED DATA (loaded once at module import)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_pricing_reference() -> str:
    """Compact pricing markdown table from product YAMLs."""
    products_dir = os.path.join(_KNOWLEDGE_DIR, 'products')
    if not os.path.isdir(products_dir):
        return ""

    lines = ["| Plano | Tipo | Adesão | Mensalidade | Público |",
             "|-------|------|--------|-------------|---------|"]

    for fname in sorted(os.listdir(products_dir)):
        if not fname.endswith('.yaml'):
            continue
        try:
            with open(os.path.join(products_dir, fname), 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            for plan in data.get('plans', []):
                name = plan.get('name', '?')
                ptype = plan.get('type', '?')
                pricing = plan.get('pricing', {})
                adesao = pricing.get('adesao', pricing.get('installation_fee', '?'))
                mensal = pricing.get('mensalidade', pricing.get('monthly_fee', '?'))
                audience = plan.get('target_audience', '?')
                if isinstance(audience, list):
                    audience = ', '.join(audience[:2])
                lines.append(f"| {name} | {ptype} | {adesao} | {mensal} | {audience} |")
        except Exception:
            continue

    return "\n".join(lines) if len(lines) > 2 else ""


def _build_agent_rules() -> dict:
    """Pre-extract rules per agent type to avoid re-reading YAML per call."""
    return {
        "StrategicAdvisor": {
            "mandatory": [
                "Diagnóstico OBRIGATÓRIO antes da recomendação — NÃO criar product_presentation_strategy sem dados de qualificação",
                "knowledge_service_tool é ÚNICA fonte factual — PROIBIDO inventar/assumir dados",
                "Se informação não encontrada após buscas exaustivas → sinalizar em information_gaps",
                "disclosure_checklist OBRIGATÓRIO com status 'pending' para cada termo a esclarecer",
                "NUNCA remover itens do checklist — apenas adicionar novos, únicos",
                "Foco principal da estratégia DEVE derivar da client_message atual (não do histórico)",
                "Múltiplas chamadas iterativas à knowledge_service_tool são esperadas e incentivadas",
            ],
            "prohibited": [
                "PROIBIDO criar product_presentation_strategy sem dados mínimos de qualificação",
                "PROIBIDO inventar preços, funcionalidades ou prazos",
                "PROIBIDO oferecer PGS para carros/caminhões (APENAS motos)",
                "PROIBIDO oferecer PGS em DDD 66 (Mato Grosso)",
            ],
            "weights": {
                "context_coherence": 0.25,
                "product_strategy": 0.25,
                "guidance_quality": 0.20,
                "payload_accuracy": 0.20,
                "checklist_quality": 0.10,
            },
        },
        "IncrementalStrategicPlannerAgent": {
            "mandatory": [
                "PEGAR plano existente e TORNÁ-LO MELHOR — não reescrever do zero",
                "Pesquisa iterativa OBRIGATÓRIA na knowledge_service_tool para preencher gaps",
                "disclosure_checklist: apenas ADICIONAR itens novos — NUNCA remover/alterar existentes",
                "Poda de otimização: remover informações obsoletas (perguntas já respondidas, etc.)",
                "Cada refinamento deve agregar valor real e avançar em direção ao objetivo",
            ],
            "prohibited": [
                "PROIBIDO descartar plano anterior e criar do zero (exceto se completamente fraco)",
                "PROIBIDO contradizer decisões já tomadas sem justificativa",
                "PROIBIDO inventar dados factuais",
            ],
            "weights": {
                "incrementality": 0.30,
                "consistency": 0.25,
                "message_incorporation": 0.25,
                "refinement_quality": 0.20,
            },
        },
        "RoutingAgent": {
            "mandatory": [
                "operational_context DEVE refletir a intenção real (BUDGET/SUPPORT/CUSTOMER_SERVICE)",
                "is_plan_acceptable=False se primeira msg sem plano OU mudança completa de assunto",
                "is_sales_final_step=True APENAS se cliente CLARAMENTE confirma compra",
                "action DEVE ser consistente com operational_context",
            ],
            "prohibited": [
                "PROIBIDO rotear para system_operations sem necessidade real",
                "PROIBIDO classificar is_sales_final_step=True para dúvidas/perguntas",
            ],
            "weights": {
                "classification": 0.30,
                "plan_decision": 0.25,
                "purchase_detection": 0.25,
                "action_routing": 0.20,
            },
        },
    }


_PRICING_REFERENCE = _build_pricing_reference()
_AGENT_RULES = _build_agent_rules()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RUBRIC-BASED EVALUATOR PROMPTS (focused on SCORING)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_STRATEGY_EVALUATOR_PROMPT = """Você é um avaliador de qualidade de planos estratégicos para a Global System (rastreamento veicular).

Avalie o output do StrategicAdvisor usando as dimensões ponderadas abaixo. As regras já foram extraídas — foque na AVALIAÇÃO.

## RUBRICA — 5 Dimensões

### D1: COERÊNCIA COM CONTEXTO (peso {w_ctx})
- customer_context_summary captura a situação real do cliente?
- Insights acionáveis (não genéricos)?
- Modo correto: QUALIFICATION (sem dados) / PRESENTATION (com dados) / RESOLUTION (suporte)?

### D2: ESTRATÉGIA DE PRODUTO (peso {w_prod})
- Produto mais completo primeiro (upsell)?
- Hierarquia: moto→PGS; carro→Híbrido/GSM+WiFi; frota→SATELITAL
- Não oferece produto incompatível?
- primary_offer e secondary_offer adequadas?

### D3: QUALIDADE DO GUIDANCE (peso {w_guid})
- key_talking_points concretos e acionáveis?
- key_questions_to_ask avançam a qualificação?
- next_step_preview claro?
- Tom adequado ao estágio?

### D4: PRECISÃO DO INFORMATION_PAYLOAD (peso {w_pay})
- Preços conferem com tabela de referência?
- Zero dados inventados? (ALUCINAÇÃO = -3)
- Funcionalidades descritas corretamente?

### D5: DISCLOSURE CHECKLIST (peso {w_chk})
- Itens obrigatórios presentes?
- Status correto (pending)?
- Sem duplicatas?

## CÁLCULO: overall = D1×{w_ctx} + D2×{w_prod} + D3×{w_guid} + D4×{w_pay} + D5×{w_chk}

Penalizações — formato estruturado:
[{{"type": "hallucination", "severity": 3, "description": "..."}}, {{"type": "incompatible_product", "severity": 2, "description": "..."}}, {{"type": "generic_guidance", "severity": 1, "description": "..."}}]

## JSON OBRIGATÓRIO (sem markdown):
{{
    "scores": {{ "context_coherence": <0-10>, "product_strategy": <0-10>, "guidance_quality": <0-10>, "payload_accuracy": <0-10>, "checklist_quality": <0-10> }},
    "overall_score": <0.0-10.0>,
    "reasoning": "<análise concisa>",
    "issues": ["<problema>"],
    "hallucinations": ["<dado inventado>"],
    "penalties_applied": [{{"type": "<tipo>", "severity": <1-3>, "description": "<motivo>"}}],
    "suggestions": ["<melhoria>"]
}}"""


_ROUTING_EVALUATOR_PROMPT = """Você é um avaliador do RoutingAgent da Global System (rastreamento veicular).

Avalie a classificação e roteamento usando as dimensões ponderadas. Regras pré-extraídas na seção de referência.

## RUBRICA — 4 Dimensões

### D1: CLASSIFICAÇÃO (peso {w_cls})
- operational_context correto? (vendas=BUDGET, problemas=SUPPORT, dúvidas=CUSTOMER_SERVICE)
- identified_topic reflete o assunto real?
- prefers_audio detectado?

### D2: DECISÃO DE PLANO (peso {w_plan})
- is_plan_acceptable=False se primeira msg ou mudança de assunto
- is_plan_acceptable=True se continuação do mesmo tema

### D3: DETECÇÃO DE COMPRA (peso {w_purch})
- is_sales_final_step=True APENAS com confirmação clara
- False para dúvidas, interesse sem confirmação

### D4: AÇÃO (peso {w_act})
- action consistente com operational_context?
- Não roteia para sys_ops desnecessariamente?

## CÁLCULO: overall = D1×{w_cls} + D2×{w_plan} + D3×{w_purch} + D4×{w_act}

## JSON OBRIGATÓRIO:
{{
    "scores": {{ "classification": <0-10>, "plan_decision": <0-10>, "purchase_detection": <0-10>, "action_routing": <0-10> }},
    "overall_score": <0.0-10.0>,
    "reasoning": "<análise>",
    "issues": ["<problema>"],
    "penalties_applied": [{{"type": "<tipo>", "severity": <1-3>, "description": "<motivo>"}}],
    "suggestions": ["<melhoria>"]
}}"""


_REFINE_EVALUATOR_PROMPT = """Você é um avaliador do IncrementalStrategicPlannerAgent da Global System.

Avalie o refinamento do plano estratégico. Regras pré-extraídas na seção de referência.

## RUBRICA — 4 Dimensões

### D1: INCREMENTALIDADE (peso {w_inc})
- Plano REFINADO (bom) vs REESCRITO do zero (ruim)?
- Insights anteriores preservados?
- Nova informação integrada cirurgicamente?

### D2: CONSISTÊNCIA (peso {w_con})
- product_presentation_strategy coerente com histórico?
- Sem contradições com decisões anteriores?
- disclosure_checklist preserva itens preexistentes?

### D3: INCORPORAÇÃO DA MENSAGEM (peso {w_msg})
- Última mensagem do cliente analisada?
- Novos talking_points refletem a nova necessidade?
- key_questions atualizadas pro novo estágio?

### D4: QUALIDADE DO REFINAMENTO (peso {w_ref})
- Mudanças agregam valor real?
- Plano progride em direção ao objetivo?
- Poda de otimização feita (removeu obsoletos)?

## CÁLCULO: overall = D1×{w_inc} + D2×{w_con} + D3×{w_msg} + D4×{w_ref}

Penalizações — formato estruturado:
[{{"type": "hallucination", "severity": 3, "description": "..."}}, {{"type": "total_rewrite", "severity": 2, "description": "..."}}, {{"type": "contradiction", "severity": 2, "description": "..."}}]

## JSON OBRIGATÓRIO:
{{
    "scores": {{ "incrementality": <0-10>, "consistency": <0-10>, "message_incorporation": <0-10>, "refinement_quality": <0-10> }},
    "overall_score": <0.0-10.0>,
    "reasoning": "<análise>",
    "issues": ["<problema>"],
    "penalties_applied": [{{"type": "<tipo>", "severity": <1-3>, "description": "<motivo>"}}],
    "suggestions": ["<melhoria>"]
}}"""


def _format_evaluator_prompt(template: str, weights: dict) -> str:
    """Inject weight values into evaluator prompt template."""
    replacements = {}
    for key, value in weights.items():
        # Map weight keys to template placeholders
        short_keys = {
            'context_coherence': 'w_ctx', 'product_strategy': 'w_prod',
            'guidance_quality': 'w_guid', 'payload_accuracy': 'w_pay',
            'checklist_quality': 'w_chk', 'classification': 'w_cls',
            'plan_decision': 'w_plan', 'purchase_detection': 'w_purch',
            'action_routing': 'w_act', 'incrementality': 'w_inc',
            'consistency': 'w_con', 'message_incorporation': 'w_msg',
            'refinement_quality': 'w_ref',
        }
        placeholder = short_keys.get(key)
        if placeholder:
            replacements[placeholder] = str(value)

    for k, v in replacements.items():
        template = template.replace('{' + k + '}', v)
    return template


# Pre-format evaluator prompts with weights
_EVALUATOR_CONFIG = {
    "StrategicAdvisor": (
        _format_evaluator_prompt(_STRATEGY_EVALUATOR_PROMPT, _AGENT_RULES["StrategicAdvisor"]["weights"]),
        _AGENT_RULES["StrategicAdvisor"],
    ),
    "IncrementalStrategicPlannerAgent": (
        _format_evaluator_prompt(_REFINE_EVALUATOR_PROMPT, _AGENT_RULES["IncrementalStrategicPlannerAgent"]["weights"]),
        _AGENT_RULES["IncrementalStrategicPlannerAgent"],
    ),
    "RoutingAgent": (
        _format_evaluator_prompt(_ROUTING_EVALUATOR_PROMPT, _AGENT_RULES["RoutingAgent"]["weights"]),
        _AGENT_RULES["RoutingAgent"],
    ),
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PUBLIC API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def evaluate_agent_output(
    agent_name: str,
    output: str,
    inputs: dict,
    conversation_state: dict = None,
    evaluator_model: str = None,
    evaluation_focus: dict = None,
) -> dict:
    """
    Multi-model consensus evaluation of any agent's output.

    Uses 2+ cross-provider LLMs (median aggregation) to eliminate single-model
    bias. Falls back to single model if evaluator_model is explicitly specified.

    Args:
        evaluator_model: If set, uses only this model (bypasses consensus).
                         If None, uses multi-model consensus (DEFAULT_EVAL_MODELS).
        evaluation_focus: Optional per-agent scenario lens dict.

    For CommunicationAgent, delegates to discriminator.py.
    """
    # CommunicationAgent → use discriminator
    if agent_name == "CommunicationAgent":
        agent_lens = (evaluation_focus or {}).get("CommunicationAgent")
        return _evaluate_communication_agent(output, inputs, conversation_state, scenario_lens=agent_lens)

    config = _EVALUATOR_CONFIG.get(agent_name)
    if not config:
        return {"overall_score": "N/A", "error": f"No evaluator for {agent_name}"}

    system_prompt, rules = config

    # Build scenario-specific lens section if provided
    agent_lens = (evaluation_focus or {}).get(agent_name)
    scenario_lens_section = ""
    if agent_lens and isinstance(agent_lens, dict):
        checkpoints = agent_lens.get("critical_checkpoints", [])
        if checkpoints:
            scenario_lens_section = f"""
═══════════════════════════════════════
LENTE DE CENÁRIO — CHECKPOINTS CRÍTICOS PARA {agent_name}
═══════════════════════════════════════
Os seguintes checkpoints são ESPECÍFICOS deste cenário. Avalie cada um e
inclua no reasoning se foram atendidos ou violados. Falha em checkpoint
crítico impacta o overall_score proporcionalmente.

{chr(10).join(f"  ✓ {cp}" for cp in checkpoints)}
"""

    # Build user prompt with ONLY dynamic data + pre-computed references
    user_prompt = f"""Avalie o seguinte output do agente {agent_name}.

═══════════════════════════════════════
OUTPUT DO AGENTE
═══════════════════════════════════════
{output[:3000]}

═══════════════════════════════════════
INPUTS RECEBIDOS PELO AGENTE
═══════════════════════════════════════
client_message: {inputs.get('client_message', 'N/A')}
operational_context: {inputs.get('operational_context', 'N/A')}
identified_topic: {inputs.get('identified_topic', 'N/A')}
turn: {inputs.get('turn', 'N/A')}
conversation_state (resumo): {json.dumps(inputs.get('conversation_state', ''), ensure_ascii=False)[:1500]}
shorterm_history: {str(inputs.get('shorterm_history', ''))[:800]}

═══════════════════════════════════════
REGRAS DO AGENTE (pré-extraídas)
═══════════════════════════════════════
[OBRIGATÓRIO]
{chr(10).join(f"  • {r}" for r in rules.get('mandatory', []))}

[PROIBIDO]
{chr(10).join(f"  • {r}" for r in rules.get('prohibited', []))}

═══════════════════════════════════════
TABELA DE PREÇOS (referência factual)
═══════════════════════════════════════
{_PRICING_REFERENCE if _PRICING_REFERENCE else 'N/A'}
{scenario_lens_section}
═══════════════════════════════════════
AVALIE E RETORNE JSON
═══════════════════════════════════════"""

    models = [evaluator_model] if evaluator_model else None  # None → multi-model consensus

    try:
        result = multi_model_evaluate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            models=models,
            weights=rules.get('weights', {}),
        )

        models_used = result.get('_meta', {}).get('models_used', [])
        result["evaluator_model"] = models_used
        result["agent_evaluated"] = agent_name
        return result

    except Exception as e:
        logger.error(f"Evaluator failed for {agent_name}: {e}", exc_info=True)
        return {
            "overall_score": "ERROR",
            "error": str(e)[:300],
            "agent_evaluated": agent_name,
        }


def _evaluate_communication_agent(output: str, inputs: dict, conversation_state: dict, scenario_lens: dict = None) -> dict:
    """Delegate CommunicationAgent evaluation to the full discriminator."""
    from dev_chat.discriminator import analyze_response
    from app.utils.funcs.parse_llm_output import parse_json_from_string

    parsed = parse_json_from_string(output)
    messages = []
    if parsed and isinstance(parsed, tuple) and len(parsed) >= 1:
        first = parsed[0]
        if isinstance(first, dict):
            messages = first.get("messages_sequence", [])

    state = conversation_state or {}
    contact_id = inputs.get("contact_id", "unknown")

    from app.services.redis_service import get_redis
    r = get_redis()
    raw_history = r.lrange(f"dev:history:{contact_id}", 0, -1)
    history = [json.loads(m) for m in raw_history]

    result = analyze_response(
        bot_response=messages or [output[:500]],
        conversation_state=state,
        history=history,
        scenario_lens=scenario_lens,
    )
    result["agent_evaluated"] = "CommunicationAgent"
    return result
