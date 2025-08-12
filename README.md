# Callbell AI Integration Hub

## Descrição Curta

Este projeto é uma plataforma de automação conversacional de ponta que conecta o CRM **Callbell** a um ecossistema de Inteligência Artificial, utilizando o WhatsApp como principal canal de comunicação. Construído em Python e orquestrado por **Celery**, o sistema emprega uma arquitetura de multiagentes (CrewAI) para gerenciar conversas complexas, automatizar operações de sistema e fornecer respostas contextuais e precisas, atuando como um agente de vendas e suporte de alta performance.

A solução foi projetada com foco em robustez e extensibilidade, incorporando features avançadas como base de conhecimento para **RAG**, processamento de áudio e imagem, e estratégias de diálogo dinâmicas.

## Principais Funcionalidades

- **Arquitetura Multiagente Especializada:** Utiliza um sistema de agentes de IA com papéis definidos (analistas, comunicadores, operadores de sistema) para planejar e executar tarefas complexas, garantindo respostas coesas e alinhadas aos objetivos de negócio.
- **Planejamento Estratégico Dinâmico:** Um agente dedicado avalia e refina continuamente a estratégia de conversação, adaptando o plano de diálogo a cada turno para maximizar a eficácia da interação.
- **Base de Conhecimento com RAG:** As respostas são enriquecidas com informações de uma base de conhecimento estruturada (localizada em [`/app/domain_knowledge`](/app/domain_knowledge)), carregada via [`/app/services/knowledge_service.py`](/app/services/knowledge_service.py:1), minimizando alucinações e garantindo a precisão dos dados fornecidos.
- **Tolerância a Erros de Digitação (Fuzzy Matching):** Emprega a biblioteca `thefuzz` para interpretar queries de forma flexível, aumentando a robustez do sistema contra erros de digitação do usuário.
- **Processamento de Mídia:** Transcreve áudios, descreve imagens e envia respostas em áudio (via ElevenLabs) para criar uma experiência de usuário mais rica e acessível.
- **Limpeza de Saída do LLM:** Aplica técnicas de NLP com Sentence Transformers para remover "tiques verbais" e artefatos indesejados das respostas geradas pela IA, garantindo uma comunicação mais natural. Veja a implementação em [`/app/utils/funcs/parse_llm_output.py`](/app/utils/funcs/parse_llm_output.py).
- **Interação Segura com o Sistema:** Agentes especializados podem interagir com sistemas externos através de ferramentas seguras e bem definidas, como as encontradas em [`/app/tools/system_operations_tools.py`](/app/tools/system_operations_tools.py).
- **Agente de Reengajamento:** Um worker de inatividade ([`/app/workers/inactivity_worker.py`](/app/workers/inactivity_worker.py)) monitora conversas silenciosas e decide de forma inteligente se deve ou não enviar uma mensagem de acompanhamento para reengajar o cliente.
- **Gerenciamento de Estado com Pydantic e Redis:** O estado da conversa é gerenciado de forma robusta e persistente com modelos Pydantic e armazenado no Redis, permitindo que os agentes tenham memória de longo prazo das interações.
- **Otimização com Cache:** Utiliza `lru_cache` para armazenar em cache os resultados de serviços de áudio e imagem, reduzindo a latência e o custo de API.
- **Processamento Assíncrono com Celery:** Garante que a aplicação principal permaneça responsiva ao delegar tarefas pesadas (processamento de IA, APIs externas) para workers Celery.

## Arquitetura da Solução

A aplicação é um serviço de backend que expõe um webhook para o Callbell. O fluxo de interação é orquestrado por uma série de componentes especializados:

1.  **Webhook e Debounce:** O endpoint em `main.py` recebe a notificação da Callbell, armazena a mensagem em uma fila no Redis e agenda uma tarefa Celery com debounce para agrupar mensagens rápidas.
2.  **Orquestração de Agentes (CrewAI):** A tarefa Celery aciona a "tripulação" de IA.
    a.  **Agentes Analisadores:** Avaliam a intenção do usuário e o estado da conversa.
    b.  **Agente Estratégico:** Cria ou refina o plano de diálogo (`strategic_plan`), consultando a base de conhecimento quando necessário.
    c.  **Agente de Comunicação:** Gera a resposta final com base no plano estratégico.
    d.  **Agente Operador de Sistema:** É acionado quando a intenção do usuário é realizar uma ação no sistema (ex: cadastro), utilizando ferramentas específicas para a tarefa.
3.  **Gerenciamento de Estado:** O `StateManagerService` persiste o `ConversationState` no Redis durante todo o ciclo.
4.  **Entrega da Resposta:** O `CallbellService` envia a mensagem final, decidindo se o formato será texto ou áudio.

