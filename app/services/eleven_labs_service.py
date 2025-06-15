from elevenlabs import ElevenLabs, VoiceSettings
from typing import List
import requests
from datetime import datetime
import re

from app.config.settings import settings


def number_to_words(num):
    """Converte um número inteiro para sua representação por extenso em português"""
    if num == 0:
        return "zero"
    
    # Unidades
    units = ["", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove"]
    # Dezenas
    tens = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
    # Números especiais de 10 a 19
    teens = ["dez", "onze", "doze", "treze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
    # Centenas
    hundreds = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos", "oitocentos", "novecentos"]
    
    def convert_group(n):
        """Converte um grupo de até 3 dígitos"""
        if n == 0:
            return ""
        
        result = []
        
        # Centenas
        if n >= 100:
            if n == 100:
                result.append("cem")
            else:
                result.append(hundreds[n // 100])
            n %= 100
        
        # Dezenas e unidades
        if n >= 20:
            result.append(tens[n // 10])
            if n % 10 != 0:
                result.append(units[n % 10])
        elif n >= 10:
            result.append(teens[n - 10])
        elif n > 0:
            result.append(units[n])
        
        return " e ".join(result)
    
    if num < 1000:
        return convert_group(num)
    
    # Para números maiores que 1000
    parts = []
    
    # Milhões
    if num >= 1000000:
        millions = num // 1000000
        million_text = convert_group(millions)
        if millions == 1:
            parts.append(f"{million_text} milhão")
        else:
            parts.append(f"{million_text} milhões")
        num %= 1000000
    
    # Milhares
    if num >= 1000:
        thousands = num // 1000
        thousand_text = convert_group(thousands)
        if thousands == 1:
            parts.append("mil")
        else:
            parts.append(f"{thousand_text} mil")
        num %= 1000
    
    # Centenas, dezenas e unidades restantes
    if num > 0:
        parts.append(convert_group(num))
    
    return " ".join(parts)

def decimal_to_words(decimal_str):
    """Converte a parte decimal para extenso"""
    # Remove zeros à direita desnecessários
    decimal_str = decimal_str.rstrip('0')
    if not decimal_str:
        return ""
    
    # Para casos como "033" -> "zero zero três" ou decimais pequenos que começam com zeros
    if len(decimal_str) <= 3 and decimal_str.startswith('0'):
        digits = []
        for digit in decimal_str:
            digits.append(number_to_words(int(digit)))
        return " ".join(digits)
    else:
        # Para casos normais, converte o número decimal como inteiro
        return number_to_words(int(decimal_str))

def normalize_numbers_for_tts(text: str) -> str:
    """
    Função universal que converte para extenso:
    - Valores monetários: R$ 15.110,65 -> quinze mil cento e dez reais e sessenta e cinco centavos
    - Porcentagens: 3% -> três porcento | 0,033% -> zero vírgula zero três três porcento
    - Números decimais: 3,14 -> três vírgula quatorze
    """
    
    # 1. MOEDAS: R$ X.XXX,XX
    def replace_currency(match):
        inteiros_str = match.group(1).replace('.', '')
        centavos_str = match.group(2)
        inteiros = int(inteiros_str)
        parts = []
        
        if inteiros > 0:
            inteiros_extenso = number_to_words(inteiros)
            if inteiros == 1:
                parts.append(f"{inteiros_extenso} real")
            else:
                parts.append(f"{inteiros_extenso} reais")
        
        if centavos_str:
            centavos = int(centavos_str)
            if centavos > 0:
                if inteiros > 0:
                    parts.append("e")
                centavos_extenso = number_to_words(centavos)
                if centavos == 1:
                    parts.append(f"{centavos_extenso} centavo")
                else:
                    parts.append(f"{centavos_extenso} centavos")
        
        return ' '.join(parts)
    
    # 2. PORCENTAGENS: X% ou X,XXX%
    def replace_percentage(match):
        inteiro_str = match.group(1)
        decimal_str = match.group(2)
        
        inteiro = int(inteiro_str)
        parts = []
        
        # Converte a parte inteira
        if inteiro > 0:
            parts.append(number_to_words(inteiro))
        else:
            parts.append("zero")
        
        # Converte a parte decimal se existir
        if decimal_str:
            parts.append("vírgula")
            decimal_extenso = decimal_to_words(decimal_str)
            parts.append(decimal_extenso)
        
        parts.append("porcento")
        return " ".join(parts)
    
    # 3. NÚMEROS DECIMAIS: X,XXX (que não sejam porcentagens)
    def replace_decimal(match):
        inteiro_str = match.group(1)
        decimal_str = match.group(2)
        
        inteiro = int(inteiro_str)
        parts = []
        
        parts.append(number_to_words(inteiro))
        parts.append("vírgula")
        
        decimal_extenso = decimal_to_words(decimal_str)
        parts.append(decimal_extenso)
        
        return " ".join(parts)
    
    # Aplica as substituições em ordem:
    
    # 1. Primeiro as moedas
    currency_pattern = r'R\$\s*(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{2}))?'
    text = re.sub(currency_pattern, replace_currency, text)
    
    # 2. Depois as porcentagens
    percentage_pattern = r'(\d+)(?:,(\d+))?%'
    text = re.sub(percentage_pattern, replace_percentage, text)
    
    # 3. Por último os números decimais restantes
    decimal_pattern = r'\b(\d+),(\d+)\b'
    text = re.sub(decimal_pattern, replace_decimal, text)
    
    return text

def normalize_symbols_for_tts(text: str) -> str:

    symbols_to_words = {
        '+': 'mais',
        '-': 'menos',
        '*': 'vezes',
        '/': 'dividido por',
        '=': 'igual a',
        '(': 'abre parênteses',
        ')': 'fecha parênteses',
    }

    for symbol, word in symbols_to_words.items():
        text = text.replace(symbol, f' {word} ')

    return text

def normalize_words_for_tts(text: str) -> str:
    words_to_replace = {
        'WI-FI': 'wifi',
        'wi-fi': 'wifi',
        'wi fi': 'wifi',
    }

    for word, replacement in words_to_replace.items():
        text = text.replace(word, replacement)
    
    return text

def apply_normalizations(text: str) -> str:
    """
    Aplica normalizações de números, símbolos e palavras para o texto.
    """
    text = normalize_numbers_for_tts(text)
    text = normalize_symbols_for_tts(text)
    text = normalize_words_for_tts(text)
    return text

def host_audio(audio_bytes: bytes):
    audio_name = f'audio_eleven_agent_AI_{datetime.now().strftime("%Y%m%d%H%M%S")}.mp3'
    headers = {'filename': audio_name}
    response_hosting = requests.post('https://api-data-automa-system-production.up.railway.app/upload_doc?path=docs&ex=3', headers=headers, data=audio_bytes)

    if response_hosting.status_code == 200:
        return f'https://api-data-automa-system-production.up.railway.app/download_doc/{audio_name}?path=docs&mimetype=mp3'
    else:
        return None


def main(messages: List[str]):
    messages_str = '\n'.join(messages)

    messages_normalized = apply_normalizations(messages_str)

    voice_settings = VoiceSettings(
            stability=0.71,
            similarity_boost=0.5,
            style=0.0,
            use_speaker_boost=True,
            speed=1.2
        )

    eleven_labs = ElevenLabs(api_key=settings.ELEVEN_LABS_API_KEY)
    audio = eleven_labs.text_to_speech.convert(
                text=messages_normalized,
                model_id='eleven_multilingual_v2',
                output_format='mp3_22050_32',
                voice_id='CstacWqMhJQlnfLPxRG4',
                voice_settings=voice_settings
                )

    audio_bytes = b''.join(audio)

    hosted_url = host_audio(audio_bytes)
    
    return hosted_url