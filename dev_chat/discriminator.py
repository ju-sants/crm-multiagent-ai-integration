"""
Discriminator Agent — Rubric-based quality evaluation of bot responses.

Architecture: Pre-Computed Rule Registry + Structured Rubric Scoring.

Instead of dumping ~20K tokens of raw YAML/Python into the prompt and asking
the LLM to "extract rules", we:
  1. Pre-extract all rules from agent prompts at module load (STATIC)
  2. Pre-compute a compact pricing reference table (STATIC)
  3. Focus the LLM exclusively on SCORING against a structured rubric
  4. Inject only DYNAMIC data per call (bot response, state, history)

Evaluation dimensions (weighted):
  - Factual Accuracy (30%) — claims vs strategic_plan + pricing reference
  - Structural Compliance (20%) — response format, message flow
  - Tone & Style (20%) — WhatsApp-native, proactivity, concision
  - Rule Adherence (15%) — mandatory/prohibited rules from prompt
  - Business Alignment (15%) — product hierarchy, upsell, legal
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

def _build_rules_registry() -> dict:
    """Extract and categorize all rules from CommunicationAgent prompt at load time.

    Returns a structured dict with mandatory, prohibited, conditional, and
    preference rules — so the LLM never needs to extract them itself.
    """
    return {
        "mandatory": [
            "Fonte da verdade é EXCLUSIVAMENTE o strategic_plan — dados factuais DEVEM vir dele",
            "Cada resposta DEVE avançar a conversa proativamente (pergunta, sugestão ou próximo passo concreto)",
            "disclosure_checklist: atualizar status para 'communicated' após abordar item — NUNCA excluir/reordenar itens",
            "Se is_follow_up=true, primeira mensagem DEVE ser reabertura de conversa contextual",
            "Se meta do plano foi atingida ou cliente sinaliza fechamento, entrar em MODO FECHAMENTO com pergunta de confirmação",
            "Checklist jurídico (disclosure_checklist) DEVE ser abordado progressivamente durante a conversa",
            "products_discussed DEVE ser atualizado com planos mencionados na resposta",
            "messages_sequence DEVE ter progressão lógica: resposta direta → ponte → ação proativa",
        ],
        "prohibited": [
            "PROIBIDO reafirmar contexto que o cliente já forneceu (ex: 'entendo que você quer uma moto')",
            "PROIBIDO iniciar com saudações genéricas repetidas (ex: 'Olá!' em toda resposta)",
            "PROIBIDO inventar/alucinar dados factuais (preço, prazo, funcionalidade) não presentes no plano",
            "PROIBIDO afirmar cobertura de SEGURO — o serviço é RASTREAMENTO com garantia de reembolso",
            "PROIBIDO enviar catálogo (plan_names) se já foi enviado para este plano (verificar recently_sent_catalogs)",
            "PROIBIDO fazer perguntas irrelevantes que não contribuam para fechamento ou resolução",
        ],
        "conditional": [
            "plan_names: preencher SOMENTE SE (a) cliente pediu expressamente novamente OU (b) primeiro envio desse plano específico",
            "request_human_intervention: true apenas em casos extremos (ameaça, erro grave, impossibilidade)",
            "Se operational_context=BUDGET e meta atingida → mudar para closing mindset com pergunta de confirmação",
            "Se pending_disclosure_item existe → esse é o conteúdo proativo prioritário",
        ],
        "preferences": [
            "Concisão profissional: prefira 1-3 mensagens curtas (~2 linhas cada). Pense em construção a longo prazo — não precisa falar tudo em um turno",
            "Tom casual-profissional em PT-BR, emojis com moderação",
            "Entusiasmo genuíno mas calibrado, sem parecer forçado ou artificial",
            "Construir pontes lógicas entre pontos do plano nas transições de mensagem",
            "Orientação por valor: comece pela solução mais completa (benefícios, diferenciais), mas adapte-se ao perfil do cliente",
            "Persuasão sutil focada em benefícios, sem agressividade — preço é informação legítima, mas valor percebido constrói a venda",
        ],
    }


def _build_pricing_reference() -> str:
    """Build a compact pricing reference table from product YAMLs.

    Returns a markdown table instead of raw YAML — ~90% fewer tokens.
    """
    products_dir = os.path.join(_KNOWLEDGE_DIR, 'products')
    if not os.path.isdir(products_dir):
        return "Tabela de preços indisponível."

    lines = ["| Plano | Tipo | Adesão | Mensalidade | Público-Alvo |",
             "|-------|------|--------|-------------|--------------|"]

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

    return "\n".join(lines) if len(lines) > 2 else "Tabela de preços indisponível."


def _build_business_rules_summary() -> str:
    """Extract key business rules as a compact bullet list (not raw YAML)."""
    rules_path = os.path.join(_KNOWLEDGE_DIR, 'business_rules.yaml')
    try:
        with open(rules_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except Exception:
        return ""

    lines = []

    # Sales guidance
    sg = data.get('sales_guidance', {})
    if isinstance(sg, dict):
        hierarchy = sg.get('product_hierarchy', sg.get('upsell_hierarchy', ''))
        if hierarchy:
            lines.append(f"- Hierarquia de upsell: {hierarchy}")
        philosophy = sg.get('philosophy', '')
        if philosophy:
            lines.append(f"- Filosofia: {str(philosophy)[:200]}")

    # Customer profiles
    profiles = data.get('customer_profiles_and_triggers', {})
    if isinstance(profiles, dict):
        for profile_type, profile_data in list(profiles.items())[:3]:
            lines.append(f"- Perfil '{profile_type}': {str(profile_data)[:150]}")

    return "\n".join(lines[:10])


# Pre-compute at module load — NO per-call overhead
_RULES_REGISTRY = _build_rules_registry()
_PRICING_REFERENCE = _build_pricing_reference()
_BUSINESS_RULES_SUMMARY = _build_business_rules_summary()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RUBRIC-BASED SYSTEM PROMPT (focused on SCORING, not discovery)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DISCRIMINATOR_SYSTEM_PROMPT = """Você é um avaliador de qualidade de ELITE para respostas de um chatbot de atendimento WhatsApp (rastreamento veicular — Global System).

