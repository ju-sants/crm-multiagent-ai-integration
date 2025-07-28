import re
import json

from app.utils.static import dict_text_normalization

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
        
        # Garante que n está no intervalo válido (0-999)
        if n > 999:
            n = n % 1000
        
        result = []
        
        # Centenas
        if n >= 100:
            hundreds_digit = n // 100
            if n == 100:
                result.append("cem")
            elif hundreds_digit < len(hundreds):
                result.append(hundreds[hundreds_digit])
            n %= 100
        
        # Dezenas e unidades
        if n >= 20:
            tens_digit = n // 10
            if tens_digit < len(tens):
                result.append(tens[tens_digit])
            if n % 10 != 0:
                units_digit = n % 10
                if units_digit < len(units):
                    result.append(units[units_digit])
        elif n >= 10:
            teens_index = n - 10
            if teens_index < len(teens):
                result.append(teens[teens_index])
        elif n > 0:
            if n < len(units):
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

def parse_abbreviated_currency(match: re.Match):
    """Processa valores monetários abreviados como 'R$ 10 mil' ou 'R$ 1,5 milhão'"""
    amount_str = match.group(1).replace(',', '.')  # Converte vírgula decimal para ponto
    unit = match.group(2).lower()
    
    try:
        amount = float(amount_str)
    except ValueError:
        return match.group(0)  # Retorna o texto original se não conseguir converter
    
    # Converte para o valor real baseado na unidade
    if unit in ['mil']:
        total_value = amount * 1000
    elif unit in ['milhão', 'milhões']:
        total_value = amount * 1000000
    elif unit in ['bilhão', 'bilhões']:
        total_value = amount * 1000000000
    else:
        return match.group(0)  # Unidade não reconhecida
    
    # Separa parte inteira e decimal
    integer_part = int(total_value)
    decimal_part = round((total_value - integer_part) * 100)  # Centavos
    
    parts = []
    
    # Parte inteira
    if integer_part > 0:
        integer_extenso = number_to_words(integer_part)
        if integer_part == 1:
            parts.append(f"{integer_extenso} real")
        else:
            parts.append(f"{integer_extenso} reais")
    
    # Parte decimal (centavos)
    if decimal_part > 0:
        if integer_part > 0:
            parts.append("e")
        decimal_extenso = number_to_words(decimal_part)
        if decimal_part == 1:
            parts.append(f"{decimal_extenso} centavo")
        else:
            parts.append(f"{decimal_extenso} centavos")
    
    return ' '.join(parts)

