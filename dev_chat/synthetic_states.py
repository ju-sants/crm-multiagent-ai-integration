"""
Synthetic State Factory — Pre-built conversation states for automated benchmarking.

Each scenario provides a fully populated ConversationState + Redis context
(profile, history, messages) so benchmarks can run without a real conversation.
"""

import json
import uuid
from datetime import datetime, timezone
import os

from app.models.data_models import (
    ConversationState, StateMetadata, EntityItem, ProductItem,
    ChecklistItem, QualificationItem, TurnRecap, ObjectionItem,
    ConversationGoal,
)
from app.services.redis_service import get_redis
from app.core.logger import get_logger

logger = get_logger(__name__)
redis_client = get_redis()

_SCENARIOS_DIR = os.path.join(os.path.dirname(__file__), "scenarios")


def load_scenario_evaluation_focus(scenario_name: str) -> dict | None:
    """Load evaluation_focus from the scenario JSON file linked to a synthetic state."""
    scenario = SYNTHETIC_SCENARIOS.get(scenario_name)
    if not scenario:
        return None
    filename = scenario.get("scenario_file")
    if not filename:
        return None
    filepath = os.path.join(_SCENARIOS_DIR, filename)
    if not os.path.isfile(filepath):
        logger.warning(f"Scenario file not found: {filepath}")
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("evaluation_focus")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SCENARIO DEFINITIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SYNTHETIC_SCENARIOS = {

    # ── 1. First contact — no context yet ──
    "first_contact": {
        "description": "Brand new contact, first message 'oi'. No state, no plan, no history.",
        "agent_focus": ["RoutingAgent", "StrategicAdvisor"],
        "scenario_file": "edge_saudacao_ambigua.json",
        "state": ConversationState(
            metadata=StateMetadata(
                contact_id="synth-first-contact",
                current_turn_number=1,
                contact_name="Carlos Silva",
                phone_number="+5511999990001",
            ),
        ),
        "profile": None,
        "shorterm_history": None,
        "longterm_history": {},
        "waiting_messages": ["oi"],
        "recent_catalogs": [],
        "system_op_output": None,
    },

    # ── 2. Motorcycle sales — mid-funnel, plan exists, qualifying ──
    "moto_mid_funnel": {
        "description": "Client interested in motorcycle tracking. Turn 3, has plan, needs qualification.",
        "agent_focus": ["CommunicationAgent", "IncrementalStrategicPlannerAgent"],
        "scenario_file": "basic_sales_moto.json",
        "state": ConversationState(
            metadata=StateMetadata(
                contact_id="synth-moto-mid",
                current_turn_number=3,
                contact_name="João Ferreira",
                phone_number="+5521988880002",
            ),
            identified_topic="BUDGET",
            operational_context="BUDGET",
            is_plan_acceptable=True,
            entities_extracted=[
                EntityItem(entity="vehicle_type", value="moto"),
                EntityItem(entity="brand", value="Honda"),
                EntityItem(entity="model_hint", value="CG 160"),
            ],
            products_discussed=[
                ProductItem(plan_name="Plano Rastreamento Moto Básico", details_provided=["pricing"]),
            ],
            strategic_plan={
                "conversation_blueprint": {
                    "customer_context_summary": {
                        "relevant_profile_insights": "Motociclista urbano, preocupado com segurança.",
                        "insights_from_current_session": "Interessado em rastreamento para Honda CG 160. Demonstrou interesse em preço.",
                    },
                    "product_presentation_strategy": {
                        "presentation_order": ["Plano Rastreamento + Proteção Total PGS", "Plano Rastreamento Moto Básico"],
                        "primary_offer": "Plano Rastreamento + Proteção Total PGS",
                        "secondary_offer": "Plano Rastreamento Moto Básico",
                    },
                    "communication_guidance": {
                        "tone_and_style": "Entusiasta mas informativo. Destacar proteção FIPE como diferencial.",
                        "key_talking_points": [
                            "Apresentar o PGS como proteção completa — se não recuperar, recebe valor FIPE.",
                            "Moto reserva disponível durante busca.",
                            "Adesão R$ 120, mensalidade a partir de R$ 77/mês.",
                            "Perguntar faixa de valor FIPE da moto para definir mensalidade exata.",
                        ],
                        "key_questions_to_ask": [
                            "Qual o valor aproximado da sua CG 160 na tabela FIPE?",
                        ],
                        "next_step_preview": "Após saber faixa FIPE, apresentar valor exato e fechar.",
                    },
                    "information_payload": {
                        "Plano Rastreamento + Proteção Total PGS": {
                            "adesao": 120.00,
                            "faixas": [
                                {"fipe_range": "Até R$ 15.000", "valor": 77.00},
                                {"fipe_range": "R$ 16.000 a R$ 22.000", "valor": 85.00},
                                {"fipe_range": "R$ 23.000 a R$ 30.000", "valor": 110.00},
                            ],
                            "moto_reserva": True,
                            "reembolso_fipe": True,
                        },
                        "Plano Rastreamento Moto Básico": {
                            "adesao": 120.00,
                            "mensalidade": 60.00,
                        },
                    },
                },
            },
            disclosure_checklist=[
                ChecklistItem(topic="pricing_pgs", content="Faixas de preço PGS por FIPE", status="pending"),
                ChecklistItem(topic="pricing_basic", content="Preço plano básico R$60/mês", status="disclosed"),
                ChecklistItem(topic="adhesion", content="Adesão R$120", status="disclosed"),
                ChecklistItem(topic="fipe_reimbursement", content="Reembolso FIPE em caso de não recuperação", status="pending"),
                ChecklistItem(topic="moto_reserva", content="Moto reserva durante busca", status="pending"),
            ],
            qualification_tracker=[
                QualificationItem(topic="vehicle_type", status="collected", value="moto", turn_collected=1),
                QualificationItem(topic="brand", status="collected", value="Honda", turn_collected=2),
                QualificationItem(topic="fipe_value", status="pending", value=None, turn_collected=None),
            ],
            last_turn_recap=TurnRecap(
                turn_number=2,
                user_intent="Pediu preço do rastreador para moto",
                agent_action="Apresentou plano básico R$60/mês e mencionou PGS",
                key_info_exchanged=["preço básico", "existência do PGS"],
            ),
        ),
        "profile": json.dumps({
            "client_identity": {"name": "João Ferreira", "vehicle": "Honda CG 160 2023"},
            "clients_mindset": {"primary_concern": "segurança", "price_sensitivity": "média"},
        }),
        "shorterm_history": "Turn 1: Cliente disse 'oi, quero rastreador pra moto'. Bot acolheu e perguntou qual moto.\nTurn 2: Cliente disse 'Honda CG 160'. Bot apresentou plano básico R$60.",
        "longterm_history": {"topic_details": []},
        "waiting_messages": ["quanto custa o plano com proteção?"],
        "recent_catalogs": [],
        "system_op_output": None,
    },

    # ── 3. Car sales — price objection, closing phase ──
    "car_objection_closing": {
        "description": "Client wants car tracker but objects to price. Turn 5, near closing.",
        "agent_focus": ["CommunicationAgent", "IncrementalStrategicPlannerAgent"],
        "scenario_file": "sales_objecao_preco.json",
        "state": ConversationState(
            metadata=StateMetadata(
                contact_id="synth-car-objection",
                current_turn_number=5,
                contact_name="Maria Santos",
                phone_number="+5531977770003",
            ),
            identified_topic="BUDGET",
            operational_context="BUDGET",
            is_plan_acceptable=True,
            entities_extracted=[
                EntityItem(entity="vehicle_type", value="carro"),
                EntityItem(entity="brand", value="Fiat"),
                EntityItem(entity="model_hint", value="Argo"),
                EntityItem(entity="usage", value="urbano"),
            ],
            products_discussed=[
                ProductItem(plan_name="Rastreador Híbrido SATELITAL", details_provided=["pricing", "features"]),
                ProductItem(plan_name="Rastreador GSM 4G", details_provided=["pricing"]),
            ],
            strategic_plan={
                "conversation_blueprint": {
                    "customer_context_summary": {
                        "relevant_profile_insights": "Dona de Fiat Argo, uso urbano. Sensível a preço.",
                        "insights_from_current_session": "Interessada mas achou Híbrido caro. Precisa de argumento de valor.",
                    },
                    "product_presentation_strategy": {
                        "presentation_order": ["Rastreador Híbrido SATELITAL", "Rastreador GSM 4G"],
                        "primary_offer": "Rastreador GSM 4G",
                        "secondary_offer": "Rastreador Híbrido SATELITAL",
                    },
                    "communication_guidance": {
                        "tone_and_style": "Empático e consultivo. Validar objeção, reposicionar valor.",
                        "key_talking_points": [
                            "GSM 4G: adesão R$200, mensalidade R$65-75/mês — melhor custo-benefício urbano.",
                            "Atualização a cada 30 segundos em movimento.",
                            "Bloqueio remoto opcional (+R$10).",
                            "Contrato 24 meses, sem multa de cancelamento, apenas desinstalação.",
                        ],
                        "key_questions_to_ask": [
                            "Prefere com ou sem bloqueio remoto?",
                        ],
                        "next_step_preview": "Fechar no GSM 4G e iniciar coleta de dados.",
                    },
                    "information_payload": {
                        "Rastreador GSM 4G": {
                            "adesao": 200.00,
                            "mensalidade_sem_bloqueio": 65.00,
                            "mensalidade_com_bloqueio": 75.00,
                            "contrato": "24 meses",
                        },
                    },
                },
            },
            disclosure_checklist=[
                ChecklistItem(topic="gsm_pricing", content="GSM 4G: R$65-75/mês", status="disclosed"),
                ChecklistItem(topic="hybrid_pricing", content="Híbrido: R$180-200/mês", status="disclosed"),
                ChecklistItem(topic="bloqueio", content="Bloqueio remoto opcional", status="pending"),
                ChecklistItem(topic="contrato", content="24 meses sem multa", status="pending"),
            ],
            unresolved_objections=[
                ObjectionItem(objection="Achei caro o plano híbrido", status="acknowledged", turn_raised=4),
            ],
            last_turn_recap=TurnRecap(
                turn_number=4,
                user_intent="Disse que achou o híbrido caro",
                agent_action="Reposicionou para GSM 4G como alternativa",
                key_info_exchanged=["objeção de preço", "GSM como alternativa"],
            ),
        ),
        "profile": json.dumps({
            "client_identity": {"name": "Maria Santos", "vehicle": "Fiat Argo 2024"},
            "clients_mindset": {"primary_concern": "custo-benefício", "price_sensitivity": "alta"},
        }),
        "shorterm_history": "Turn 1-3: Cliente perguntou sobre rastreador pra carro. Bot apresentou Híbrido primeiro.\nTurn 4: Cliente disse 'achei caro'. Bot ofereceu GSM 4G.",
        "longterm_history": {"topic_details": []},
        "waiting_messages": ["e esse de 65 reais, faz o que exatamente?"],
        "recent_catalogs": ["Rastreador Híbrido SATELITAL"],
        "system_op_output": None,
    },

    # ── 4. Support scenario — vehicle offline ──
    "support_vehicle_offline": {
        "description": "Existing client, vehicle not updating. Support flow turn 2.",
        "agent_focus": ["RoutingAgent", "CommunicationAgent", "StrategicAdvisor"],
        "scenario_file": "support_veiculo_parado.json",
        "state": ConversationState(
            metadata=StateMetadata(
                contact_id="synth-support-offline",
                current_turn_number=2,
                contact_name="Pedro Almeida",
                phone_number="+5585966660004",
            ),
            identified_topic="SUPPORT",
            operational_context="SUPPORT",
            entities_extracted=[
                EntityItem(entity="vehicle_type", value="carro"),
                EntityItem(entity="issue_type", value="sem atualização"),
                EntityItem(entity="plate", value="ABC1D23"),
            ],
            last_turn_recap=TurnRecap(
                turn_number=1,
                user_intent="Veículo não atualiza há 2 dias",
                agent_action="Coletou placa e iniciou diagnóstico",
                key_info_exchanged=["placa ABC1D23", "sem atualização 2 dias"],
            ),
        ),
        "profile": json.dumps({
            "client_identity": {"name": "Pedro Almeida", "is_existing_client": True},
            "current_mission": {"intent": "suporte técnico", "issue": "veículo sem atualização"},
        }),
        "shorterm_history": "Turn 1: Cliente disse 'meu rastreador não atualiza faz 2 dias, placa ABC1D23'. Bot confirmou placa e disse que vai verificar.",
        "longterm_history": {"topic_details": [
            {"title": "Contratação GSM 4G", "summary": "Cliente contratou GSM 4G há 6 meses."},
        ]},
        "waiting_messages": ["e aí, conseguiram ver?"],
        "recent_catalogs": [],
        "system_op_output": json.dumps({
            "status": "completed",
            "synthesis": "Veículo ABC1D23 última atualização há 48h. Bateria do rastreador em 15%. Provável descarregamento.",
            "data_payload": {"last_update": "2026-03-06T10:00:00Z", "battery": "15%"},
        }),
    },

    # ── 5. Fleet inquiry — B2B, complex needs ──
    "fleet_b2b": {
        "description": "Company manager asking about fleet plans. Turn 2, needs consultative approach.",
        "agent_focus": ["StrategicAdvisor", "CommunicationAgent"],
        "scenario_file": "strategy_fleet_b2b.json",
        "state": ConversationState(
            metadata=StateMetadata(
                contact_id="synth-fleet-b2b",
                current_turn_number=2,
                contact_name="Roberto Mendes",
                phone_number="+5562955550005",
            ),
            identified_topic="BUDGET",
            operational_context="BUDGET",
            entities_extracted=[
                EntityItem(entity="vehicle_type", value="frota"),
                EntityItem(entity="fleet_size", value="25 veículos"),
                EntityItem(entity="vehicle_types_in_fleet", value="caminhões e vans"),
            ],
            qualification_tracker=[
                QualificationItem(topic="fleet_size", status="collected", value="25", turn_collected=1),
                QualificationItem(topic="vehicle_types", status="collected", value="caminhões e vans", turn_collected=1),
                QualificationItem(topic="current_tracking", status="pending", value=None, turn_collected=None),
                QualificationItem(topic="operation_area", status="pending", value=None, turn_collected=None),
            ],
        ),
        "profile": json.dumps({
            "client_identity": {"name": "Roberto Mendes", "company": "TransMendes Logística"},
            "clients_mindset": {"primary_concern": "gestão de frota", "decision_maker": True},
        }),
        "shorterm_history": "Turn 1: Cliente disse 'preciso de rastreamento pra 25 caminhões e vans da minha transportadora'. Bot acolheu e perguntou sobre área de operação.",
        "longterm_history": {"topic_details": []},
        "waiting_messages": ["rodamos mais interior de Goiás e Mato Grosso, algumas áreas não pega celular"],
        "recent_catalogs": [],
        "system_op_output": None,
    },

    # ── 6. Regional restriction — PGS in DDD 66 ──
    "regional_ddd66": {
        "description": "Client in Mato Grosso (DDD 66) requesting PGS — must be denied. Tests regional restriction compliance.",
        "agent_focus": ["StrategicAdvisor", "CommunicationAgent", "RoutingAgent"],
        "scenario_file": "strategy_regional_restriction.json",
        "state": ConversationState(
            metadata=StateMetadata(
                contact_id="synth-regional-ddd66",
                current_turn_number=3,
                contact_name="Gustavo Pereira",
                phone_number="+5566999990006",
            ),
            identified_topic="BUDGET",
            operational_context="BUDGET",
            is_plan_acceptable=True,
            entities_extracted=[
                EntityItem(entity="vehicle_type", value="moto"),
                EntityItem(entity="brand", value="Honda"),
                EntityItem(entity="model_hint", value="Bros 160"),
                EntityItem(entity="city", value="Sorriso"),
                EntityItem(entity="state", value="MT"),
            ],
            qualification_tracker=[
                QualificationItem(topic="vehicle_type", status="collected", value="moto", turn_collected=1),
                QualificationItem(topic="city", status="collected", value="Sorriso-MT (DDD 66)", turn_collected=2),
            ],
        ),
        "profile": json.dumps({
            "client_identity": {"name": "Gustavo Pereira", "vehicle": "Honda Bros 160"},
            "clients_mindset": {"primary_concern": "proteção total", "price_sensitivity": "baixa"},
        }),
        "shorterm_history": "Turn 1: Cliente disse 'quero o plano mais completo pra minha moto'. Bot perguntou qual moto e cidade.\nTurn 2: Cliente disse 'Honda Bros 160, moro em Sorriso-MT'.",
        "longterm_history": {"topic_details": []},
        "waiting_messages": ["quero aquele plano com reembolso da fipe, o PGS"],
        "recent_catalogs": [],
        "system_op_output": None,
    },

    # ── 7. Cascade objections — robbed client ──
    "cascade_objections": {
        "description": "Client who was previously robbed, multiple price objections. High emotional stress test.",
        "agent_focus": ["CommunicationAgent", "StrategicAdvisor", "IncrementalStrategicPlannerAgent"],
        "scenario_file": "comm_multi_objection.json",
        "state": ConversationState(
            metadata=StateMetadata(
                contact_id="synth-cascade-objections",
                current_turn_number=4,
                contact_name="Patrícia Alves",
                phone_number="+5511988880007",
            ),
            identified_topic="BUDGET",
            operational_context="BUDGET",
            is_plan_acceptable=True,
            entities_extracted=[
                EntityItem(entity="vehicle_type", value="moto"),
                EntityItem(entity="brand", value="Honda"),
                EntityItem(entity="model_hint", value="CB 300"),
                EntityItem(entity="previous_theft", value="sim"),
            ],
            products_discussed=[
                ProductItem(plan_name="Plano Rastreamento + Proteção Total PGS", details_provided=["pricing", "features"]),
            ],
            unresolved_objections=[
                ObjectionItem(objection="Adesão R$120 cara, outro lugar cobra R$80", status="raised", turn_raised=3),
            ],
            strategic_plan={
                "conversation_blueprint": {
                    "customer_context_summary": {
                        "relevant_profile_insights": "Já teve moto roubada antes. Desconfiada de rastreadores. Alta sensibilidade emocional.",
                        "insights_from_current_session": "Comprou nova CB 300 e quer proteger. Já teve experiência negativa com concorrente.",
                    },
                    "product_presentation_strategy": {
                        "primary_offer": "Plano Rastreamento + Proteção Total PGS",
                        "secondary_offer": "Plano Rastreamento Moto Básico",
                    },
                    "communication_guidance": {
                        "tone_and_style": "Empático profundo. Perfil 'Já teve o bem roubado'. Validar frustração antes de vender.",
                        "key_talking_points": [
                            "100% taxa de recuperação PGS — diferencial real.",
                            "PGS reembolsa FIPE se não recuperar.",
                            "Moto reserva durante busca.",
                            "Plantão 24h dedicado.",
                        ],
                    },
                    "information_payload": {
                        "Plano Rastreamento + Proteção Total PGS": {
                            "adesao": 120.00,
                            "faixas": [
                                {"fipe_range": "Até R$ 15.000", "valor": 77.00},
                                {"fipe_range": "R$ 16.000 a R$ 22.000", "valor": 85.00},
                                {"fipe_range": "R$ 23.000 a R$ 30.000", "valor": 110.00},
                            ],
                        },
                    },
                },
            },
            last_turn_recap=TurnRecap(
                turn_number=3,
                user_intent="Reclamou que adesão é cara comparando com concorrência",
                agent_action="Validou objeção e destacou diferenciais do PGS",
                key_info_exchanged=["objeção de preço", "comparação concorrência"],
            ),
        ),
        "profile": json.dumps({
            "client_identity": {"name": "Patrícia Alves", "vehicle": "Honda CB 300"},
            "clients_mindset": {"primary_concern": "não ser roubada de novo", "price_sensitivity": "alta", "previous_theft": True},
        }),
        "shorterm_history": "Turn 1: 'já tive moto roubada antes, to de saco cheio'. Turn 2: 'comprei uma CB 300 nova'. Turn 3: 'R$120 de adesão? tá caro, outro lugar cobra R$80'.",
        "longterm_history": {"topic_details": []},
        "waiting_messages": ["e como eu sei que vocês vão recuperar? a outra empresa disse o mesmo"],
        "recent_catalogs": [],
        "system_op_output": None,
    },

    # ── 8. Theft + inadimplência — critical edge case ──
    "theft_inadimplencia": {
        "description": "PGS client with possible late payment and stolen motorcycle. Critical urgency + coverage rules.",
        "agent_focus": ["RoutingAgent", "CommunicationAgent", "SystemOperationsAgent", "StrategicAdvisor"],
        "scenario_file": "edge_theft_inadimplencia.json",
        "state": ConversationState(
            metadata=StateMetadata(
                contact_id="synth-theft-inadimplencia",
                current_turn_number=2,
                contact_name="Diego Santana",
                phone_number="+5571977770008",
            ),
            identified_topic="SUPPORT",
            operational_context="SUPPORT",
            entities_extracted=[
                EntityItem(entity="vehicle_type", value="moto"),
                EntityItem(entity="issue_type", value="roubo"),
                EntityItem(entity="plate", value="KLM3N45"),
                EntityItem(entity="plan_type", value="PGS"),
            ],
            last_turn_recap=TurnRecap(
                turn_number=1,
                user_intent="Moto roubada agora, tem PGS",
                agent_action="Coletou placa e plano, iniciando verificação",
                key_info_exchanged=["placa KLM3N45", "plano PGS", "roubo recente"],
            ),
        ),
        "profile": json.dumps({
            "client_identity": {"name": "Diego Santana", "is_existing_client": True},
            "current_mission": {"intent": "emergência roubo", "plan": "PGS"},
        }),
        "shorterm_history": "Turn 1: 'ROUBARAM MINHA MOTO AGORA, tenho PGS, placa KLM3N45'. Bot coletou dados e disse que vai verificar.",
        "longterm_history": {"topic_details": [
            {"title": "Contratação PGS", "summary": "Cliente contratou PGS há 4 meses para Honda CG 160."},
        ]},
        "waiting_messages": ["tô com a mensalidade atrasada, isso afeta alguma coisa?"],
        "recent_catalogs": [],
        "system_op_output": json.dumps({
            "status": "completed",
            "synthesis": "Veículo KLM3N45 — plano PGS ativo. Última posição: Av. Paralela, Salvador-BA. Último sinal há 45 min.",
            "data_payload": {"last_update": "2026-03-11T13:15:00Z", "plan": "PGS", "status": "active"},
        }),
    },

    # ── 9. Personal mobility — patinete + bike elétrica ──
    "personal_mobility": {
        "description": "Family scenario: parent wanting tracking for kid's scooter and electric bike. Niche product test.",
        "agent_focus": ["StrategicAdvisor", "CommunicationAgent", "RoutingAgent"],
        "scenario_file": "strategy_personal_mobility.json",
        "state": ConversationState(
            metadata=StateMetadata(
                contact_id="synth-personal-mobility",
                current_turn_number=2,
                contact_name="Camila Duarte",
                phone_number="+5511955550009",
            ),
            identified_topic="BUDGET",
            operational_context="BUDGET",
            entities_extracted=[
                EntityItem(entity="vehicle_type", value="patinete elétrico"),
                EntityItem(entity="brand", value="Xiaomi"),
                EntityItem(entity="usage", value="ir à escola"),
            ],
            qualification_tracker=[
                QualificationItem(topic="vehicle_type", status="collected", value="patinete elétrico", turn_collected=1),
                QualificationItem(topic="purpose", status="collected", value="monitoramento filho", turn_collected=1),
            ],
        ),
        "profile": json.dumps({
            "client_identity": {"name": "Camila Duarte"},
            "clients_mindset": {"primary_concern": "segurança do filho", "price_sensitivity": "baixa"},
        }),
        "shorterm_history": "Turn 1: 'vocês fazem rastreamento de patinete elétrico? é um xiaomi, meu filho de 14 anos usa pra ir na escola'.",
        "longterm_history": {"topic_details": []},
        "waiting_messages": ["ele também tem uma bike elétrica, dá pra rastrear as duas?"],
        "recent_catalogs": [],
        "system_op_output": None,
    },

    # ── 10. Farm WiFi + John Deere compatibility ──
    "farm_wifi_deere": {
        "description": "Farm scenario with Starlink WiFi and John Deere autopilot compatibility concern.",
        "agent_focus": ["StrategicAdvisor", "CommunicationAgent", "IncrementalStrategicPlannerAgent"],
        "scenario_file": "farm_wifi_compatibility.json",
        "state": ConversationState(
            metadata=StateMetadata(
                contact_id="synth-farm-wifi",
                current_turn_number=3,
                contact_name="Sebastião Borges",
                phone_number="+5577944440010",
            ),
            identified_topic="BUDGET",
            operational_context="BUDGET",
            is_plan_acceptable=True,
            entities_extracted=[
                EntityItem(entity="vehicle_type", value="máquinas agrícolas"),
                EntityItem(entity="brand", value="John Deere"),
                EntityItem(entity="fleet_size", value="5"),
                EntityItem(entity="city", value="Luís Eduardo Magalhães"),
                EntityItem(entity="connectivity", value="sem sinal celular, tem Starlink"),
            ],
            qualification_tracker=[
                QualificationItem(topic="vehicle_type", status="collected", value="colheitadeiras + tratores", turn_collected=1),
                QualificationItem(topic="connectivity", status="collected", value="sem sinal celular, Starlink na fazenda", turn_collected=2),
                QualificationItem(topic="autopilot", status="pending", value=None, turn_collected=None),
            ],
            strategic_plan={
                "conversation_blueprint": {
                    "customer_context_summary": {
                        "relevant_profile_insights": "Produtor rural em LEM-BA. Fazenda sem sinal celular mas com Starlink.",
                    },
                    "product_presentation_strategy": {
                        "primary_offer": "Rastreador GSM (2G+3G+4G) + WI-FI",
                        "secondary_offer": "Rastreador GSM 4G",
                    },
                    "communication_guidance": {
                        "key_talking_points": [
                            "GSM+WiFi ideal para fazendas com internet local (Starlink).",
                            "Inclui 2 roteadores pré-configurados.",
                            "Armazena até 3 meses de dados offline.",
                        ],
                    },
                    "information_payload": {
                        "Rastreador GSM (2G+3G+4G) + WI-FI": {
                            "adesao": 300.00,
                            "mensalidade_sem_bloqueio": 75.00,
                            "mensalidade_com_bloqueio": 85.00,
                        },
                    },
                },
            },
        ),
        "profile": json.dumps({
            "client_identity": {"name": "Sebastião Borges", "type": "produtor rural"},
            "clients_mindset": {"primary_concern": "monitoramento de maquinário", "tech_savvy": False},
        }),
        "shorterm_history": "Turn 1: 'preciso rastrear máquinas da fazenda, 3 John Deere e 2 Case'. Turn 2: 'aqui em LEM, na fazenda não pega celular, mas tenho Starlink'.",
        "longterm_history": {"topic_details": []},
        "waiting_messages": ["as john deere usam piloto automático, interfere?"],
        "recent_catalogs": [],
        "system_op_output": None,
    },

    # ── 11. Disclosure compliance — contract terms ──
    "disclosure_contract": {
        "description": "Client closing GSM 4G deal, asking critical contract questions. Tests disclosure checklist progression.",
        "agent_focus": ["CommunicationAgent", "StrategicAdvisor", "IncrementalStrategicPlannerAgent"],
        "scenario_file": "comm_disclosure_compliance.json",
        "state": ConversationState(
            metadata=StateMetadata(
                contact_id="synth-disclosure-contract",
                current_turn_number=4,
                contact_name="Juliana Rodrigues",
                phone_number="+5511933330011",
            ),
            identified_topic="BUDGET",
            operational_context="BUDGET",
            is_plan_acceptable=True,
            is_sales_final_step=False,
            entities_extracted=[
                EntityItem(entity="vehicle_type", value="carro"),
                EntityItem(entity="brand", value="Toyota"),
                EntityItem(entity="model_hint", value="Corolla"),
                EntityItem(entity="bloqueio", value="sim"),
            ],
            products_discussed=[
                ProductItem(plan_name="Rastreador GSM 4G", details_provided=["pricing", "bloqueio"]),
            ],
            disclosure_checklist=[
                ChecklistItem(topic="gsm_pricing", content="GSM 4G com bloqueio: R$75/mês", status="communicated"),
                ChecklistItem(topic="adesao", content="Adesão R$200", status="communicated"),
                ChecklistItem(topic="contrato_vigencia", content="Contrato 24 meses", status="pending"),
                ChecklistItem(topic="cancelamento", content="Sem multa, taxa desinstalação R$200", status="pending"),
                ChecklistItem(topic="comodato", content="Equipamento em comodato", status="pending"),
                ChecklistItem(topic="nao_seguro", content="Serviço de rastreamento, não é seguro", status="pending"),
            ],
            last_turn_recap=TurnRecap(
                turn_number=3,
                user_intent="Confirmou que quer GSM 4G com bloqueio",
                agent_action="Apresentou preço R$75/mês e mencionou próximos passos",
                key_info_exchanged=["preço confirmado", "interesse em fechar"],
            ),
        ),
        "profile": json.dumps({
            "client_identity": {"name": "Juliana Rodrigues", "vehicle": "Toyota Corolla 2023"},
            "clients_mindset": {"primary_concern": "segurança jurídica", "detail_oriented": True},
        }),
        "shorterm_history": "Turn 1-2: Cliente pediu rastreador pro Corolla, Bot apresentou GSM 4G.\nTurn 3: Cliente confirmou que quer com bloqueio, R$75/mês.",
        "longterm_history": {"topic_details": []},
        "waiting_messages": ["e se eu quiser cancelar antes dos 24 meses, pago multa?"],
        "recent_catalogs": [],
        "system_op_output": None,
    },

    # ── 12. Pivot mid-funnel — car to motorcycle ──
    "pivot_car_to_moto": {
        "description": "Client pivots from car tracking to motorcycle mid-conversation. Tests incremental plan refinement.",
        "agent_focus": ["IncrementalStrategicPlannerAgent", "CommunicationAgent", "RoutingAgent"],
        "scenario_file": "refine_pivot_product.json",
        "state": ConversationState(
            metadata=StateMetadata(
                contact_id="synth-pivot-car-moto",
                current_turn_number=3,
                contact_name="Rafael Costa",
                phone_number="+5521966660012",
            ),
            identified_topic="BUDGET",
            operational_context="BUDGET",
            is_plan_acceptable=True,
            entities_extracted=[
                EntityItem(entity="vehicle_type", value="carro"),
                EntityItem(entity="brand", value="VW"),
                EntityItem(entity="model_hint", value="Gol 2022"),
            ],
            products_discussed=[
                ProductItem(plan_name="Rastreador Híbrido SATELITAL", details_provided=["pricing"]),
            ],
            strategic_plan={
                "conversation_blueprint": {
                    "customer_context_summary": {
                        "relevant_profile_insights": "Dono de Gol 2022, uso trabalho.",
                    },
                    "product_presentation_strategy": {
                        "primary_offer": "Rastreador Híbrido SATELITAL",
                        "secondary_offer": "Rastreador GSM 4G",
                    },
                    "communication_guidance": {
                        "key_talking_points": [
                            "Híbrido: cobertura ininterrupta GSM+Satélite.",
                            "Adesão R$400, mensalidade R$180-200.",
                        ],
                    },
                    "information_payload": {
                        "Rastreador Híbrido SATELITAL": {
                            "adesao": 400.00,
                            "mensalidade_sem_bloqueio": 180.00,
                            "mensalidade_com_bloqueio": 200.00,
                        },
                    },
                },
            },
            last_turn_recap=TurnRecap(
                turn_number=2,
                user_intent="Informou que é Gol 2022 pra trabalho",
                agent_action="Apresentou Híbrido como opção premium",
                key_info_exchanged=["Gol 2022", "Híbrido apresentado"],
            ),
        ),
        "profile": json.dumps({
            "client_identity": {"name": "Rafael Costa", "vehicle": "VW Gol 2022"},
            "clients_mindset": {"primary_concern": "segurança", "price_sensitivity": "média"},
        }),
        "shorterm_history": "Turn 1: 'preciso de rastreador pro meu carro'. Turn 2: 'é um Gol 2022, uso pra trabalho'.",
        "longterm_history": {"topic_details": []},
        "waiting_messages": ["na verdade, eu tenho uma pcx 150 também e ela é mais fácil de roubar"],
        "recent_catalogs": [],
        "system_op_output": None,
    },

    # ── 13. Support — GPS impreciso + cross-sell ──
    "support_crosssell": {
        "description": "Existing client with GPS jumping issue. Support evolves into upgrade opportunity.",
        "agent_focus": ["RoutingAgent", "SystemOperationsAgent", "CommunicationAgent", "StrategicAdvisor"],
        "scenario_file": "sysops_vehicle_diagnostic.json",
        "state": ConversationState(
            metadata=StateMetadata(
                contact_id="synth-support-crosssell",
                current_turn_number=2,
                contact_name="Marcos Vieira",
                phone_number="+5531955550013",
            ),
            identified_topic="SUPPORT",
            operational_context="SUPPORT",
            entities_extracted=[
                EntityItem(entity="vehicle_type", value="carro"),
                EntityItem(entity="issue_type", value="GPS impreciso"),
                EntityItem(entity="plate", value="MNO5P67"),
                EntityItem(entity="current_plan", value="GSM 4G"),
            ],
            last_turn_recap=TurnRecap(
                turn_number=1,
                user_intent="Rastreador com localização pulando no mapa",
                agent_action="Coletou placa e tipo de problema",
                key_info_exchanged=["placa MNO5P67", "GPS impreciso", "fusca reformado"],
            ),
        ),
        "profile": json.dumps({
            "client_identity": {"name": "Marcos Vieira", "vehicle": "Fusca reformado", "is_existing_client": True},
            "current_mission": {"intent": "suporte técnico", "issue": "GPS pulando"},
        }),
        "shorterm_history": "Turn 1: 'meu rastreador tá doido, a localização fica pulando no mapa, placa MNO5P67'.",
        "longterm_history": {"topic_details": [
            {"title": "Contratação GSM 4G", "summary": "Cliente contratou GSM 4G há 8 meses."},
        ]},
        "waiting_messages": ["tenho o GSM 4G, ele fica nuns galpões às vezes"],
        "recent_catalogs": [],
        "system_op_output": json.dumps({
            "status": "completed",
            "synthesis": "Veículo MNO5P67 — rastreador GSM 4G funcionando. Últimas atualizações mostram gaps de sinal em zonas industriais. Provável interferência de estruturas metálicas.",
            "data_payload": {"last_update": "2026-03-11T14:30:00Z", "signal_gaps": 12, "plan": "GSM 4G"},
        }),
    },

    # ── 14. Unlisted city — feasibility check ──
    "unlisted_city": {
        "description": "Client from a city not in the service catalog. Tests regional feasibility procedure.",
        "agent_focus": ["StrategicAdvisor", "CommunicationAgent", "RoutingAgent"],
        "scenario_file": "sales_unlisted_city.json",
        "state": ConversationState(
            metadata=StateMetadata(
                contact_id="synth-unlisted-city",
                current_turn_number=3,
                contact_name="Leandro Silva",
                phone_number="+5562944440014",
            ),
            identified_topic="BUDGET",
            operational_context="BUDGET",
            is_plan_acceptable=True,
            entities_extracted=[
                EntityItem(entity="vehicle_type", value="caminhão"),
                EntityItem(entity="brand", value="Iveco"),
                EntityItem(entity="model_hint", value="Daily"),
                EntityItem(entity="city", value="Monte Alegre de Goiás"),
            ],
            qualification_tracker=[
                QualificationItem(topic="vehicle_type", status="collected", value="caminhão", turn_collected=1),
                QualificationItem(topic="city", status="collected", value="Monte Alegre de Goiás", turn_collected=2),
            ],
        ),
        "profile": json.dumps({
            "client_identity": {"name": "Leandro Silva", "vehicle": "Iveco Daily"},
            "clients_mindset": {"primary_concern": "rastreamento para frete"},
        }),
        "shorterm_history": "Turn 1: 'quero rastreador pro caminhão Iveco Daily'. Turn 2: 'moro em Monte Alegre de Goiás, interior de Goiás'.",
        "longterm_history": {"topic_details": []},
        "waiting_messages": ["vocês instalam aqui? ou tem que ir em outra cidade?"],
        "recent_catalogs": [],
        "system_op_output": None,
    },

    # ── 15. Reengagement after inactivity ──
    "reengagement": {
        "description": "Client returns after period of inactivity. Tests memory and follow-up mode.",
        "agent_focus": ["CommunicationAgent", "IncrementalStrategicPlannerAgent", "RoutingAgent"],
        "scenario_file": "comm_followup_reengagement.json",
        "state": ConversationState(
            metadata=StateMetadata(
                contact_id="synth-reengagement",
                current_turn_number=4,
                contact_name="Bruno Nascimento",
                phone_number="+5521933330015",
            ),
            identified_topic="BUDGET",
            operational_context="BUDGET",
            is_plan_acceptable=True,
            entities_extracted=[
                EntityItem(entity="vehicle_type", value="moto"),
                EntityItem(entity="brand", value="Honda"),
                EntityItem(entity="model_hint", value="XRE 300"),
            ],
            products_discussed=[
                ProductItem(plan_name="Plano Rastreamento Moto Básico", details_provided=["pricing"]),
                ProductItem(plan_name="Plano Rastreamento + Proteção Total PGS", details_provided=["mentioned"]),
            ],
            strategic_plan={
                "conversation_blueprint": {
                    "customer_context_summary": {
                        "relevant_profile_insights": "Motociclista, usa XRE 300 para trilha e cidade.",
                    },
                    "product_presentation_strategy": {
                        "primary_offer": "Plano Rastreamento + Proteção Total PGS",
                        "secondary_offer": "Plano Rastreamento Moto Básico",
                    },
                    "communication_guidance": {
                        "key_talking_points": [
                            "PGS: proteção completa com reembolso FIPE.",
                            "Básico R$60/mês já apresentado.",
                        ],
                    },
                    "information_payload": {
                        "Plano Rastreamento + Proteção Total PGS": {
                            "adesao": 120.00,
                            "faixas": [
                                {"fipe_range": "Até R$ 15.000", "valor": 77.00},
                                {"fipe_range": "R$ 16.000 a R$ 22.000", "valor": 85.00},
                            ],
                        },
                        "Plano Rastreamento Moto Básico": {"adesao": 120.00, "mensalidade": 60.00},
                    },
                },
            },
            last_turn_recap=TurnRecap(
                turn_number=2,
                user_intent="Informou que é XRE 300 pra trilha e cidade",
                agent_action="Apresentou Básico R$60 e mencionou PGS",
                key_info_exchanged=["preço Básico R$60", "existência do PGS"],
            ),
        ),
        "profile": json.dumps({
            "client_identity": {"name": "Bruno Nascimento", "vehicle": "Honda XRE 300"},
            "clients_mindset": {"primary_concern": "trilha + segurança"},
        }),
        "shorterm_history": "Turn 1: 'quero saber sobre rastreador pra moto'. Turn 2: 'é uma XRE 300, uso pra trilha e cidade'. Bot apresentou Básico R$60 e mencionou PGS.",
        "longterm_history": {"topic_details": []},
        "waiting_messages": ["opa, desculpa, tava no trabalho. quanto era mesmo o mais completo?"],
        "recent_catalogs": [],
        "system_op_output": None,
    },
}