Seu trabalho é AVALIAR, não descobrir regras. As regras já foram extraídas e categorizadas abaixo. Foque 100% na análise da resposta.

## RUBRICA DE AVALIAÇÃO — 5 Dimensões com Pesos

### D1: PRECISÃO FACTUAL (peso 30%)
Compare CADA afirmação factual na resposta contra o `strategic_plan.information_payload` (fonte primária) e a tabela de preços (referência).
- ✅ VERIFICADO: tem respaldo direto — score alto
- ⚠️ INFERIDO: razoável mas não explícito — aceitável com nota
- ❌ INVENTADO: preço/funcionalidade/prazo sem respaldo = ALUCINAÇÃO GRAVE → -3 pontos automático
Score 10 = zero alucinações, todos os dados verificáveis. Score 0 = dados completamente inventados.

### D2: COMPLIANCE ESTRUTURAL (peso 20%)
- `messages_sequence`: progressão lógica? (direta → ponte → proativa)
- **Concisão**: A resposta reflete mentalidade WhatsApp? Prefira 1-3 mensagens curtas (~2 linhas cada). Respostas com 4+ mensagens ou parágrafos longos indicam falta de concisão — penalize proporcionalmente, mas considere o contexto (cliente fez múltiplas perguntas? Há informação complexa a transmitir?).
- `disclosure_checklist`: apenas status atualizado? Sem exclusão/reordenação?
- `plan_names`: respeitou regra de primeiro envio / recently_sent_catalogs?
- JSON válido, campos esperados presentes?
Score 10 = estrutura impecável, resposta limpa e profissional. Score 0 = JSON inválido ou resposta inundando o cliente.

### D3: TOM E ESTILO (peso 20%)
- WhatsApp-native: frases curtas, diretas, casual-profissional PT-BR
- Proatividade: avança a conversa com pergunta/ação concreta
- Sem reafirmação de contexto já conhecido pelo cliente
- Sem saudações genéricas repetidas
- Closing mindset em vendas (direciona para fechamento)
- Entusiasmo calibrado (confiante sem ser forçado)
Score 10 = comunicação perfeita. Score 0 = parece email corporativo ou robô.

