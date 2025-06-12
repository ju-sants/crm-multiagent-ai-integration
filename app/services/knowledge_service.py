import yaml
import os
from typing import Dict, Any, List, Optional

class KnowledgeService:
    """
    Serviço para carregar e consultar as regras de negócio a partir de um arquivo YAML.
    Implementa um padrão Singleton para garantir que o arquivo de regras seja lido
    e processado apenas uma vez, armazenando os dados em memória para acesso rápido.
    """
    _instance = None
    _rules: Optional[Dict[str, Any]] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(KnowledgeService, cls).__new__(cls)
        return cls._instance

    def __init__(self, yaml_path: str = 'app/config/guidelines/business_rules.yaml'):
        if self._rules is None:
            self.yaml_path = yaml_path
            self._load_rules()

    def _load_rules(self):
        try:
            if not os.path.exists(self.yaml_path):
                raise FileNotFoundError(f"Arquivo de regras não encontrado em: {self.yaml_path}")

            with open(self.yaml_path, 'r', encoding='utf-8') as file:
                self._rules = yaml.safe_load(file)
            
            if not self._rules:
                raise ValueError("Arquivo de regras está vazio ou malformado.")
                
            print("KnowledgeService: Regras de negócio carregadas com sucesso.")
        except Exception as e:
            print(f"ERRO CRÍTICO no KnowledgeService: {e}")
            self._rules = {}

    def _get_rule_section(self, section_name: str) -> Any:
        """Helper para obter uma seção principal das regras com segurança."""
        if not self._rules:
            return None
        return self._rules.get(section_name, {})

    def find_information(self, query: Dict[str, Any]) -> Any:
        """
        Ponto de entrada principal para buscar informações.
        Funciona como um roteador que chama a função de busca apropriada
        com base no 'topic' da query.
        """
        topic = query.get('topic')
        params = query.get('params', {})

        # Dicionário completo de tópicos e funções correspondentes
        search_functions = {
            'list_all_products': self._search_list_all_products,
            'pricing': self._search_pricing,
            'installation_policy': self._search_installation_policy,
            'product_compatibility': self._search_product_compatibility,
            'contract_terms': self._search_contract_terms,
            'regional_availability': self._search_regional_availability,
            'get_sales_philosophy': self._search_sales_philosophy,
            'get_support_philosophy': self._search_support_philosophy,
            'get_company_info': self._search_company_info,
            'maintenance_policy': self._search_maintenance_policy,
            'technical_limitations': self._search_technical_limitations,
            'blocker_installation_rules': self._search_blocker_installation_rules,
            'application_features': self._search_application_features,
            'faq': self._search_faq,
        }

        search_function = search_functions.get(topic)

        if search_function:
            return search_function(params)
        else:
            valid_topics = list(search_functions.keys())
            return f"Erro: Tópico '{topic}' inválido. Por favor, use um dos seguintes tópicos: {valid_topics}"

    # --- Funções de Busca ---
    def _search_company_info(self, params: Dict[str, Any]) -> Dict:
        return self._get_rule_section('company_info')

    def _search_maintenance_policy(self, params: Dict[str, Any]) -> Dict:
        return self._get_rule_section('operational_procedures').get('maintenance')

    def _search_scheduling_rules(self, params: Dict[str, Any]) -> Dict:
        return self._get_rule_section('operational_procedures').get('scheduling')
        
    def _search_application_features(self, params: Dict[str, Any]) -> Dict:
        """
        Busca informações sobre as funcionalidades do aplicativo.
        Pode retornar todas as features ou uma específica se o nome for fornecido.
        """
        app_features = self._get_rule_section('application_features')
        feature_name = params.get('feature_name')

        if feature_name:
            # Busca por uma feature específica, ignorando maiúsculas/minúsculas e acentos
            normalized_feature_name = feature_name.lower()
            for key, value in app_features.items():
                if normalized_feature_name in key.lower():
                    return {key: value}
            return {"error": f"Funcionalidade '{feature_name}' não encontrada."}
        
        # Se nenhum nome for fornecido, retorna a visão geral
        return app_features.get('overview')

    def _search_faq(self, params: Dict[str, Any]) -> Any:
        plan_name = params.get('plan_name')
        if not plan_name: return {"error": "Parâmetro 'plan_name' é obrigatório para buscar FAQ."}
        for category in self._get_rule_section('products'):
            for plan in category.get('plans', []):
                if plan.get('name') == plan_name:
                    return plan.get('faq', [])
        return {"error": f"Plano '{plan_name}' não encontrado para busca de FAQ."}
    
    def _search_list_all_products(self, params: Dict[str, Any]) -> List[Dict[str, str]]:
        products_data = self._get_rule_section('products')
        product_list = []
        for category in products_data:
            for plan in category.get('plans', []):
                product_list.append({
                    "category": category.get('category'),
                    "plan_name": plan.get('name'),
                    "description": plan.get('type')
                })
        return product_list

    def _search_pricing(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        plan_name = params.get('plan_name')
        if not plan_name: return {"error": "Parâmetro 'plan_name' é obrigatório."}
        for category in self._get_rule_section('products'):
            for plan in category.get('plans', []):
                if plan.get('name') == plan_name:
                    return plan.get('pricing')
        return {"error": f"Plano '{plan_name}' não encontrado."}

    def _search_installation_policy(self, params: Dict[str, Any]) -> Optional[str]:
        policy_data = self._get_rule_section('operational_procedures').get('installation', {}).get('location_policy', {})
        vehicle_type = params.get('vehicle_type')
        for exception in policy_data.get('exceptions', []):
            if exception.get('vehicle_type') == vehicle_type:
                return exception.get('policy')
        return policy_data.get('default')

    def _search_product_compatibility(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        detail = params.get('detail', '').lower()
        compatibility_rules = self._get_rule_section('operational_procedures').get('compatibility', {})
        if 'john deere' in detail and 'piloto automático' in detail:
            return compatibility_rules.get('john_deere_autopilot')
        return {"is_compatible": True, "explanation": "Nenhuma incompatibilidade conhecida para este caso."}
    
    def _search_contract_terms(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        contract_id = params.get('contract_id')
        if not contract_id: return {"error": "Parâmetro 'contract_id' é obrigatório."}
        contractual_data = self._get_rule_section('legal_and_contractual')
        response = contractual_data.get('general_terms', {})
        specific_terms = contractual_data.get(f"{contract_id}_contract")
        if specific_terms:
            response.update(specific_terms)
            return response
        return {"error": f"Contrato com ID '{contract_id}' não encontrado."}

    def _search_regional_availability(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        location_info = params.get('location_info', {})
        ddd = location_info.get('ddd')
        regional_rules = self._get_rule_section('operational_procedures').get('regional_service_rules', {}).get('contact_origin_indicators', [])
        for rule in regional_rules:
            if ddd and f"DDD {ddd}" in rule.get('origin', ''):
                return {"plan_availability": rule.get('plan_availability')}
        return {"plan_availability": "Nenhuma restrição específica encontrada para esta localidade."}

    def _search_sales_philosophy(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self._get_rule_section('communication_guidelines').get('sales')

    def _search_support_philosophy(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self._get_rule_section('communication_guidelines').get('support')
    
    def _search_maintenance_policy(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self._get_rule_section('operational_procedures').get('maintenance')

    def _search_technical_limitations(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self._get_rule_section('operational_procedures').get('technical_limitations')

    def _search_blocker_installation_rules(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self._get_rule_section('operational_procedures').get('blocker_installation_rules')

    def _search_application_features(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self._get_rule_section('application_features')

    def _search_faq(self, params: Dict[str, Any]) -> Optional[List[Dict[str, str]]]:
        plan_name = params.get('plan_name')
        keyword = params.get('question_keyword', '').lower()
        if not plan_name: return {"error": "Parâmetro 'plan_name' é obrigatório para buscar FAQ."}
        
        for category in self._get_rule_section('products'):
            for plan in category.get('plans', []):
                if plan.get('name') == plan_name:
                    faqs = plan.get('faq', [])
                    if not keyword: return faqs
                    
                    # Filtra por palavra-chave
                    return [q for q in faqs if keyword in q.get('question', '').lower()]
        
        return {"error": f"Plano '{plan_name}' não encontrado para busca de FAQ."}


# Inicialização Singleton
knowledge_service_instance = KnowledgeService()