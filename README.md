# Callbell AI Integration Hub

<!-- Opcional: Adicione aqui badges de CI/CD, licença, etc. Ex:
[![Status da Build](https://github.com/seu-usuario/seu-repo/actions/workflows/main.yml/badge.svg)](https://github.com/seu-usuario/seu-repo/actions/workflows/main.yml)
[![Licença: MIT](https://img.shields.io/badge/Licença-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
-->

## Descrição Curta

Este projeto é uma plataforma de integração robusta que conecta a plataforma de CRM **Callbell** com múltiplas tecnologias de Inteligência Artificial, utilizando o WhatsApp como principal canal de comunicação. Construído em Python, o sistema funciona como um orquestrador inteligente, capaz de gerenciar conversas complexas, automatizar tarefas e fornecer respostas contextuais e precisas, agindo como um agente de vendas e suporte de alta performance.

## Principais Funcionalidades

- **Respostas Inteligentes e Contextuais:** Utiliza um sistema de multiagentes de IA (CrewAI) para entender, planejar e formular respostas que vão além de simples scripts, adaptando-se ao fluxo da conversa.
- **Gerenciamento de Estado de Conversa:** Mantém um estado persistente para cada contato usando Redis, permitindo que a IA tenha memória de interações passadas e tome decisões informadas.
- **Geração de Respostas por Áudio:** Converte mensagens de texto em áudio de forma dinâmica utilizando a API da ElevenLabs, melhorando a experiência do usuário em interações longas.
- **Análise de Mídia:** Processa automaticamente mensagens de áudio e imagem recebidas, transcrevendo-as e descrevendo-as para que o conteúdo seja compreendido e utilizado pelos agentes de IA.
- **Roteamento e Planejamento Estratégico:** Um agente de roteamento avalia a intenção do cliente e a qualidade do plano de conversa atual, decidindo se uma nova estratégia de diálogo é necessária para garantir respostas precisas.
- **Integração com Base de Conhecimento (RAG):** As respostas são fundamentadas em um conjunto de regras de negócio e informações de produtos definidas em um arquivo `business_rules.yaml`, evitando alucinações e garantindo a veracidade das informações.
- **Processamento Assíncrono:** Utiliza Celery e Redis para gerenciar tarefas em background (como transcrição de áudio, envio de mensagens e execução dos agentes de IA), garantindo que a aplicação principal permaneça responsiva.

## Arquitetura da Solução

A aplicação funciona como um serviço de backend que expõe um endpoint de webhook para a Callbell. O fluxo de uma interação típica é o seguinte:

1.  **Webhook:** A Callbell envia uma notificação de nova mensagem para o endpoint `/receive_message` da aplicação Flask.
2.  **Debounce e Enfileiramento:** A `main.py` recebe a mensagem, a armazena em uma fila no Redis e agenda uma tarefa Celery com um pequeno atraso (debounce). Isso agrupa mensagens enviadas em rápida sucessão pelo usuário em uma única tarefa de processamento. Anexos de áudio e imagem são processados em paralelo.
3.  **Orquestração de IA (CrewAI):** A tarefa Celery inicia a execução da "tripulação" de agentes de IA.
    a.  O **RoutingAgent** primeiro analisa a mensagem e o estado atual para decidir se o plano de conversa existente é adequado.
    b.  Se necessário, o **StrategicAdvisorAgent** é acionado para criar um novo plano (`strategic_plan`), consultando a base de conhecimento (`knowledge_service`) para obter informações de produtos, preços, etc.
    c.  Com um plano em mãos, o **CommunicationAgent** gera a sequência de mensagens de resposta, garantindo que o diálogo seja natural e siga a estratégia.
4.  **Gerenciamento de Estado:** Durante todo o processo, o `StateManagerService` lê e escreve o `ConversationState` do contato no Redis, garantindo que todos os agentes tenham acesso ao contexto mais recente.
5.  **Envio da Resposta:** A resposta final é enviada de volta ao usuário através do `CallbellService`, que decide se a envia como texto ou a converte para áudio via **ElevenLabs**.

## Tecnologias Utilizadas

- **Linguagem:** Python 3.x
- **Framework Principal:** Flask
- **Orquestração de IA:** CrewAI
- **Modelos de Linguagem (LLMs):**
  - OpenAI (série `gpt-4-o-mini`)
  - Google Gemini (série `gemini-2.5-flash`)
  - XAI (série `grok-3`)
- **Processamento Assíncrono:** Celery
- **Banco de Dados / Cache / Broker de Mensagens:** Redis
- **APIs e Plataformas:**
  - Callbell API
  - WhatsApp Business API (via Callbell)
  - ElevenLabs API (Texto para Áudio)
  - Gladia API (Transcrição de Áudio)
  - Google Maps API
- **Bibliotecas Principais:** `pydantic`, `requests`, `python-dotenv`, `pyyaml`.
- **DevOps:** Gunicorn (servidor de produção)

## Pré-requisitos

Para configurar e executar este projeto em um ambiente de desenvolvimento, você precisará ter o seguinte software instalado:

- Python (versão 3.9 ou superior)
- Pip (gerenciador de pacotes Python)
- Git
- Redis (servidor rodando localmente ou acessível)

## Instalação e Configuração

Siga estes passos para colocar a aplicação em funcionamento:

1.  **Clonar o Repositório:**
    ```bash
    git clone <URL_DO_SEU_REPOSITORIO>
    cd <NOME_DO_DIRETORIO>
    ```

2.  **Criar e Ativar um Ambiente Virtual:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # No Windows, use: venv\Scripts\activate
    ```

3.  **Instalar as Dependências:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configurar as Variáveis de Ambiente:**
    O projeto utiliza um arquivo `.env` para gerenciar chaves de API e outras configurações. Crie um arquivo chamado `.env` na raiz do projeto, copiando o modelo de `app/config/settings.py`. Você precisará preencher as seguintes variáveis:

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

    # --- Chaves para o Serviço de Descrição de Imagem ---
    APPID_IMAGE_DESCRIPTION='seu_appid'
    SECRET_IMAGE_DESCRIPTION='seu_secret'

    # --- Configurações do Redis ---
    REDIS_HOST="localhost"
    REDIS_PORT=6379
    REDIS_PASSWORD="seu_password_do_redis_se_houver" # Deixe em branco se não houver senha
    REDIS_DB_MAIN=0

    # --- Outras Configurações ---
    LOG_LEVEL="INFO"
    ```

## Como Executar a Aplicação

1.  **Iniciar os Serviços (Redis e Celery):**
    - Certifique-se de que seu servidor Redis esteja rodando.
    - Em um terminal separado, inicie o worker do Celery a partir da raiz do projeto:
      ```bash
      celery -A app.services.celery_service.celery_app worker --loglevel=INFO
      ```

2.  **Iniciar o Servidor Flask:**
    - Em outro terminal, inicie a aplicação Flask:
      ```bash
      python main.py
      ```
    - Por padrão, o servidor de desenvolvimento rodará em `http://0.0.0.0:8080`.

3.  **Execução em Produção:**
    - O arquivo `Procfile` indica o comando para um ambiente de produção (como o Heroku):
      ```bash
      web: celery -A app.services.celery_service.celery_app worker --loglevel=INFO && gunicorn -b 0.0.0.0:2828 main:app
      ```
    - Este comando inicia tanto o worker do Celery quanto o servidor Gunicorn. Para rodar localmente, você pode executar os comandos separadamente ou adaptar o script.

Após a execução, o servidor estará pronto para receber webhooks da Callbell no endpoint `http://seu-dominio-publico/receive_message`.

## Estrutura dos Arquivos

```
/app
├── /config       # Configurações da aplicação, LLMs e regras de negócio
├── /core         # Módulos centrais como o logger
├── /crews        # Definição dos agentes de IA, tarefas e prompts (o cérebro da aplicação)
├── /models       # Modelos de dados Pydantic (estruturas da aplicação)
├── /patches      # Patches para bibliotecas de terceiros
├── /services     # Lógica de negócio e integrações com APIs externas (Callbell, Redis, etc.)
├── /tools        # Ferramentas customizadas que os agentes de IA podem usar
└── /utils        # Funções utilitárias, callbacks e wrappers
main.py           # Ponto de entrada da aplicação Flask e do webhook
requirements.txt  # Dependências do projeto
Procfile          # Comando de execução para ambientes de produção
```

## Licença

Este projeto não possui um arquivo de licença definido. Recomenda-se adicionar um arquivo `LICENSE` para esclarecer os termos de uso e distribuição (ex: MIT, Apache 2.0).

## Como Contribuir

Contribuições são bem-vindas! Se você deseja melhorar este projeto, siga os passos abaixo:

1.  **Faça um Fork** do repositório.
2.  **Crie uma Nova Branch** para sua feature ou correção (`git checkout -b feature/minha-feature`).
3.  **Faça o Commit** de suas alterações (`git commit -am 'Adiciona nova feature'`).
4.  **Faça o Push** para a sua branch (`git push origin feature/minha-feature`).
5.  **Abra um Pull Request**.