### D4: ADERÊNCIA ÀS REGRAS (peso 15%)
As regras pré-extraídas do prompt estão na seção REGRAS DO AGENTE abaixo.
- Para cada regra [OBRIGATÓRIO]: foi cumprida? Não → penalizar
- Para cada regra [PROIBIDO]: foi violada? Sim → -2 pontos
- Para cada regra [CONDICIONAL]: condição se aplica? Se sim, foi cumprida?
Score 10 = zero violações. Score 0 = múltiplas violações graves.

### D5: ALINHAMENTO COM NEGÓCIO (peso 15%)
- **Orientação por valor**: O produto mais completo/valioso foi apresentado como opção principal? A comunicação destacou BENEFÍCIOS (segurança, tranquilidade, praticidade)? Considere o contexto — se o cliente pediu explicitamente a opção mais barata ou fez objeção de preço, atendê-lo é a resposta correta, não uma falha.
- Hierarquia de produtos como guia (não como regra absoluta): moto→PGS tende a vir primeiro; carro→Híbrido tende a vir primeiro. Mas adaptar ao cliente é mais importante que seguir hierarquia cegamente.
- Nunca afirmar "seguro" — é rastreamento com garantia de reembolso
- Informações de preço/contrato conferem com tabela de referência?
- Preço é informação legítima e pode ser argumento válido ("por apenas R$X/mês"), mas a venda se constrói sobre valor percebido.
Score 10 = venda consultiva orientada a valor, adaptada ao cliente. Score 0 = viola regras de negócio críticas (dados errados, afirma seguro).

## CÁLCULO DO SCORE FINAL
overall_score = (D1 × 0.30) + (D2 × 0.20) + (D3 × 0.20) + (D4 × 0.15) + (D5 × 0.15)

## PENALIZAÇÕES — FORMATO ESTRUTURADO
Registre CADA penalização detectada com tipo e severidade padronizados:

| Tipo | Severidade | Quando aplicar |
|------|-----------|----------------|
| hallucination | 3 | Preço/prazo/funcionalidade inventada sem respaldo no plano |
| prohibited_violation | 2 | Qualquer regra [PROIBIDO] violada |
| excessive_length | 1 | 5+ mensagens ou parágrafos extensos sem justificativa |
| context_reaffirmation | 1 | Reafirmar contexto já conhecido pelo cliente |
| lack_of_proactivity | 1 | Resposta sem ação concreta de avanço |

## FORMATO DE SAÍDA — JSON OBRIGATÓRIO (sem markdown, sem texto extra)
{
    "dimensions": {
        "factual_accuracy": {
            "score": <0-10>,
            "reasoning": "<análise breve de cada claim>",
            "verified_claims": ["<claim com respaldo>"],
            "invented_claims": ["<ALUCINAÇÃO — dado inventado>"]
        },
        "structural_compliance": {
            "score": <0-10>,
            "reasoning": "<análise da estrutura>",
            "issues": ["<problema>"]
        },
        "tone_style": {
            "score": <0-10>,
            "reasoning": "<análise do tom>",
            "issues": ["<problema>"]
        },
        "rule_adherence": {
            "score": <0-10>,
            "reasoning": "<regras violadas/cumpridas>",
            "violations": ["<regra violada>"]
        },
        "business_alignment": {
            "score": <0-10>,
            "reasoning": "<análise de negócio>",
            "violations": ["<regra de negócio violada>"]
        }
    },
    "overall_score": <0.0-10.0>,
    "penalties_applied": [{"type": "<tipo>", "severity": <1-3>, "description": "<motivo breve>"}],
    "hallucinations": ["<dado inventado>"],
    "suggestions": ["<melhoria concreta e acionável>"]
}"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PUBLIC API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_DISC_WEIGHTS = {
    'factual_accuracy': 0.30,
    'structural_compliance': 0.20,
    'tone_style': 0.20,
    'rule_adherence': 0.15,
    'business_alignment': 0.15,
}