### Prompts e Personalização

O comportamento dos agentes é definido por prompts programáticos de alto nível, projetados para raciocínio em múltiplas etapas. Estes podem ser encontrados em [`/app/crews/agents_definitions/prompts/agents.yaml`](/app/crews/agents_definitions/prompts/agents.yaml).

### Patches e Customizações

O projeto inclui patches para bibliotecas de terceiros como `litellm` e `crewai.telemetry` para adaptar seu comportamento às necessidades específicas da aplicação. Veja em [`/app/patches`](/app/patches).

## Tecnologias Utilizadas

- **Linguagem:** Python 3.x
- **Framework Principal:** Flask
- **Orquestração de IA:** CrewAI
- **Modelos de Linguagem (LLMs):** OpenAI (gpt-4-o-mini), Google (gemini-2.5-flash), XAI (grok-3)
- **Processamento Assíncrono:** Celery
- **Banco de Dados / Cache / Broker:** Redis
- **Bibliotecas Principais:** `pydantic`, `thefuzz`, `sentence-transformers`, `pyyaml`
- **APIs e Plataformas:** Callbell, ElevenLabs, Gladia, Google Maps
- **DevOps:** Gunicorn

## Pré-requisitos

- Python (3.9+)
- Pip
- Git
- Redis

## Instalação e Configuração

1.  **Clonar o Repositório:**
    ```bash
    git clone <URL_DO_SEU_REPOSITORIO>
    cd <NOME_DO_DIRETORIO>
    ```

2.  **Criar e Ativar um Ambiente Virtual:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # No Windows: venv\Scripts\activate
    ```

3.  **Instalar as Dependências:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configurar as Variáveis de Ambiente:**
    Crie um arquivo `.env` na raiz do projeto, usando `app/config/settings.py` como modelo, e preencha as chaves de API e configurações do Redis.

    ```env
    # --- Chaves de API para LLMs ---
    XAI_API_KEY="sua_chave_xai"
    GEMINI_API_KEY="sua_chave_google_gemini"
    OPENAI_API_KEY="sua_chave_openai"

    # --- Chaves de API para Serviços ---
    CALLBELL_API_KEY="sua_chave_da_api_callbell"
    ELEVEN_LABS_API_KEY="sua_chave_da_elevenlabs"
    X_GLADIA_KEY="sua_chave_da_gladia"
    GMAPS_API_KEY="sua_chave_do_google_maps"
    APPID_IMAGE_DESCRIPTION='seu_appid'
    SECRET_IMAGE_DESCRIPTION='seu_secret'

    # --- Configurações do Redis ---
    REDIS_HOST="localhost"
    REDIS_PORT=6379
    REDIS_PASSWORD="" # Opcional
    REDIS_DB_MAIN=0

    # --- Outras Configurações ---
    LOG_LEVEL="INFO"
    ```

## Como Executar a Aplicação

1.  **Iniciar os Serviços:**
    - Garanta que o servidor Redis esteja rodando.
    - Em um terminal, inicie o worker do Celery:
      ```bash
      celery -A app.services.celery_service.celery_app worker --loglevel=INFO
      ```

2.  **Iniciar o Servidor Flask:**
    - Em outro terminal, inicie a aplicação:
      ```bash
      python main.py
      ```
    - O servidor estará disponível em `http://0.0.0.0:8080`.

## Estrutura dos Arquivos

```
/app
├── /config       # Configurações da aplicação e chaves
├── /core         # Módulos centrais como o logger
├── /crews        # Definição dos agentes, tarefas e prompts (o cérebro)
├── /domain_knowledge # Base de conhecimento para o RAG
├── /models       # Modelos de dados Pydantic
├── /patches      # Patches para bibliotecas de terceiros
├── /services     # Lógica de negócio e integrações com APIs
├── /tools        # Ferramentas que os agentes podem usar
├── /utils        # Funções utilitárias, callbacks e wrappers
└── /workers      # Workers assíncronos (ex: inatividade)
main.py           # Ponto de entrada da aplicação (Flask)
requirements.txt  # Dependências do projeto
Procfile          # Comando de execução para produção
```

## Licença

Este projeto não possui um arquivo de licença definido. Recomenda-se adicionar um arquivo `LICENSE` (ex: MIT, Apache 2.0).

## Como Contribuir

Contribuições são bem-vindas!

1.  **Faça um Fork** do repositório.
2.  **Crie uma Nova Branch** (`git checkout -b feature/minha-feature`).
3.  **Faça o Commit** (`git commit -am 'Adiciona nova feature'`).
4.  **Faça o Push** (`git push origin feature/minha-feature`).
5.  **Abra um Pull Request**.
