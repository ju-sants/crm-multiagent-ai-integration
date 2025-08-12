import json
import json5
import re
import ast
import logging
from sentence_transformers import util

from app.services.nlp_service import carregar_modelo_semantico

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

modelo_semantico = carregar_modelo_semantico()
def _extrair_bloco_json(texto_bruto: str) -> str:
    """
    Helper para extrair de forma inteligente o bloco JSON de uma string.
    Remove texto introdutório, final e blocos de markdown.
    """
    # 1. Tenta encontrar um bloco de código JSON em markdown (ex: ```json ... ```)
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', texto_bruto)
    if match:
        return match.group(1).strip()

    # 2. Se não houver markdown, encontra o primeiro '{' ou '[' e o último '}' ou ']'
    start_brace = texto_bruto.find('{')
    start_bracket = texto_bruto.find('[')
    
    # Encontra o primeiro caractere de início de JSON
    if start_brace == -1:
        start = start_bracket
    elif start_bracket == -1:
        start = start_brace
    else:
        start = min(start_brace, start_bracket)

    if start == -1:
        return texto_bruto # Retorna o texto original se não encontrar um início

    end_brace = texto_bruto.rfind('}')
    end_bracket = texto_bruto.rfind(']')
    end = max(end_brace, end_bracket)

    if end == -1:
        return texto_bruto

    return texto_bruto[start:end+1].strip()

def _tentar_parsear_bloco(bloco_json: str) -> dict | list | None:
    """
    Helper que tenta parsear o bloco de JSON usando uma cascata de métodos,
    do mais rígido e rápido para o mais flexível.
    """
    # --- Tentativa 1: O parser padrão (o mais rápido e ideal) ---
    try:
        return json.loads(bloco_json)
    except json.JSONDecodeError:
        pass

    # --- Tentativa 2: json5 (a nossa ferramenta principal) ---
    # Lida com: aspas simples, chaves sem aspas, vírgulas traçantes, comentários etc.
    try:
        return json5.loads(bloco_json)
    except Exception:
        pass

    # --- Tentativa 3: ast.literal_eval (para sintaxe de dicionário Python) ---
    try:
        py_literal_str = re.sub(r'\btrue\b', 'True', bloco_json, flags=re.IGNORECASE)
        py_literal_str = re.sub(r'\bfalse\b', 'False', py_literal_str, flags=re.IGNORECASE)
        py_literal_str = re.sub(r'\bnull\b', 'None', py_literal_str, flags=re.IGNORECASE)
        return ast.literal_eval(py_literal_str)
    except (ValueError, SyntaxError):
        return None

def parse_json_from_string(
    json_string: str, 
    update: bool = True
) -> tuple[dict | None, dict | None] | dict | list | None:
    """
    Analisa um objeto JSON de uma string, tentando corrigir erros comuns de sintaxe de LLMs.
    Esta função é projetada para ser robusta contra JSON malformado de modelos de linguagem.

    Args:
        json_string: A string completa retornada pelo LLM.
        update: Se True, retorna uma tupla (task_output, updated_state).
                Se False, retorna o objeto JSON completo.

    Returns:
        Dependendo do parâmetro 'update', retorna o objeto JSON parseado ou uma tupla.
        Retorna None ou (None, None) em caso de falha de parsing.
    """
    if not json_string or not isinstance(json_string, str):
        logger.warning("Input inválido: a string fornecida está vazia ou não é uma string.")
        return (None, None) if update else None
        
    bloco_extraido = _extrair_bloco_json(json_string)
    if not bloco_extraido:
        logger.warning("Não foi possível extrair um bloco JSON da string.")
        return (None, None) if update else None

    json_response = _tentar_parsear_bloco(bloco_extraido)

    if json_response is None:
        logger.error("Falha ao decodificar o JSON mesmo após todas as tentativas de correção.")
        logger.debug(f"String original fornecida:\n{json_string}")
        logger.debug(f"Bloco que falhou no parsing:\n{bloco_extraido}")
        return (None, None) if update else None

    logger.info("JSON parseado com sucesso.")
    
    if update:
        task_output = json_response.get('task_output')
        updated_state = json_response.get('updated_state')
        return task_output, updated_state
    else:
        return json_response
    

def limpar_tiques_verbais(mensagem: str) -> str:
    """
    Remove frases de preenchimento e tiques verbais do início de uma mensagem.
    Args:
        mensagem: O texto original gerado pelo LLM.

    Returns:
        A mensagem limpa, pronta para ser enviada.
    """
    padroes_iniciais = [
        "Ótimo", "Otimo", "Excelente", "Perfeito", "Maravilha", "Maravilhoso",
        "Que bom", "Que ótimo", "Que otimo", "Que maravilha",
        "Certo", "Correto", "Entendi", "Compreendi", "Claro", "Beleza"
    ]

    regex_padroes = "|".join(padroes_iniciais)

    expressao_completa = re.compile(
        fr"^(?:{regex_padroes})\b.*?[!\.\?]\s*",
        re.IGNORECASE | re.DOTALL
    )

    mensagem_limpa = re.sub(expressao_completa, "", mensagem)

    # Garante que a primeira letra da nova frase seja maiúscula
    if mensagem_limpa:
        return mensagem_limpa[0].upper() + mensagem_limpa[1:]
    
    return ""

def limpar_com_rede_de_seguranca(mensagem_original: str) -> str:
    """
    Limpa a mensagem original removendo tiques verbais e avaliando a taxa de remoção.
    Se a limpeza não for significativa, retorna a mensagem original.
    """
    mensagem_limpa = limpar_tiques_verbais(mensagem_original)

    if not mensagem_limpa or mensagem_limpa == mensagem_original:
        return mensagem_original
    
    len_original = len(mensagem_original)
    len_removido = len_original - len(mensagem_limpa)
    taxa_remocao = len_removido / len_original

    limiar_base = 0.80
    fator_tolerancia = 0.45 
    
    # O limiar dinâmico diminui conforme a taxa de remoção aumenta.
    limiar_dinamico = limiar_base - (taxa_remocao * fator_tolerancia)
    
    limiar_dinamico = max(limiar_dinamico, 0.35) 
    
    embedding_original = modelo_semantico.encode(mensagem_original, convert_to_tensor=True)
    embedding_limpo = modelo_semantico.encode(mensagem_limpa, convert_to_tensor=True)
    similaridade = util.pytorch_cos_sim(embedding_original, embedding_limpo).item()

    if similaridade >= limiar_dinamico:
        return mensagem_limpa
    else:
        return mensagem_original