def _build_scenario_lens_section(scenario_lens: dict | None) -> str:
    """Build the scenario-specific lens section for the discriminator prompt."""
    if not scenario_lens or not isinstance(scenario_lens, dict):
        return ""
    checkpoints = scenario_lens.get("critical_checkpoints", [])
    if not checkpoints:
        return ""
    return f"""
═══════════════════════════════════════
LENTE DE CENÁRIO — CHECKPOINTS CRÍTICOS (CommunicationAgent)
═══════════════════════════════════════
Os seguintes checkpoints são ESPECÍFICOS deste cenário de teste.
Avalie cada um e inclua no reasoning se foram atendidos ou violados.
Falha em checkpoint crítico deve impactar o overall_score proporcionalmente.

{chr(10).join(f'  ✓ {cp}' for cp in checkpoints)}
"""


def _build_user_prompt(
    bot_response: list,
    conversation_state: dict,
    history: list,
    scenario_lens: dict = None,
) -> str:
    """Build the user prompt for discriminator evaluation (extracted for reuse by canary checks)."""
    strategic_plan = conversation_state.get('strategic_plan', {})
    disclosure_checklist = conversation_state.get('disclosure_checklist', [])

    recent_history = history[-12:] if len(history) > 12 else history
    history_str = "\n".join([
        f"{'[BOT]' if m.get('status') == 'sent' else '[CLIENTE]'}: {m.get('text', '')}"
        for m in recent_history
    ])

    return f"""Avalie a resposta do bot usando a rubrica de 5 dimensões com pesos.

═══════════════════════════════════════
RESPOSTA DO BOT PARA AVALIAÇÃO
═══════════════════════════════════════
{json.dumps(bot_response, ensure_ascii=False, indent=2)}

═══════════════════════════════════════
PLANO ESTRATÉGICO (fonte de verdade factual primária)
═══════════════════════════════════════
{json.dumps(strategic_plan, ensure_ascii=False, indent=2) if strategic_plan else "⚠ NENHUM PLANO — qualquer dado factual na resposta é potencial alucinação."}

═══════════════════════════════════════
DISCLOSURE CHECKLIST (estado atual)
═══════════════════════════════════════
{json.dumps(disclosure_checklist, ensure_ascii=False, indent=2) if disclosure_checklist else "Vazio."}

═══════════════════════════════════════
HISTÓRICO DA CONVERSA
═══════════════════════════════════════
{history_str if history_str else "Sem histórico."}

═══════════════════════════════════════
ESTADO DA CONVERSA
═══════════════════════════════════════
operational_context: {conversation_state.get('operational_context', 'N/A')}
identified_topic: {conversation_state.get('identified_topic', 'N/A')}
is_sales_final_step: {conversation_state.get('is_sales_final_step', False)}
is_plan_acceptable: {conversation_state.get('is_plan_acceptable', False)}
products_discussed: {json.dumps(conversation_state.get('products_discussed', []), ensure_ascii=False)}
entities_extracted: {json.dumps(conversation_state.get('entities_extracted', []), ensure_ascii=False)}
unresolved_objections: {json.dumps(conversation_state.get('unresolved_objections', []), ensure_ascii=False)}
last_turn_recap: {json.dumps(conversation_state.get('last_turn_recap'), ensure_ascii=False, default=str) if conversation_state.get('last_turn_recap') else 'N/A'}
turn: {conversation_state.get('metadata', {}).get('current_turn_number', 'N/A') if isinstance(conversation_state.get('metadata'), dict) else 'N/A'}
recently_sent_catalogs: {json.dumps(conversation_state.get('recently_sent_catalogs', []), ensure_ascii=False)}

═══════════════════════════════════════
REGRAS DO AGENTE (pré-extraídas — NÃO extraia novamente)
═══════════════════════════════════════
[OBRIGATÓRIO]
{chr(10).join(f"  • {r}" for r in _RULES_REGISTRY['mandatory'])}

[PROIBIDO]
{chr(10).join(f"  • {r}" for r in _RULES_REGISTRY['prohibited'])}

[CONDICIONAL]
{chr(10).join(f"  • {r}" for r in _RULES_REGISTRY['conditional'])}

[PREFERÊNCIA]
{chr(10).join(f"  • {r}" for r in _RULES_REGISTRY['preferences'])}

═══════════════════════════════════════
TABELA DE PREÇOS (referência factual)
═══════════════════════════════════════
{_PRICING_REFERENCE}

═══════════════════════════════════════
REGRAS DE NEGÓCIO (resumo)
═══════════════════════════════════════
{_BUSINESS_RULES_SUMMARY if _BUSINESS_RULES_SUMMARY else "N/A"}
{_build_scenario_lens_section(scenario_lens)}
═══════════════════════════════════════
AVALIE E RETORNE JSON
═══════════════════════════════════════"""