def list_synthetic_scenarios() -> dict:
    """Return metadata for all synthetic scenarios."""
    return {
        name: {
            "description": s["description"],
            "agent_focus": s["agent_focus"],
            "turn": s["state"].metadata.current_turn_number,
            "topic": s["state"].identified_topic or "NEW_CONTACT",
        }
        for name, s in SYNTHETIC_SCENARIOS.items()
    }


def inject_synthetic_state(scenario_name: str, contact_id: str = None) -> str:
    """Inject a synthetic scenario into Redis, returning the contact_id used.

    This creates a fully populated Redis state identical to what a real
    conversation would produce, enabling benchmark runs without live chat.
    """
    scenario = SYNTHETIC_SCENARIOS.get(scenario_name)
    if not scenario:
        raise ValueError(f"Unknown scenario: {scenario_name}. Available: {list(SYNTHETIC_SCENARIOS.keys())}")

    # Deep copy to avoid mutating the shared singleton
    state = scenario["state"].model_copy(deep=True)
    cid = contact_id or f"synth-{scenario_name}-{uuid.uuid4().hex[:6]}"

    # Override metadata contact_id
    state.metadata.contact_id = cid

    # 1. Save conversation state
    from app.services.state_manager_service import StateManagerService
    sm = StateManagerService()
    sm.save_state(cid, state)

    # 2. Inject profile
    if scenario.get("profile"):
        redis_client.set(f"{cid}:customer_profile", scenario["profile"])

    # 3. Inject short-term history
    if scenario.get("shorterm_history"):
        redis_client.set(f"shorterm_history:{cid}", scenario["shorterm_history"])

    # 4. Inject long-term history
    if scenario.get("longterm_history"):
        redis_client.set(f"longterm_history:{cid}", json.dumps(scenario["longterm_history"]))

    # 5. Inject waiting messages
    if scenario.get("waiting_messages"):
        key = f"contacts_messages:waiting:{cid}"
        redis_client.delete(key)
        for msg in scenario["waiting_messages"]:
            redis_client.rpush(key, msg)

    # 6. Inject recently sent catalogs
    if scenario.get("recent_catalogs"):
        key = f"{cid}:sended_catalogs"
        redis_client.delete(key)
        for cat in scenario["recent_catalogs"]:
            redis_client.rpush(key, cat)

    # 7. Inject system operation output
    if scenario.get("system_op_output"):
        redis_client.set(f"{cid}:last_system_operation_output", scenario["system_op_output"])

    # 8. Inject dev history for discriminator
    if scenario.get("waiting_messages"):
        for msg in scenario["waiting_messages"]:
            redis_client.rpush(f"dev:history:{cid}", json.dumps({
                "status": "received",
                "text": msg,
                "createdAt": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            }))

    # Register as active contact
    redis_client.sadd("contacts", cid)

    logger.info(f"[SYNTHETIC] Injected scenario '{scenario_name}' as contact '{cid}'")
    return cid
