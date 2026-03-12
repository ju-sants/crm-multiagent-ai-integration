"""
Benchmark Report Generator — LLM-powered cross-analysis of benchmark results.

Takes completed benchmark data (rankings, per-run evaluations, timing, errors)
and produces a structured natural-language report with:
  - Best models per agent/scenario
  - Model limitations and failure patterns
  - Concrete recommendations
  - Suggested re-tests for statistical confidence
"""

import json
from app.config.llm_config import create_llm
from app.core.logger import get_logger

logger = get_logger(__name__)

REPORT_SYSTEM_PROMPT = """Você é um analista de performance de modelos de IA. Seu trabalho é analisar resultados de benchmarks de agentes de IA (chatbot de atendimento WhatsApp) e produzir um relatório profissional em linguagem natural.

## CONTEXTO
O sistema testa diferentes modelos de LLM executando agentes (CommunicationAgent, StrategicAdvisor, etc.) em cenários sintéticos. Cada run produz:
- Score de qualidade (0-10) via discriminator com 5 dimensões
- Tempo de execução
- Status (success/error) 
- Avaliação detalhada com dimensões: factual_accuracy, structural_compliance, tone_style, rule_adherence, business_alignment

## SUA TAREFA
Analise os dados do benchmark e produza um relatório em MARKDOWN com as seguintes seções:

### 1. 📊 Resumo Executivo
Visão geral rápida: quantos runs, quais agentes/modelos/cenários, e a conclusão principal em 2-3 frases.

### 2. 🏆 Ranking de Modelos
Para cada modelo testado: score médio, tempo médio, pontos fortes, pontos fracos. Destaque o melhor modelo geral e o melhor custo-benefício (qualidade vs velocidade).

### 3. 🔍 Análise Cruzada (Modelo × Agente × Cenário)
Identifique padrões:
- Qual modelo se sai melhor com cada agente?
- Algum modelo é consistentemente fraco em um cenário específico?
- Há combinações surpreendentes (modelo barato que performa bem em certo agente)?

### 4. ⚠️ Limitações e Padrões de Falha
- Modelos que alucinam mais (factual_accuracy baixo)
- Modelos que geram respostas longas demais (structural_compliance baixo)
- Modelos com tom inadequado (tone_style baixo)
- Padrões de erro (timeouts, rate limits, crashes)

### 5. ✅ Recomendações
- Modelo recomendado para produção por agente
- Trade-offs explícitos (ex: "Modelo X é 2x mais lento mas 15% melhor em qualidade")
- Configurações sugeridas (temperatura, top_p, max_tokens)

### 6. 🎛️ Análise de Parâmetros LLM
Se os runs incluem informação de parâmetros (temperature, top_p, max_tokens):
- Como a variação de temperatura afeta score e consistência para cada modelo?
- Existe um sweet-spot de parâmetros por modelo/agente?
- Recomende a config ideal de parâmetros por modelo

### 6.1 💰 Análise de Consumo de Tokens
Se os dados incluem informação de tokens (agent_tokens, eval_tokens):
- Consumo médio de tokens por modelo (prompt + completion)
- Proporção de tokens do agente vs tokens do avaliador
- Modelos mais eficientes (melhor score/token)
- Estimativa de custo relativo entre modelos (baseado no consumo)
- Modelos com respostas desnecessariamente longas vs concisos

### 7. 🔄 Re-testes Sugeridos
Sugira re-testes específicos para melhorar a confiança estatística:
- Combinações que tiveram poucas iterações (< 3)
- Modelos que ficaram próximos no ranking (diferença < 0.5 no score)
- Cenários onde houve alta variância entre iterações
- Parâmetros que merecem teste mais granular
- Formato: "Rodar [Agente] com [Modelo] no cenário [X], temp=[valores], 10 iterações" + justificativa

### 8. 📦 Configurações Recomendadas para Re-teste
Gere blocos JSON importáveis para os re-testes sugeridos. Formato:
```json
{
  "mode": "matrix",
  "agents": ["AgenteName"],
  "models": ["model/key"],
  "scenarios": ["scenario_name"],
  "iterations": 5,
  "model_params": {
    "model/key": {"temperature": [0.1, 0.3, 0.5]}
  }
}
```
Cada bloco deve ser um benchmark completo pronto para importar.

### 9. 📈 Insights Adicionais
Qualquer observação estatística relevante que não se encaixa nas seções acima.

## REGRAS
- Use dados concretos (números, percentuais) para sustentar cada afirmação
- Seja direto e acionável — o leitor quer saber O QUE FAZER, não teoria
- Se os dados são insuficientes para uma conclusão, diga explicitamente
- Considere que scores >= 7 são bons, >= 5 são aceitáveis, < 5 são ruins
- Considere que menos de 3 iterações por combinação é estatisticamente fraco
- Escreva em português brasileiro
- Formate em markdown limpo e legível"""


