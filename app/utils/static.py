default_strategic_plan = {
  "system_action_request": None,
  "conversation_blueprint": {
    "customer_context_summary": {
      "relevant_profile_insights": "Novo contato, sem histórico prévio.",
      "insights_from_current_session": "Objetivo: Acolher o cliente, estabelecer um tom cordial e entender a necessidade inicial."
    },
    "product_presentation_strategy": {
      "presentation_order": [],
      "primary_offer": None,
      "secondary_offer": None
    },
    "communication_guidance": {
      "tone_and_style": "Profissional, acolhedor e prestativo. Foco em cordialidade e confiança, sem ser robótico.",
      "key_talking_points": [
        "Agradecer o contato e dar boas-vindas à Global System.",
        "Apresentar-se como o assistente virtual pronto para ajudar.",
        "Finalizar com uma pergunta aberta, passando o controle da conversa ao cliente.",
        "REGRA: É proibido fazer perguntas de qualificação (veículo/uso) ou oferecer produtos nesta interação."
      ],
      "key_questions_to_ask": [
        "Olá! Seja bem-vindo(a) à Global System. Eu sou Alessandro, seu assistente virtual. Como posso ajudar hoje?"
      ],
      "next_step_preview": "Aguardar a resposta do cliente para categorizar a intenção e definir a próxima estratégia."
    },
    "information_payload": {
      "agent_persona": {
        "name": "Alessandro",
        "role": "Assistente virtual da Global System."
      }
    }
  }
}


plans_messages = {
                "Plano Rastreamento Moto Básico": """
MOTO GSM/PGS

🛵🏍️ Para sua moto, temos duas opções incríveis:

Link do Catálogo Visual: Acesse e confira todos os detalhes:
https://wa.me/p/9380524238652852/558006068000

Adesão Única: R$ 120,00

Plano Rastreamento (sem cobertura FIPE):
Apenas R$ 60/mês, com plantão 24h incluso para sua segurança!

Plano Rastreamento + Proteção Total PGS (com cobertura FIPE):
Com este plano, se não recuperarmos sua moto, você recebe o valor da FIPE!
    Até R$ 15 mil: R$ 77/mês
    De R$ 16 a 22 mil: R$ 85/mês
    De R$ 23 a 30 mil: R$ 110/mês
""",
                "Plano Rastreamento + Proteção Total PGS": """
MOTO GSM/PGS

🛵🏍️ Para sua moto, temos duas opções incríveis:

Link do Catálogo Visual: Acesse e confira todos os detalhes:
https://wa.me/p/9380524238652852/558006068000

Adesão Única: R$ 120,00

Plano Rastreamento (sem cobertura FIPE):
Apenas R$ 60/mês, com plantão 24h incluso para sua segurança!

Plano Rastreamento + Proteção Total PGS (com cobertura FIPE):
Com este plano, se não recuperarmos sua moto, você recebe o valor da FIPE!
    Até R$ 15 mil: R$ 77/mês
    De R$ 16 a 22 mil: R$ 85/mês
    De R$ 23 a 30 mil: R$ 110/mês
""",
                "Rastreador GSM 4G": """
GSM Padrão

🚗 Nosso Plano GSM Padrão é ideal para seu veículo!

    Adesão: R$ 200,00
    Mensalidade:
        Sem bloqueio: R$ 65/mês
        Com bloqueio: R$ 75/mês

Confira mais detalhes no nosso catálogo:
https://wa.me/p/9356355621125950/558006068000""",
                "GSM FROTA": """
GSM FROTA

🚚 Gerencie sua frota com eficiência e segurança!

Conheça nosso Plano GSM FROTA: https://wa.me/p/9321097734636816/558006068000
""",
                "SATELITAL FROTA": """
SATELITAL FROTA

🌍 Para sua frota, conte com a alta precisão do nosso Plano SATELITAL FROTA!

Confira os detalhes: https://wa.me/p/9553408848013955/558006068000
""",
                "Rastreador Híbrido SATELITAL": """
HÍBRIDO

📡 O melhor dos dois mundos para seu rastreamento!

Descubra o Plano HÍBRIDO: https://wa.me/p/8781199928651103/558006068000
""",
                "Rastreador GSM (2G+3G+4G) + WI-FI": """
GSM+WiFi

📶 Conectividade e segurança aprimoradas para sua fazenda!

Saiba mais sobre o Plano GSM+WiFi: https://wa.me/p/9380395508713863/558006068000
""",
                "Plano para Scooters, Patinetes e Bikes Elétricas": """
Scooters/Patinetes

🛴 Mantenha seus veículos de mobilidade pessoal sempre seguros!

    Plano exclusivo para Scooters e Patinetes: https://wa.me/p/8478546275590970/558006068000
"""
}

agent_state_mapping = {
    "StrategicAdvisor": [
        "metadata",
        "operational_context",
        "entities_extracted",
        "disclosure_checklist",
        "products_discussed",
        "qualification_tracker",
        "unresolved_objections",
        "conversation_goals"
    ],
    "IncrementalStrategicPlannerAgent": [
        "metadata",
        "operational_context",
        "entities_extracted",
        "disclosure_checklist",
        "strategic_plan",
        "products_discussed",
        "last_turn_recap",
        "unresolved_objections",
        "qualification_tracker"
    ],
    "SystemOperationsAgent": [
        "metadata",
        "entities_extracted",
        "system_action_request"
    ],
    "CommunicationAgent": [
        "metadata",
        "strategic_plan",
        "disclosure_checklist",
        "products_discussed",
        "entities_extracted",
        "last_turn_recap",
        "unresolved_objections"
    ],
    "RegistrationDataCollectorAgent": [
        "metadata",
        "entities_extracted",
    ],
    "StateSummarizerAgent": [
        "entities_extracted",
        "identified_topic",
        "user_sentiment_history",
        "qualification_tracker",
        "last_turn_recap",
        "unresolved_objections",
    ],
    "RoutingAgent": [
        "metadata",
        "strategic_plan",
        "identified_topic",
        "last_turn_recap",
        "qualification_tracker",
        "products_discussed",
        "disclosure_checklist",
        "unresolved_objections"
    ],
}

dict_text_normalization = {
    "(2G + 3G + 4G)": "dois G, três G e quatro G",
    "(2G+3G+4G)": "dois G, três G e quatro G",
    "(2G + 3G)": "dois G e três G",
    "(2G+3G)": "dois G e três G",
    "(2G + 4G)": "dois G e quatro G",
    "(2G+4G)": "dois G e quatro G",
    "(3G + 4G)": "três G e quatro G",
    "(3G+4G)": "três G e quatro G",
    "(2G)": "dois G",
    "(3G)": "três G",
    "(4G)": "quatro G",
    "(5G)": "cinco G",
    "(2G/3G/4G)": "dois G, três G e quatro G",
    "(2G/3G)": "dois G e três G",
    "(2G/4G)": "dois G e quatro G",
    "(3G/4G)": "três G e quatro G",
    "(2G/3G/4G/5G)": "dois G, três G, quatro G e cinco G",
    "(2G/3G/5G)": "dois G, três G e cinco G",
    "(2G/4G/5G)": "dois G, quatro G e cinco G",
    "(3G/4G/5G)": "três G, quatro G e cinco G",
}