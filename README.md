# Global Agent

Um serviço em Flask para integração com a API do Callbell, processando mensagens do WhatsApp e utilizando agentes de IA para respostas automatizadas.

## Funcionalidades

- Recebimento de mensagens via webhook do Callbell
- Processamento de mensagens utilizando agentes de IA (MVP Crew)
- Integração com Qdrant para armazenamento vetorial
- Cache de conversas e histórico de mensagens

## Pré-requisitos

- Python 3.10+
- Conta no Callbell com API Key
- Instância do Qdrant (local ou cloud)

## Instalação

```bash
git clone [URL do repositório]
cd Global-Agent
pip install -r requirements.txt
```

## Configuração

Crie um arquivo `.env` na raiz do projeto com:

```env
CALLBELL_API_KEY=sua_chave_aqui
QDRANT_URL=http://localhost:6333
```

## Execução

**Ambiente de desenvolvimento:**
```bash
flask run --host=0.0.0.0 --port=5000
```

**Produção:**
```bash
gunicorn --bind 0.0.0.0:5000 main:app
```

## Endpoints

- `POST /receive_message`: Endpoint para recebimento de webhooks do Callbell

## Implantação no Heroku

1. Crie um novo app Railway
2. Configure as variáveis de ambiente no painel de configurações
3. O `Procfile` já contém a configuração necessária:
```bash
web: gunicorn main:app
```

## Estrutura do Projeto
```
├── app/              # Módulos principais
│   ├── config/       # Configurações e definições
│   ├── crews/        # Definições de crews de agentes
│   ├── tools/        # Ferramentas e integrações
│   └── services/     # Serviços externos
├── main.py           # Ponto de entrada da aplicação
├── requirements.txt  # Dependências do projeto
└── Procfile          # Configuração de deploy
```

## Contribuição

1. Faça um fork do projeto
2. Crie uma branch (`git checkout -b feature/nova-funcionalidade`)
3. Commit suas mudanças (`git commit -am 'Adiciona nova funcionalidade'`)
4. Push para a branch (`git push origin feature/nova-funcionalidade`)
5. Abra um Pull Request