def normalize_dates_for_tts(text: str) -> str:
    """
    Normaliza datas em vários formatos para TTS, sempre convertendo para DD/MM/YYYY em palavras:
    
    Formatos suportados:
    - DD/MM/YYYY, DD/MM/YY -> dia DD de mês de YYYY
    - DD-MM-YYYY, DD-MM-YY -> dia DD de mês de YYYY  
    - DD.MM.YYYY, DD.MM.YY -> dia DD de mês de YYYY
    - YYYY/MM/DD -> dia DD de mês de YYYY
    - YYYY-MM-DD -> dia DD de mês de YYYY (ISO)
    - YYYY.MM.DD -> dia DD de mês de YYYY
    - MM/DD/YYYY -> dia DD de mês de YYYY (americano)
    - MM-DD-YYYY -> dia DD de mês de YYYY
    - MM.DD.YYYY -> dia DD de mês de YYYY
    - DD MMM YYYY -> dia DD de mês de YYYY (ex: 15 jan 2024)
    - MMM DD, YYYY -> dia DD de mês de YYYY (ex: jan 15, 2024)
    - DD de MMM de YYYY -> já em português
    """
    
    months = {
        1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
        5: "maio", 6: "junho", 7: "julho", 8: "agosto",
        9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"
    }
    
    # Abreviações de meses em português e inglês
    month_abbrev = {
        'jan': 1, 'fev': 2, 'mar': 3, 'abr': 4, 'mai': 5, 'jun': 6,
        'jul': 7, 'ago': 8, 'set': 9, 'out': 10, 'nov': 11, 'dez': 12,
        'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
        'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
        'janeiro': 1, 'fevereiro': 2, 'março': 3, 'abril': 4, 'maio': 5, 'junho': 6,
        'julho': 7, 'agosto': 8, 'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12
    }
    
    def format_date_to_words(day, month, year):
        """Converte componentes de data para formato DD de MMM de YYYY"""
        day_int = int(day) if isinstance(day, str) else day
        
        # Processa mês
        if isinstance(month, str):
            if month.isdigit():
                month_int = int(month)
            else:
                month_int = month_abbrev.get(month.lower(), 1)
        else:
            month_int = month
            
        year_int = int(year) if isinstance(year, str) else year
        
        # Trata anos de 2 dígitos (assume século 21 se <= 30, senão século 20)
        if year_int <= 30:
            year_int += 2000
        elif year_int < 100:
            year_int += 1900
        
        day_words = number_to_words(day_int)
        month_name = months.get(month_int, f"mês {month_int}")
        year_words = number_to_words(year_int)
        
        return f"dia {day_words} de {month_name} de {year_words}"
    
    # Padrões de data em ordem de especificidade (mais específicos primeiro)
    patterns = [
        # DD de MMM de YYYY (já em português - manter)
        (r'\bdia\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{2,4})\b', 
         lambda m: format_date_to_words(m.group(1), m.group(2), m.group(3))),
        
        # MMM DD, YYYY (formato americano com vírgula)
        (r'\b(\w{3,9})\s+(\d{1,2}),\s+(\d{2,4})\b', 
         lambda m: format_date_to_words(m.group(2), m.group(1), m.group(3))),
        
        # DD MMM YYYY (europeu)
        (r'\b(\d{1,2})\s+(\w{3,9})\s+(\d{2,4})\b', 
         lambda m: format_date_to_words(m.group(1), m.group(2), m.group(3))),
        
        # YYYY/MM/DD
        (r'\b(\d{4})/(\d{1,2})/(\d{1,2})\b', 
         lambda m: format_date_to_words(m.group(3), m.group(2), m.group(1))),
        
        # YYYY-MM-DD (formato ISO)
        (r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b', 
         lambda m: format_date_to_words(m.group(3), m.group(2), m.group(1))),
        
        # YYYY.MM.DD
        (r'\b(\d{4})\.(\d{1,2})\.(\d{1,2})\b', 
         lambda m: format_date_to_words(m.group(3), m.group(2), m.group(1))),
        
        # MM/DD/YYYY (americano - assumindo que mês vem primeiro quando > 12)
        (r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b', 
         lambda m: format_date_to_words(m.group(2), m.group(1), m.group(3)) 
                  if int(m.group(1)) > 12 
                  else format_date_to_words(m.group(1), m.group(2), m.group(3))),
        
        # MM-DD-YYYY (americano)
        (r'\b(\d{1,2})-(\d{1,2})-(\d{2,4})\b', 
         lambda m: format_date_to_words(m.group(2), m.group(1), m.group(3)) 
                  if int(m.group(1)) > 12 
                  else format_date_to_words(m.group(1), m.group(2), m.group(3))),
        
        # MM.DD.YYYY (americano)
        (r'\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b', 
         lambda m: format_date_to_words(m.group(2), m.group(1), m.group(3)) 
                  if int(m.group(1)) > 12 
                  else format_date_to_words(m.group(1), m.group(2), m.group(3))),
        
        # DD/MM/YYYY ou DD/MM/YY (brasileiro - padrão)
        (r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b', 
         lambda m: format_date_to_words(m.group(1), m.group(2), m.group(3))),
        
        # DD-MM-YYYY ou DD-MM-YY (brasileiro)
        (r'\b(\d{1,2})-(\d{1,2})-(\d{2,4})\b', 
         lambda m: format_date_to_words(m.group(1), m.group(2), m.group(3))),
        
        # DD.MM.YYYY ou DD.MM.YY (brasileiro)
        (r'\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b', 
         lambda m: format_date_to_words(m.group(1), m.group(2), m.group(3))),
    ]
    
    for pattern, replacement_func in patterns:
        text = re.sub(pattern, replacement_func, text, flags=re.IGNORECASE)
    
    return text

