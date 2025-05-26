from pathlib import Path

def obter_caminho_projeto():
    """Encontra a raiz do projeto"""
    current_file = Path(__file__).resolve()
    for parent in [current_file] + list(current_file.parents):
        if (parent / 'main.py').exists():
            return parent
    return Path.cwd()