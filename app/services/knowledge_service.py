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
            self._topic_map = {
                'application_features': ('application_features',),
                'company_info': ('business_rules', 'company_info'),
                'maintenance_policy': ('operational_procedures', 'maintenance'),
                'scheduling_rules': ('operational_procedures', 'scheduling'),
                'installation_policy': ('operational_procedures', 'installation'),
                'product_compatibility': ('operational_procedures', 'compatibility'),
                'regional_availability': ('operational_procedures', 'regional_service_rules'),
                'sales_philosophy': ('communication', 'sales'),
                'support_philosophy': ('communication', 'support'),
                'technical_limitations': ('operational_procedures', 'technical_limitations'),
                'blocker_installation_rules': ('operational_procedures', 'blocker_installation_rules'),
                'customer_profile_scripts': ('business_rules', 'customer_profiles_and_triggers'),
                'list_all_products': ('products',),
                'sales_guidance': ('business_rules', 'sales_guidance'),
                'contract_terms': ('contracts',),
            }
            self._plan_based_topics = {'pricing', 'faq', 'key_selling_points', 'objection_handling'}

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

    def _get_data_with_related_queries(self, *section_keys: str) -> Optional[Dict[str, Any]]:
        """
        Busca dados aninhados e agrega 'related_queries' de todos os níveis.
        """
        current_level = self._rules
        all_queries = []

        for key in section_keys:
            if not isinstance(current_level, dict):
                return {"error": f"Caminho inválido. '{key}' não pode ser acessado."}
            
            if 'related_queries' in current_level:
                all_queries.extend(q for q in current_level['related_queries'] if q not in all_queries)

            current_level = current_level.get(key)
            if current_level is None:
                return {"error": f"Seção '{key}' não encontrada no caminho '{'/'.join(section_keys)}'."}

        if isinstance(current_level, dict) and 'related_queries' in current_level:
            all_queries.extend(q for q in current_level['related_queries'] if q not in all_queries)
        
        return {
            "data": current_level,
            "related_queries": all_queries
        }

    def find_information(self, query: Dict[str, Any]) -> Any:
        """
        Ponto de entrada dinâmico para buscar informações na base de conhecimento.
        """
        topic = query.get('topic')
        params = query.get('params', {})
        
        # Lógica de fallback com Fuzzy Matching
        all_topics = list(self._topic_map.keys()) + list(self._plan_based_topics)
        if topic not in all_topics:
            best_match, score = process.extractOne(topic, all_topics)
            if score > 80:
                logger.info(f"Tópico '{topic}' não encontrado. Usando melhor correspondência: '{best_match}' (score: {score}).")
                topic = best_match
            else:
                return f"Erro: Tópico '{topic}' inválido. Tópicos válidos: {all_topics}"

        # --- Lógica de Roteamento ---

        # 1. Tópicos baseados em plano
        if topic in self._plan_based_topics:
            plan_name = params.get('plan_name')
            if not plan_name:
                return {"error": f"Parâmetro 'plan_name' é obrigatório para o tópico '{topic}'."}
            plan = self._find_plan_by_name(plan_name)
            if not plan:
                return {"error": f"Plano '{plan_name}' não encontrado."}
            
            # Encontra o produto que contém o plano para construir o caminho
            for product in self._get_rule_section('products'):
                if any(p['name'] == plan['name'] for p in product.get('plans', [])):
                    category_name = product.get('category', '').lower().replace(' ', '_')
                    # Encontra o plano dentro da categoria para obter os dados corretos
                    for p in product.get('plans', []):
                        if p['name'] == plan['name']:
                             path = ('products', category_name, 'plans', p['name'], topic)
                             return self._get_data_with_related_queries(*path)
            return {"error": f"Não foi possível encontrar a categoria para o plano '{plan_name}'."}

        # 2. Tópicos especiais com lógica customizada
        if topic == 'contract_terms':
            contract_id = params.get('contract_id', 'general_terms')
            return self._get_data_with_related_queries('contracts', contract_id)

        if topic == 'application_features':
            feature_name = params.get('feature_name')
            if feature_name:
                # Tenta correspondência exata e depois parcial
                app_features = self._get_rule_section('application_features')
                for key in app_features.keys():
                    if feature_name.lower() in key.lower():
                        return self._get_data_with_related_queries('application_features', key)
                return {"error": f"Funcionalidade '{feature_name}' não encontrada."}
            return self._get_data_with_related_queries('application_features', 'overview')

        # 3. Tópicos mapeados diretamente
        if topic in self._topic_map:
            path = self._topic_map[topic]
            return self._get_data_with_related_queries(*path)

        return {"error": f"Lógica de busca para o tópico '{topic}' não implementada."}



# Inicialização Singleton
knowledge_service_instance = KnowledgeService()