def normalize_times_for_tts(text: str) -> str:
    """
    Normaliza horários em vários formatos para TTS:
    
    Formatos suportados:
    - HH:MM -> X horas e Y minutos
    - HH:MM:SS -> X horas Y minutos e Z segundos
    - HHhMM -> X horas e Y minutos
    - HHhMMmSSs -> X horas Y minutos e Z segundos
    - HH:MM AM/PM -> X horas e Y minutos da manhã/tarde/noite
    - Casos especiais: meio-dia, meia-noite, hora cheia
    """
    
    def format_time_to_words(hours, minutes=0, seconds=0, period=None):
        """Converte componentes de horário para extenso"""
        hours_int = int(hours)
        minutes_int = int(minutes) if minutes else 0
        seconds_int = int(seconds) if seconds else 0
        
        # Converte AM/PM para 24h se necessário
        if period:
            period = period.upper()
            if period in ['PM', 'P.M.'] and hours_int != 12:
                hours_int += 12
            elif period in ['AM', 'A.M.'] and hours_int == 12:
                hours_int = 0
        
        # Casos especiais
        if hours_int == 0 and minutes_int == 0:
            return "meia-noite"
        elif hours_int == 12 and minutes_int == 0:
            return "meio-dia"
        
        result = []
        
        # Horas
        if hours_int == 1:
            result.append("uma hora")
        elif hours_int > 1:
            hours_words = number_to_words(hours_int)
            result.append(f"{hours_words} horas")
        elif hours_int == 0:
            result.append("zero hora")
        
        # Minutos
        if minutes_int > 0:
            if hours_int > 0:
                result.append("e")
            
            if minutes_int == 1:
                result.append("um minuto")
            else:
                minutes_words = number_to_words(minutes_int)
                result.append(f"{minutes_words} minutos")
        
        # Segundos
        if seconds_int > 0:
            if hours_int > 0 or minutes_int > 0:
                result.append("e")
            
            if seconds_int == 1:
                result.append("um segundo")
            else:
                seconds_words = number_to_words(seconds_int)
                result.append(f"{seconds_words} segundos")
        
        # Período do dia (contexto brasileiro)
        if period:
            time_context = get_time_context(hours_int)
            if time_context:
                result.append(time_context)
        
        return " ".join(result)
    
    def get_time_context(hour):
        """Retorna contexto do período do dia"""
        if 5 <= hour < 12:
            return "da manhã"
        elif 12 <= hour < 18:
            return "da tarde"
        elif 18 <= hour < 24:
            return "da noite"
        else:  # 0-4h
            return "da madrugada"
    
    # Padrões de horário em ordem de especificidade
    patterns = [
        # HH:MM:SS AM/PM
        (r'\b(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM|A\.M\.|P\.M\.)\b',
         lambda m: format_time_to_words(m.group(1), m.group(2), m.group(3), m.group(4))),
        
        # HH:MM AM/PM
        (r'\b(\d{1,2}):(\d{2})\s*(AM|PM|A\.M\.|P\.M\.)\b',
         lambda m: format_time_to_words(m.group(1), m.group(2), None, m.group(3))),
        
        # HH.MM.SS AM/PM
        (r'\b(\d{1,2})\.(\d{2})\.(\d{2})\s*(AM|PM|A\.M\.|P\.M\.)\b',
         lambda m: format_time_to_words(m.group(1), m.group(2), m.group(3), m.group(4))),
        
        # HH.MM AM/PM
        (r'\b(\d{1,2})\.(\d{2})\s*(AM|PM|A\.M\.|P\.M\.)\b',
         lambda m: format_time_to_words(m.group(1), m.group(2), None, m.group(3))),
        
        # HHhMMmSSs
        (r'\b(\d{1,2})h(\d{2})m(\d{2})s\b',
         lambda m: format_time_to_words(m.group(1), m.group(2), m.group(3))),
        
        # HHhMMs
        (r'\b(\d{1,2})h(\d{2})s\b',
         lambda m: format_time_to_words(m.group(1), 0, m.group(2))),
        
        # HHhMM.SS (com segundos após ponto)
        (r'\b(\d{1,2})h(\d{2})\.(\d{2})\b',
         lambda m: format_time_to_words(m.group(1), m.group(2), m.group(3))),
        
        # HHhMM ou HHhMMm
        (r'\b(\d{1,2})h(\d{2})m?\b',
         lambda m: format_time_to_words(m.group(1), m.group(2))),
        
        # HH.MM.SS (formato com pontos)
        (r'\b(\d{1,2})\.(\d{2})\.(\d{2})\b',
         lambda m: format_time_to_words(m.group(1), m.group(2), m.group(3))),
        
        # HH.MM (formato com ponto)
        (r'\b(\d{1,2})\.(\d{2})\b',
         lambda m: format_time_to_words(m.group(1), m.group(2))),
        
        # HHh (hora cheia)
        (r'\b(\d{1,2})h\b',
         lambda m: format_time_to_words(m.group(1), 0)),
        
        # HH:MM:SS (24h)
        (r'\b(\d{1,2}):(\d{2}):(\d{2})\b',
         lambda m: format_time_to_words(m.group(1), m.group(2), m.group(3))),
        
        # HH:MM (24h)
        (r'\b(\d{1,2}):(\d{2})\b',
         lambda m: format_time_to_words(m.group(1), m.group(2))),
    ]
    
    # Primeiro, trata casos especiais escritos
    special_cases = {
        r'\bmeia-?noite\b': 'meia-noite',
        r'\bmeio-?dia\b': 'meio-dia',
        r'\b(\d{1,2})\s*da\s*manhã\b': lambda m: format_time_to_words(m.group(1)) + " da manhã",
        r'\b(\d{1,2})\s*da\s*tarde\b': lambda m: format_time_to_words(m.group(1)) + " da tarde",
        r'\b(\d{1,2})\s*da\s*noite\b': lambda m: format_time_to_words(m.group(1)) + " da noite",
        r'\b(\d{1,2})\s*da\s*madrugada\b': lambda m: format_time_to_words(m.group(1)) + " da madrugada",
    }
    
    # Aplica casos especiais primeiro
    for pattern, replacement in special_cases.items():
        if callable(replacement):
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        else:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    
    # Aplica padrões de horário
    for pattern, replacement_func in patterns:
        text = re.sub(pattern, replacement_func, text, flags=re.IGNORECASE)
    
    return text

