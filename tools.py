# --- Definição das Ferramentas ---
class IntentClassifierTool(BaseTool):
    name: str = "Classificador de Intenção do Cliente"
    description: str = (
        "Analisa a mensagem do cliente para classificar sua intenção principal. "
        "As categorias de intenção são: 'SUPORTE_TECNICO', 'SOLICITACAO_ORCAMENTO', "
        "'DUVIDA_PRODUTO_SERVICO', 'FINANCEIRO', 'OUTROS'. "
        "Responda APENAS com a string da categoria."
    )

    def _run(self, client_message: str) -> str:
        return f"A intenção para a mensagem '{client_message}' precisa ser classificada pelo LLM do agente."
