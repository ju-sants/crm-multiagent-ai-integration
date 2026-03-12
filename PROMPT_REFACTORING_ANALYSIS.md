# Análise e Refatoração de Prompts — CRM Multi-Agent AI

## 1. DIAGNÓSTICO: O que o histórico de commits revela

O git log dos prompts conta uma história clara de **"reforço reativo"** — onde cada problema
comportamental do modelo leva a mais texto nos prompts em vez de simplificação:

| Commit | Problema Real | Ação Tomada (anti-padrão) |
|--------|---------------|---------------------------|
| `e9cdc82` → `7469e45` | CommunicationAgent usa tiques verbais | Adicionou regras SEVERAS → Reverteu porque "vai ter tiques do mesmo jeito" |
| `6354d03` | Agente reafirma contexto no início das frases | Adicionou mais uma regra textual proibindo |
| `20dabbc` | Agente ignora disclosure_checklist | Adicionou lógica proativa no LOGIC_FLOW |
| `1f05e98` | Agente não encaminha conversa para fechamento | Adicionou "Closing Mindset" com mais pseudo-código |
| `a29a218` | Agente não segue processos | Explicitou mais pseudo-código no LOGIC_FLOW |
| `df70b35` + `31544fe` | Agente apresenta apenas 1 plano | "Reforçando" com mais instruções repetidas |

**Resultado:** agents.yaml cresceu de 441 → 940 linhas (113% de aumento) com degradação progressiva de qualidade.

---

## 2. PROBLEMAS FUNDAMENTAIS IDENTIFICADOS

### 2.1 Pseudo-código em Prompts (Anti-padrão #1)

Os `<LOGIC_FLOW>` usam pseudo-código tipo:
```
SET is_plan_acceptable = true
IF strategic_plan IS GENERIC:
  SET is_plan_acceptable = false
  GOTO ETAPA_6
ENDIF
```

**Por que isso é ruim:**
- LLMs não **executam** código — eles **interpretam** linguagem natural
- Pseudo-código consome ~3x mais tokens que linguagem natural equivalente
- Cria ambiguidade: o modelo não sabe se deve "simular" a execução ou apenas interpretar
- GROKs-mini-fast (modelo primário) é especialmente fraco para raciocínio multi-step codificado

**Alternativa:** Instruções em linguagem natural com decision tables claras.

### 2.2 Redundância Agent↔Task (Anti-padrão #2)

O agente (backstory) contém TODA a lógica, e a task (description) diz "siga a lógica do backstory".
Isso causa:
- **Dobro de tokens** sem nenhum valor adicional
- Confusão sobre qual instrução tem prioridade
- CrewAI concatena system prompt (agent) + user prompt (task) — cada palavra paga duas vezes

**Alternativa:** Agent = QUEM (identidade + constraints). Task = O QUÊ (instrução concreta + dados).

### 2.3 Verbosidade Compensatória (Anti-padrão #3)

Quando o modelo falha, a tendência foi adicionar mais texto. Exemplos:
- "É ESTRITAMENTE PROIBIDO" (aparece 6x nos prompts)
- "É OBRIGATÓRIO" (aparece 8x)
- "NUNCA", "DEVE", "SEMPRE" em capslock

**Por que isso é ruim:**
- Cada ênfase adicional dilui as anteriores
- Modelos menores (grok-3-mini-fast) processam enfatizações de forma errática
- Cria um tom "gritante" que compete com as instruções reais

**Alternativa:** Fewer, sharper constraints. Se preciso enfatizar, use uma seção `## CRITICAL` com no máximo 3 itens.

### 2.4 Overloaded Agents (Anti-padrão #4)

O CommunicationAgent tem ~15 regras, incluindo:
- Gestão de catálogo
- Atualização de disclosure_checklist
- Detecção de follow-up
- Anti-repetição
- Proatividade com closing mindset
- Verificação de human intervention

**Cada responsabilidade adicional reduz a performance em TODAS as responsabilidades.**

### 2.5 Output Schemas Gigantes (Anti-padrão #5)

Os `expected_output` são exemplos JSON completos com ~30-50 linhas de campos descritivos.
Isso come tokens sem necessidade — o modelo precisa de um SHAPE, não de documentação.

---

## 3. ESTRATÉGIA DE REFATORAÇÃO

### Princípio 1: Natural Language > Pseudo-Code
```
# ANTES (8 linhas, ~120 tokens)
SET is_plan_acceptable = true
IF strategic_plan IS NULL or EMPTY:
  SET is_plan_acceptable = false
  GOTO ETAPA_6
ENDIF

# DEPOIS (2 linhas, ~30 tokens)
Se não existe plano estratégico, retorne is_plan_acceptable=false imediatamente.
```

### Princípio 2: Separação Agent/Task
- **Agent backstory:** Identidade + 5-7 constraints máximo
- **Task description:** Passos concretos + dados + output format

### Princípio 3: Decision Tables > Nested IF/ELSE
```
# ANTES (20 linhas de IFs)
IF operational_context IS BUDGET AND data is missing → QUALIFICATION
ELSE IF operational_context IS BUDGET AND data present → PRESENTATION  
ELSE → RESOLUTION

# DEPOIS (tabela clara)
| Contexto     | Dados de qualificação | Modo          |
|-------------|----------------------|---------------|
| BUDGET       | Faltando             | QUALIFICATION |
| BUDGET       | Coletados            | PRESENTATION  |
| SUPPORT/CS   | Qualquer             | RESOLUTION    |
```

### Princípio 4: Constraint-Based > Instruction-Based
```
# ANTES: 10 linhas explicando como usar a tool
# DEPOIS:
CONSTRAINT: Toda informação factual DEVE vir da knowledge_service_tool. Dado inventado = falha crítica.
```

### Princípio 5: One Good Example > Many Rules
O expected_output já serve como few-shot example. Torná-lo mais conciso mas mantê-lo como referência.

---

## 4. MÉTRICAS ESPERADAS

| Métrica | Antes | Depois | Redução |
|---------|-------|--------|---------|
| agents.yaml (linhas) | 940 | ~400 | ~57% |
| tasks.yaml (linhas) | 631 | ~400 | ~37% |
| Tokens estimados por chamada* | ~4000-6000 | ~1500-2500 | ~55% |
| Regras por agente (média) | 12 | 5-7 | ~50% |

*Tokens de prompt do sistema (backstory + task description), sem contar os dados dinâmicos.

---

## 5. NOTAS DE IMPLEMENTAÇÃO

Os arquivos refatorados mantêm:
- Todas as funcionalidades existentes
- Mesma estrutura YAML (role/goal/backstory para agents, description/expected_output para tasks)
- Mesmos nomes de agentes e tasks
- Mesmos placeholders de dados ({client_message}, etc.)
- Mesmos formatos de saída JSON

O que muda:
- Pseudo-código → linguagem natural
- ~15 regras → ~5-7 constraints por agente
- backstory inflado → backstory enxuto + task description instrutiva
- expected_output verboso → expected_output compacto com shape claro