def normalize_license_plates_for_tts(text: str) -> str:
    """
    Normaliza placas de veículos brasileiras para TTS:
    - XXX0000 -> X X X número número número número
    - XXX-0000 -> X X X hífen número número número número  
    - XXX0X00 -> X X X número X número número (Mercosul)
    - XXX-0X00 -> X X X hífen número X número número (Mercosul com hífen)
    """
    
    def normalize_plate(match):
        """Normaliza uma placa individual"""
        plate = match.group(0).upper()
        result = []
        
        for char in plate:
            if char.isalpha():
                result.append(char.upper())
            elif char.isdigit():
                result.append(number_to_words(int(char)))
            elif char == '-':
                result.append(' ')
        
        return ' '.join(result)
    
    # Padrões de placas brasileiras
    patterns = [
        # Placa Mercosul com hífen: XXX-0X00
        r'\b[A-Za-z]{3}-\d[A-Za-z]\d{2}\b',
        
        # Placa Mercosul sem hífen: XXX0X00  
        r'\b[A-Za-z]{3}\d[A-Za-z]\d{2}\b',
        
        # Placa antiga com hífen: XXX-0000
        r'\b[A-Za-z]{3}-\d{4}\b',
        
        # Placa antiga sem hífen: XXX0000
        r'\b[A-Za-z]{3}\d{4}\b',
    ]
    
    for pattern in patterns:
        text = re.sub(pattern, normalize_plate, text)
    
    return text