def generate_report(benchmark_data: dict, model: str = None) -> dict:
    """Generate a deep analysis report from benchmark results.

    Args:
        benchmark_data: A single benchmark result dict (with runs, rankings, config)
        model: LLM model to use for report generation

    Returns:
        Dict with 'report' (markdown string) and metadata
    """
    model_name = model or 'xai/grok-3-mini-fast'
    llm = create_llm(model_name, temperature=0.3)

    # Build a compact data summary for the LLM
    data_summary = _build_data_summary(benchmark_data)

    messages = [
        {"role": "system", "content": REPORT_SYSTEM_PROMPT},
        {"role": "user", "content": f"""Analise os seguintes resultados de benchmark e produza o relatório completo:

{data_summary}"""},
    ]

    try:
        response = llm.invoke(messages)
        report_md = response.content.strip()

        # Clean markdown wrapping if present
        if report_md.startswith('```markdown'):
            report_md = report_md[len('```markdown'):].strip()
        if report_md.startswith('```md'):
            report_md = report_md[len('```md'):].strip()
        if report_md.endswith('```'):
            report_md = report_md[:-3].strip()

        return {
            "report": report_md,
            "model_used": model_name,
            "benchmark_run_id": benchmark_data.get("run_id"),
            "benchmark_type": benchmark_data.get("type"),
        }

    except Exception as e:
        logger.error(f"Report generation failed: {e}", exc_info=True)
        return {
            "report": f"Erro ao gerar relatório: {str(e)[:300]}",
            "error": str(e),
            "model_used": model_name,
        }


def generate_cross_report(benchmark_results: list, model: str = None) -> dict:
    """Generate a cross-analysis report comparing multiple benchmark runs.

    Args:
        benchmark_results: List of benchmark result dicts
        model: LLM model to use for report generation

    Returns:
        Dict with 'report' (markdown string) and metadata
    """
    model_name = model or 'xai/grok-3-mini-fast'
    llm = create_llm(model_name, temperature=0.3)

    # Merge all runs and build combined summary
    all_runs = []
    run_ids = []
    for bm in benchmark_results:
        run_ids.append(bm.get("run_id", "?"))
        all_runs.extend(bm.get("runs", []))

    if not all_runs:
        return {
            "report": "Nenhum dado de benchmark disponível para análise.",
            "model_used": model_name,
        }

    # Build merged rankings
    from dev_chat.benchmarks import _aggregate_matrix_rankings
    merged_rankings = _aggregate_matrix_rankings(all_runs)

    merged_data = {
        "type": "cross_analysis",
        "source_runs": run_ids,
        "total_runs": len(all_runs),
        "runs": all_runs,
        "rankings": merged_rankings,
    }

    data_summary = _build_data_summary(merged_data)

    messages = [
        {"role": "system", "content": REPORT_SYSTEM_PROMPT},
        {"role": "user", "content": f"""Analise os seguintes resultados COMBINADOS de {len(benchmark_results)} benchmarks e produza o relatório completo.
Esta é uma análise cruzada que agrega múltiplos runs para maior confiança estatística.

{data_summary}"""},
    ]

    try:
        response = llm.invoke(messages)
        report_md = response.content.strip()

        if report_md.startswith('```markdown'):
            report_md = report_md[len('```markdown'):].strip()
        if report_md.startswith('```md'):
            report_md = report_md[len('```md'):].strip()
        if report_md.endswith('```'):
            report_md = report_md[:-3].strip()

        return {
            "report": report_md,
            "model_used": model_name,
            "source_run_ids": run_ids,
            "total_runs_analyzed": len(all_runs),
        }

    except Exception as e:
        logger.error(f"Cross-report generation failed: {e}", exc_info=True)
        return {
            "report": f"Erro ao gerar relatório cruzado: {str(e)[:300]}",
            "error": str(e),
            "model_used": model_name,
        }


