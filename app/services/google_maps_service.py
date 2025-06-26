import googlemaps
from datetime import datetime

from app.config.settings import settings

def calcular_distancia_cidades(origem, destino):
    """
    Calcula a distância e o tempo de viagem de carro entre duas cidades
    usando a API Distance Matrix do Google Maps.

    Args:
        api_key (str): Sua chave da API do Google Maps.
        origem (str): A cidade de origem (ex: "São Paulo, SP").
        destino (str): A cidade de destino (ex: "Rio de Janeiro, RJ").

    Returns:
        dict: Um dicionário contendo 'distancia' e 'duracao',
              ou None se a rota não for encontrada.
    """
    try:
        gmaps = googlemaps.Client(key=settings.GMAPS_API_KEY)

        now = datetime.now()
        matrix = gmaps.distance_matrix(origins=[origem],
                                       destinations=[destino],
                                       mode="driving",
                                       language="pt-BR",
                                       units="metric",
                                       departure_time=now)

        if matrix['status'] == 'OK' and matrix['rows'][0]['elements'][0]['status'] == 'OK':
            resultado = {
                "origem": matrix['origin_addresses'][0],
                "destino": matrix['destination_addresses'][0],
                "distancia": matrix['rows'][0]['elements'][0]['distance']['text'],
                "duracao": matrix['rows'][0]['elements'][0]['duration']['text'],
                "duracao_com_transito": matrix['rows'][0]['elements'][0].get('duration_in_traffic', {}).get('text', 'N/A')
            }

            return resultado
        else:
            print(f"Erro ao buscar a rota: {matrix['rows'][0]['elements'][0]['status']}")
            return None

    except googlemaps.exceptions.ApiError as e:
        import traceback

        print(traceback.format_exc())
        print(f"Ocorreu um erro na API do Google Maps: {e}")
        return None
    except Exception as e:
        print(f"Ocorreu um erro inesperado: {e}")
        return None

def format_and_calculate_displacement_cost(cidade_origem, cidade_destino):
    """
    Formata e calcula o custo total da deslocação com base na distância, duração e custo por quilômetro.
    """
    dados_viagem = calcular_distancia_cidades(cidade_origem, cidade_destino)

    custo_total = dados_viagem['distancia'] * 1.5

    report = f"""
Análise da viagem de carro:
De: {dados_viagem['origem']}
Para: {dados_viagem['destino']}
----------------------------------------
Distância: {dados_viagem['distancia']}
Duração (sem trânsito): {dados_viagem['duracao']}
Duração (com trânsito agora): {dados_viagem['duracao_com_transito']}
----------------------------------------
Custo da viagem: R$ {custo_total:.2f}
"""
    return report

if __name__ == "__main__":
    pass