def analyze_response(
    bot_response: list,
    conversation_state: dict,
    history: list,
    model: str = None,
    scenario_lens: dict = None,
) -> dict:
    """
    Multi-model consensus evaluation of a bot response.

    Uses 2+ cross-provider LLMs (median aggregation) to eliminate single-model
    bias. Falls back to single model if explicitly specified via `model` param.

    Args:
        bot_response: List of message strings from the bot
        conversation_state: Current ConversationState as dict
        history: List of message dicts (full conversation history)
        model: If set, uses only this single model (bypasses consensus)
        scenario_lens: Optional scenario-specific checkpoints dict

    Returns:
        Rich analysis dict with per-dimension scores, penalties, and suggestions.
        Includes _meta with agreement metrics when using multi-model consensus.
    """
    user_prompt = _build_user_prompt(bot_response, conversation_state, history, scenario_lens)
    models = [model] if model else None  # None → multi-model consensus

    try:
        result = multi_model_evaluate(
            system_prompt=DISCRIMINATOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            models=models,
            weights=_DISC_WEIGHTS,
        )

        # Backward compat: dimensions → stages, suggestions → gaps
        result.setdefault('stages', result.get('dimensions', {}))
        result.setdefault('gaps', result.get('suggestions', []))

        if result.get('overall_score') == 'PARSE_ERROR':
            result.update({
                'dimensions': {}, 'stages': {}, 'gaps': [],
                'hallucinations': [], 'suggestions': [],
            })

        return result

    except Exception as e:
        logger.error(f"Discriminator analysis failed: {e}", exc_info=True)
        return {
            'overall_score': 'ERROR', 'error': str(e),
            'dimensions': {}, 'stages': {}, 'gaps': [],
            'hallucinations': [], 'suggestions': [],
        }


def run_canary_check(models: list[str] = None) -> dict:
    """Validate evaluator sanity with known-good and known-bad canary responses.

    Calls the discriminator on a response that should score high (~8+) and one
    that should score low (~2). If scores are out of expected range or ordering
    is wrong, the evaluator is flagged as unreliable.

    Args:
        models: Optional model list override (defaults to DEFAULT_EVAL_MODELS).

    Returns:
        {"passed": bool, "good_score": float, "bad_score": float, "issues": [...]}
    """
    from dev_chat.eval_utils import (
        CANARY_STATE, CANARY_HISTORY,
        CANARY_GOOD_RESPONSE, CANARY_BAD_RESPONSE,
        validate_canary_scores,
    )

    good_prompt = _build_user_prompt(CANARY_GOOD_RESPONSE, CANARY_STATE, CANARY_HISTORY)
    bad_prompt = _build_user_prompt(CANARY_BAD_RESPONSE, CANARY_STATE, CANARY_HISTORY)

    good_result = multi_model_evaluate(
        DISCRIMINATOR_SYSTEM_PROMPT, good_prompt, models=models, weights=_DISC_WEIGHTS,
    )
    bad_result = multi_model_evaluate(
        DISCRIMINATOR_SYSTEM_PROMPT, bad_prompt, models=models, weights=_DISC_WEIGHTS,
    )

    return validate_canary_scores(
        good_result.get('overall_score'),
        bad_result.get('overall_score'),
    )