def normalize_numbers_for_tts(text: str) -> str:
    """
    Função universal que converte para extenso:
    - Valores monetários: R$ 15.110,65 -> quinze mil cento e dez reais e sessenta e cinco centavos
    - Valores abreviados: R$ 10 mil -> dez mil reais | R$ 1,5 milhão -> um milhão e quinhentos mil reais
    - Porcentagens: 3% -> três porcento | 0,033% -> zero vírgula zero três três porcento
    - Números decimais: 3,14 -> três vírgula quatorze
    """
    
    # 1. MOEDAS ABREVIADAS: R$ X mil/milhão/bilhão
    abbreviated_currency_pattern = r'R\$\s*([0-9]+(?:[,.][0-9]+)?)\s+(mil|milhão|milhões|bilhão|bilhões)'
    text = re.sub(abbreviated_currency_pattern, parse_abbreviated_currency, text, flags=re.IGNORECASE)
    
    # 2. MOEDAS TRADICIONAIS: R$ X.XXX,XX
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
    
    currency_pattern = r'R\$\s*(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{2}))?'
    text = re.sub(currency_pattern, replace_currency, text)
    
    # 3. PORCENTAGENS: X% ou X,XXX%
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
    
    percentage_pattern = r'(\d+)(?:,(\d+))?%'
    text = re.sub(percentage_pattern, replace_percentage, text)
    
    # 4. NÚMEROS DECIMAIS: X,XXX (que não sejam porcentagens)
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
    
    decimal_pattern = r'\b(\d+),(\d+)\b'
    text = re.sub(decimal_pattern, replace_decimal, text)
    
    return text

def normalize_symbols_for_tts(text: str) -> str:
    symbols_to_words = {
        '+': 'mais',
        '*': 'vezes',
        '/': 'dividido por',
        '=': 'igual a',
        '(': 'abre parênteses',
        ')': 'fecha parênteses',
    }
    
    # Para cada símbolo (exceto hífen)
    for symbol, word in symbols_to_words.items():
        text = text.replace(symbol, f' {word} ')
    
    text = re.sub(r'(?<=\s)-(?=\s)', ' menos ', text)
    text = re.sub(r'(?<=\d)\s*-\s*(?=\d)', ' menos ', text)
    
    return text

def normalize_words_for_tts(text: str) -> str:
    text = re.sub(r'wi[\s\-_.]*fi', 'wifi', text, flags=re.IGNORECASE)
    text = re.sub(r'\bapp\b', 'aplicativo', text, flags=re.IGNORECASE)

    for key, value in dict_text_normalization.items():
        text = text.replace(key, value)

    return text

def normalize_bar_for_tts(text: str) -> str:
    return re.sub(r'\b\w+\/\w+\b', lambda m: m.group().replace('/', ' e '), text)

def apply_normalizations(text: str) -> str:
    """
    Aplica todas as normalizações para TTS: números, símbolos, palavras, datas e placas.
    """
    # 1. Mais específicos primeiro
    text = normalize_numbers_for_tts(text)
    text = normalize_dates_for_tts(text)
    text = normalize_times_for_tts(text)
    text = normalize_license_plates_for_tts(text)
    
    # 2. Símbolos e palavras
    text = normalize_words_for_tts(text)
    text = normalize_symbols_for_tts(text)
    text = normalize_bar_for_tts(text)

    return text