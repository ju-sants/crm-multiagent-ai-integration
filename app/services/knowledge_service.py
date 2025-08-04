import yaml
import os
from typing import Dict, Any, List, Optional
from thefuzz import process
from app.core.logger import get_logger

logger = get_logger(__name__)

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

    def __init__(self, knowledge_base_path: str = 'app/domain_knowledge'):
        if self._rules is None:
            self.knowledge_base_path = knowledge_base_path
            self._load_rules()

    def _deep_merge(self, destination: Dict, source: Dict):
        """
        Combina dicionários aninhados de forma recursiva, fundindo o 'source' no 'destination'.
        """
        for key, value in source.items():
            if isinstance(value, dict) and key in destination and isinstance(destination[key], dict):
                self._deep_merge(destination[key], value)
            else:
                destination[key] = value

    def _load_rules(self):
        """
        Carrega regras de negócio de forma recursiva a partir de um diretório de arquivos YAML.
        Os arquivos na raiz são mesclados em chaves de nível superior baseadas em seus nomes.
        Arquivos em subdiretórios (como 'products') são agrupados em listas.
        """
        self._rules = {}
        try:
            if not os.path.isdir(self.knowledge_base_path):
                raise FileNotFoundError(f"Diretório da base de conhecimento não encontrado em: {self.knowledge_base_path}")

            # Processa todos os arquivos YAML no diretório raiz
            for file_path in os.listdir(self.knowledge_base_path):
                full_path = os.path.join(self.knowledge_base_path, file_path)
                if os.path.isfile(full_path) and file_path.endswith('.yaml'):
                    filename_no_ext = os.path.splitext(file_path)[0]
                    with open(full_path, 'r', encoding='utf-8') as file:
                        data = yaml.safe_load(file)
                        if data:
                            # O arquivo 'business_rules.yaml' é especial; seu conteúdo é mesclado na raiz.
                            if filename_no_ext == 'business_rules':
                                self._deep_merge(self._rules, data)
                            else:
                                self._rules[filename_no_ext] = data
            
            # Processa a pasta de produtos separadamente para criar uma lista de produtos
            products_path = os.path.join(self.knowledge_base_path, 'products')
            if os.path.isdir(products_path):
                self._rules['products'] = []
                for file_path in os.listdir(products_path):
                    full_path = os.path.join(products_path, file_path)
                    if os.path.isfile(full_path) and file_path.endswith('.yaml'):
                        with open(full_path, 'r', encoding='utf-8') as file:
                            product_data = yaml.safe_load(file)
                            if product_data:
                                # Injeta o nome da categoria com base no nome do arquivo para referência futura
                                filename_no_ext = os.path.splitext(file_path)[0]
                                product_data['category'] = filename_no_ext.replace('_', ' ').title()
                                self._rules['products'].append(product_data)

            if not self._rules:
                raise ValueError("Nenhuma regra foi carregada. A base de conhecimento está vazia ou malformada.")
                
            logger.info("KnowledgeService: Regras de negócio modulares carregadas com sucesso.")
        except Exception as e:
            logger.info(f"ERRO CRÍTICO no KnowledgeService ao carregar regras modulares: {e}")
            self._rules = {}

    def _get_rule_section(self, section_name: str) -> Any:
        """Helper para obter uma seção principal das regras com segurança."""
        if not self._rules:
            return None
        return self._rules.get(section_name, {})

    def _get_all_plans(self) -> List[Dict[str, Any]]:
        """Helper para extrair todos os planos de todas as categorias de produtos."""
        all_plans = []
        for category in self._get_rule_section('products'):
            all_plans.extend(category.get('plans', []))
        return all_plans

    def _find_plan_by_name(self, plan_name: str) -> Optional[Dict[str, Any]]:
        """
        Helper para encontrar um plano específico pelo nome usando busca fuzzy.
        Retorna o plano mais correspondente se a pontuação de similaridade for alta o suficiente.
        """
        if not plan_name:
            return None

        all_plans = self._get_all_plans()
        plan_names = [plan['name'] for plan in all_plans]

        # Usa process.extractOne para encontrar a melhor correspondência
        best_match, score = process.extractOne(plan_name, plan_names)

        # Se a pontuação for boa o suficiente, encontre e retorne o objeto completo do plano
        if score > 85:  # Limiar de confiança ajustável
            logger.info(f"Busca por plano: '{plan_name}' correspondeu a '{best_match}' com score {score}.")
            for plan in all_plans:
                if plan['name'] == best_match:
                    return plan
        
        logger.warning(f"Nenhum plano correspondente encontrado para '{plan_name}' (melhor tentativa: '{best_match}', score: {score}).")
        return None

    def find_information(self, query: Dict[str, Any]) -> Any:
        """
        Ponto de entrada principal para buscar informações com lógica de fallback de busca semântica.
        Primeiro, tenta uma correspondência exata do tópico. Se falhar, usa a correspondência fuzzy
        para encontrar o tópico mais provável e executa a consulta com ele.
        """
        topic = query.get('topic')
        params = query.get('params', {})

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
            'key_selling_points': self._search_key_selling_points,
            'objection_handling': self._search_objection_handling,
            'customer_profile_scripts': self._search_customer_profiles,
        }

        # Tentativa de correspondência exata primeiro
        search_function = search_functions.get(topic)
        if search_function:
            return search_function(params)

        # Fallback para busca fuzzy se a correspondência exata falhar
        valid_topics = list(search_functions.keys())
        best_match, score = process.extractOne(topic, valid_topics)

        # Executa a função correspondente se a pontuação de similaridade for alta o suficiente
        if score > 80:  # Limiar de confiança ajustável
            logger.info(f"KnowledgeService: Tópico original '{topic}' não encontrado. Usando a melhor correspondência '{best_match}' com pontuação {score}.")
            return search_functions[best_match](params)
        else:
            return f"Erro: Tópico '{topic}' inválido e nenhuma correspondência suficientemente boa foi encontrada. Tópicos válidos: {valid_topics}"

    # --- Funções de Busca (Refatoradas para retornar blocos de dados) ---
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
    
    def _search_list_all_products(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Lista todos os produtos e injeta diretrizes de vendas estratégicas na resposta.
        A resposta é um dicionário contendo a lista de produtos e as diretrizes de venda.
        """
        products_data = self._get_rule_section('products')
        sales_guidance = self._get_rule_section('sales_guidance')
        
        product_list = []
        for category in products_data:
            for plan in category.get('plans', []):
                product_list.append({
                    "category": category.get('category'),
                    "plan_name": plan.get('name'),
                    "description": plan.get('type'),
                    "sales_pitch": plan.get('sales_pitch'), # Adicionado pitch de vendas
                    "pricing": plan.get('pricing'),
                })
        
        return {
            "sales_guidance": sales_guidance,
            "products": product_list
        }

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