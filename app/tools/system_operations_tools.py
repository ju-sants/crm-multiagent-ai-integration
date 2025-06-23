from langchain_core.tools import tool
from typing import List, Dict, Any


from app.services.system_operations_service import system_operations_service

# Langchain OpenAI Tool
@tool("system_operations_tool", description="Executa operações de sistema como pesquisar boletos, enviar resets, verificar status de rastreamento, etc. Utilize consultas em lote, uma lista de dicionários com `action_type` e `params`.")
def system_operations_tool(queries: List[Dict[str, Any]]) -> dict:

        # pre check
        if not isinstance(queries, list):
            return {"status": "error", "error_message": "O input deve ser uma lista de dicionários de query."}
        
        if not all(isinstance(query, dict) for query in queries):
            return {"status": "error", "error_message": "O input deve ser uma lista de dicionários de query."}
        
        if not all(query.get("action_type") for query in queries):
            return {"status": "error", "error_message": "Todas as queries devem ter um campo 'action_type'."}
        
        results = {}
        for query in queries:
            action_type = query.get("action_type")
            params = query.get("params", {})
            result = system_operations_service.execute(action_type, params)
            
            results[action_type] = result
        
        return results