import ast
from crewai.tools.tool_calling import ToolCalling
from crewai.tools.tool_usage import ToolUsageErrorException, ToolUsage


def _original_tool_calling_aprimorado(self, tool_string: str, raise_error: bool = False):
    tool_name = self.action.tool
    tool = self._select_tool(tool_name)

    try:
        # 1. Obter as chaves de argumento que a ferramenta realmente espera
        expected_keys = list(tool.args_schema.model_json_schema()['properties'].keys())

        # 2. Tentar uma análise inicial (caminho feliz)
        raw_input = self.action.tool_input
        try:
            # Tenta converter a string para um dicionário
            arguments = ast.literal_eval(self._validate_tool_input(raw_input))
            if not isinstance(arguments, dict):
                raise ValueError("O input não é um dicionário.")
        except Exception:
            # Se a análise direta falhar, usa regex para extrair apenas as chaves esperadas.
            # Esta é uma forma de resgate para extrair dados úteis de uma string malformada.
            import re
            arguments = {}
            for key in expected_keys:
                # Tenta encontrar 'key': 'value' ou "key": "value"
                match = re.search(f"['\"]?{key}['\"]?\s*:\s*['\"](.*?)['\"]", raw_input)
                if match:
                    arguments[key] = match.group(1)

        # 3. Filtrar o dicionário para conter apenas as chaves esperadas
        # Isso remove chaves alucinadas como 'resposta_esperada'
        filtered_arguments = {key: arguments[key] for key in expected_keys if key in arguments}

        # 4. Verificar se algum argumento essencial está faltando (opcional, mas bom)
        if not filtered_arguments:
             raise ValueError(f"Não foi possível extrair nenhum argumento válido para a ferramenta '{tool_name}'. Input recebido: '{raw_input}'")

        return ToolCalling(
            tool_name=tool.name,
            arguments=filtered_arguments,
            log=tool_string
        )

    except Exception as e:
        if raise_error:
            raise e
        else:
            return ToolUsageErrorException(
                f'{self._i18n.errors("tool_arguments_error")}. Please, re-use the tool the right way.'
            )
        
def apply_crewai_tool_input_patch():
    ToolUsage._original_tool_calling = _original_tool_calling_aprimorado