def _build_data_summary(benchmark_data: dict) -> str:
    """Build a compact textual summary of benchmark data for the LLM."""
    lines = []

    # Config
    config = benchmark_data.get("config", {})
    bm_type = benchmark_data.get("type", "unknown")
    lines.append(f"## CONFIGURAÇÃO DO BENCHMARK")
    lines.append(f"- Tipo: {bm_type}")
    if config:
        lines.append(f"- Agentes: {config.get('agents', 'N/A')}")
        lines.append(f"- Modelos: {config.get('models', 'N/A')}")
        lines.append(f"- Cenários: {config.get('scenarios', 'N/A')}")
        lines.append(f"- Iterações por combo: {config.get('iterations', 'N/A')}")
        lines.append(f"- Total de runs: {config.get('total_runs', len(benchmark_data.get('runs', [])))}")
        mp = config.get('model_params')
        if mp:
            lines.append(f"- Parâmetros por modelo: {json.dumps(mp, ensure_ascii=False)}")

    if benchmark_data.get("source_runs"):
        lines.append(f"- Benchmarks fonte: {benchmark_data['source_runs']}")
        lines.append(f"- Total de runs combinados: {benchmark_data.get('total_runs', '?')}")

    # Rankings
    rankings = benchmark_data.get("rankings", {})
    if rankings:
        lines.append(f"\n## RANKINGS AGREGADOS")
        for rank_type, rank_data in rankings.items():
            lines.append(f"\n### {rank_type}")
            for key, stats in rank_data.items():
                score_str = f"score={stats.get('avg_score', '?')}" if 'avg_score' in stats else "score=N/A"
                time_str = f"time={stats.get('avg_time', '?')}s" if 'avg_time' in stats else ""
                range_str = ""
                if 'min_score' in stats and 'max_score' in stats:
                    range_str = f"range=[{stats['min_score']}-{stats['max_score']}]"
                tok_parts = []
                if 'avg_agent_tokens' in stats:
                    tok_parts.append(f"avg_agent_tok={stats['avg_agent_tokens']}")
                if 'total_agent_tokens' in stats:
                    tok_parts.append(f"total_agent_tok={stats['total_agent_tokens']}")
                if 'avg_eval_tokens' in stats:
                    tok_parts.append(f"avg_eval_tok={stats['avg_eval_tokens']}")
                tok_str_r = " ".join(tok_parts)
                lines.append(f"  {key}: {score_str} {time_str} runs={stats.get('runs', '?')} errors={stats.get('errors', 0)} {range_str} {tok_str_r}".rstrip())

    # Per-run details (compact)
    runs = benchmark_data.get("runs", [])
    if runs:
        lines.append(f"\n## DETALHES POR RUN ({len(runs)} runs)")
        for r in runs:
            status = r.get("status", "?")
            model = r.get("model", "?")
            agent = r.get("agent", "?")
            scenario = r.get("scenario", "?")
            iteration = r.get("iteration", "?")
            duration = r.get("duration_s", "?")

            eval_data = r.get("evaluation", {})
            overall = eval_data.get("overall_score", "N/A")

            # Extract per-dimension scores
            dims = eval_data.get("dimensions", eval_data.get("stages", {}))
            dim_scores = {}
            for dim_key, dim_val in dims.items():
                if isinstance(dim_val, dict) and "score" in dim_val:
                    dim_scores[dim_key] = dim_val["score"]

            dim_str = " ".join(f"{k}={v}" for k, v in dim_scores.items()) if dim_scores else ""

            penalties = eval_data.get("penalties_applied", [])
            pen_str = f"penalties=[{'; '.join(str(p)[:60] for p in penalties[:3])}]" if penalties else ""

            hallucinations = eval_data.get("hallucinations", [])
            hal_str = f"hallucinations={len(hallucinations)}" if hallucinations else ""

            error_str = f"error={r['error'][:80]}" if r.get("error") else ""

            tokens = r.get("tokens", {})
            tok_str = f"agent_tok={tokens.get('total', '?')}" if tokens else ""

            eval_tok = (eval_data.get("_meta") or {}).get("eval_token_usage", {})
            eval_tok_str = f"eval_tok={eval_tok.get('total', '?')}" if eval_tok else ""

            # LLM params used for this run
            llm_p = r.get("llm_params", {})
            llm_str = " ".join(f"{k}={v}" for k, v in llm_p.items() if v is not None) if llm_p else ""

            line = f"  [{status}] {agent}/{model}/{scenario} #{iteration} — score={overall} {duration}s {dim_str} {tok_str} {eval_tok_str} {llm_str} {pen_str} {hal_str} {error_str}".strip()
            lines.append(line)

    return "\n".join(lines)
