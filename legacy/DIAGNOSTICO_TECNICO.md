# Diagnóstico Técnico — blend_IA_ort

> Gerado em 2026-04-10. Baseado nos arquivos do projeto, journals e sessões reais.

---

## 1. Visão geral do diagnóstico

**O agente funciona — mas quase sempre no handler errado.** A causa raiz do "travamento" não é um bug de runtime, timeout ou estado corrompido. É um problema de classificação: o `TurnRouter` classifica quase todas as mensagens em português como `clarification`, impedindo que o fluxo de mutação (`mutation_request` → `awaiting_confirmation` → `mutation_confirmation`) seja ativado.

Evidência direta: **100% dos `handler_completed` nos dois últimos journals** (`sess-20260410T002302Z` e `sess-20260409T215818Z`) mostram `turn_class: "clarification"`, incluindo quando o usuário está explicitamente pedindo mutações ou confirmando com "sim".

O resultado é um ciclo frustrante: o agente lê a cena, formula um plano, pede confirmação... mas na hora de executar, o sistema não reconhece a confirmação nem o pedido original como mutação. O agente então entrega o código como texto para o usuário copiar-colar.

---

## 2. Como o fluxo real do agente está se comportando

### Fluxo planejado pela arquitetura

```
User message → TurnRouter.classify()
  → mutation_request → capture_mode=True → agent gera código (staged)
    → phase: idle → awaiting_confirmation
      → User: "sim"
        → TurnRouter detecta confirmation_pattern + phase=awaiting_confirmation
          → mutation_confirmation → phase=executing → execute_code → Blender
```

### Fluxo que realmente está acontecendo (baseado nos journals)

```
User: "Me ajuda a parametrizar a extensão e flexão do punho"
  → TurnRouter: nenhum _MUTATION_PATTERN casa → default → "clarification"
    → clarification handler → agent_loop com todas as tools
      → agent chama get_tree_structure, get_node_context (múltiplos reads)
      → agent chama make_plan (step 6)
      → agent chama execute_code (step 8)...
         Abril 9: BLOCKED — "execution_gate_blocked_phase: idle"
         Abril 10: executa (gate removido no código), mas...
      → agent formula resposta como texto com plano bonito
      → handler_completed: "clarification", tool_calls: 0

User: "sim. Mantenha a entrada do desvio ulnar e crie essa nova entrada"
  → TurnRouter: phase="idle" (nunca foi para awaiting_confirmation)
    → _CONFIRMATION_PATTERNS exigem ^sim$ (string inteira) → não casa
    → nenhum _MUTATION_PATTERN casa ("crie" ≠ "cria?") → default → "clarification"
      → agent reconhece que deveria executar, mas prompt diz "never mutate without approval"
      → agent diz "Estou tendo um problema técnico com as ferramentas" e dá o script para copiar
```

### Evidências específicas dos journals

**`sess-20260409T215818Z-20e0f110.jsonl`:**
- Linha 11: `execution_gate_blocked_phase` — `execute_code`, `phase: "idle"`
- Linha 53: mesmo bloqueio, segunda tentativa
- Todos os `handler_completed`: `turn_class: "clarification"`

**`sess-20260410T002302Z-41407282.jsonl`:**
- Linha 8: `make_plan` (step 6)
- Linha 11: `execute_code` (step 8, elapsed_ms: 25)
- Linha 44: `execute_code` (step 14, elapsed_ms: 9)
- Todos os `handler_completed`: `turn_class: "clarification"`
- Linha 33 (sessão anterior): rate_limit_error 429 — 30,000 tokens/min excedido

**Sessão v1** (`sessions_v1/...session.json`):
- Assistente pede confirmação: "Posso aplicar?"
- Usuário confirma: "sim. Mantenha a entrada..."
- Assistente responde: "Estou tendo um problema técnico com as ferramentas de modificação"

---

## 3. Principais problemas encontrados

### Problemas mais fáceis (correção pontual)

#### P1. Regexes do router não cobrem conjugações portuguesas

- `cria?` casa "cri" e "cria", mas não "crie" (subjuntivo), "criei", "criando", "criar"
- "parametrizar", "mantenha", "ajuda a" não estão em nenhum pattern
- **Impacto**: a maioria das mensagens em português que pedem mudanças são classificadas como "clarification"
- **Arquivo**: `runtime/router.py:90-109` (`_MUTATION_PATTERNS`)

#### P2. Confirmation patterns exigem mensagem inteira

- `^\s*(sim|pode|...)\s*[!.]?\s*$` — ancoragem `^...$` rejeita "sim, mas mantenha X"
- **Impacto**: confirmações reais do usuário (que incluem contexto) nunca são reconhecidas
- **Arquivo**: `runtime/router.py:111-114` (`_CONFIRMATION_PATTERNS`)

#### P3. `_looks_like_failure` é excessivamente sensível

- `mutation_confirmation.py:210-213`: palavras como "error", "failed", "could not" no texto do assistente fazem o handler declarar falha
- Se o agente mencionar erros passados na resposta, o turn é marcado como falho
- **Impacto**: falsos positivos de falha

### Problemas intermediários (refatoração média)

#### P4. Goal lifecycle nunca é ativado

- Todo journal entry tem `goal_id: "untracked"`
- Nenhum handler chama `journal.start_goal()` ou `journal.end_goal()`
- `knowledge_updater.maybe_extract_knowledge()` é chamado em `agent_runtime.py:286` mas com assinatura incompatível — recebe `(self, user_message, result)` enquanto a função espera `(*, journal_session_file, goal_id, had_errors, api_key, knowledge_dir)`
- **Impacto**: aprendizado automático nunca funciona

#### P5. System prompt contradiz a autorização code-level

- O código REMOVEU o phase gate de `execute_code` (comentário em `_execute_tool:398-410`)
- Mas `BASE_SYSTEM_PROMPT` ainda diz: "Never run mutation tools without explicit user approval"
- Resultado: o código permite execução, mas as instruções do modelo impedem
- O agente fica preso entre poder e não dever

#### P6. Acúmulo de contexto sem controle

- Um único turn gera 6-10 tool calls de leitura (get_tree_structure, get_local_subgraph_context, etc.)
- Input tokens sobem de 8K para 38K em um único turn
- Taxa 429 (rate limit) observada no journal: 30,000 tokens/min excedido
- **Arquivo**: `runtime_agent_loop.py` — o loop não tem budget de tokens

### Problemas estruturais (complexos)

#### P7. Classificação regex-only é fundamentalmente frágil para português

- Português tem conjugações ricas (presente, subjuntivo, gerúndio, infinitivo, imperativo afirmativo e negativo)
- Cada verbo pode ter 6+ formas relevantes
- Patterns atuais cobrem ~2 formas por verbo
- Padrões de fala natural ("me ajuda a...", "quero que você...", "preciso de...") não são imperativos mas pedem mutação

#### P8. Dual persistence (legacy + v1) sem garantia de consistência

- `session_store.py` (legacy flat dict) e `session/` (v1 structured) coexistem
- `_sync_v1_to_legacy` em `agent_runtime.py:293-337` tem broad `except Exception: pass`
- `USE_STRUCTURED_SESSION_V1` flag em `agent_runtime.py:70` está desligada por padrão (`"0"`)
- **Impacto**: phase transitions podem se perder, pending mutations podem desaparecer entre saves

#### P9. Estado massivo no session_store

- `_default_state()` em `session_store.py:76-150` tem ~60 campos
- Muitos são vestigiais de phases anteriores (approval_token, presented_plan_stages, etc.)
- O estado é salvo/carregado inteiro em cada tool dispatch (`_postprocess_tool` → `save`)
- Overhead de I/O e complexidade mental

---

## 4. O que parece bom e vale preservar

### A. Arquitetura handler/router/state-machine é sólida em conceito

- A separação de turn classes em handlers independentes é boa
- O state machine (`state_machine.py`) é limpo, testável, tem transições explícitas
- O contrato TurnContext → HandlerResult é claro

### B. O sistema de captura (capture_mode) é bem pensado

- `mutation_request` ativa `capture_mode` → execute_code é staged, não executado
- `mutation_confirmation` faz replay das tool calls staged
- Quando funciona (se o router classificar corretamente), é um fluxo seguro e elegante

### C. Ferramentas de leitura são ricas e funcionais

- `get_tree_structure`, `get_node_context`, `get_local_subgraph_context` — todas funcionando
- `capture.py` é defensivo com Blender 3.x/4.x/5.x compatibility
- `runtime_state_sync.py` atualiza `structural_index`, `session_memory`, `local_scope` corretamente

### D. O journal é bem estruturado

- JSONL append-only com timestamps, session_ids, event_types
- Métricas úteis (input_tokens, output_tokens, elapsed_ms) em cada evento
- Quando o goal lifecycle funcionar, terá boa rastreabilidade

### E. Screenshot multimodal funciona

- `visual_evidence_processed` aparece nos journals
- O fluxo `capture_screenshot` → `send_screenshot_turn` → análise visual funciona

### F. A abordagem "code-first" (execute_code como tool principal) é a correta

- Muito mais flexível que tools atômicas (create_node, connect_nodes) para operações complexas
- O agente demonstra que SABE gerar código Python/bpy correto (evidência: os scripts que fornece em texto)

---

## 5. O que parece frágil ou mal definido

### A. O router é um ponto único de falha sem fallback

- Se o router erra, todo o turn segue pelo caminho errado
- Não há mecanismo para o handler perceber "isso deveria ter sido uma mutação" e re-rotar
- O default "clarification" é conservador demais para um copilot que precisa agir

### B. O contrato de confirmação é implícito e frágil

- O agente pede "Posso aplicar?" em texto livre (sem estrutura)
- O router espera `^sim$` na resposta inteira
- Não há nenhum mecanismo para o agente sinalizar "estou pedindo confirmação" ao sistema
- O pipeline de confirmação depende de perfeita sincronia entre agente (texto) e router (regex)

### C. Exception suppression generalizada

- `except Exception: pass` em mais de 15 locais no `agent_runtime.py`
- Bugs silenciosos: se o v1 session save falha, se o goal lifecycle falha, se o knowledge update falha — nenhum sinal
- O sistema parece funcionar mas pode estar falhando em múltiplos subsistemas sem que ninguém saiba

### D. A chamada de `maybe_extract_knowledge` está broken

```python
# agent_runtime.py:286-288
from .knowledge_updater import maybe_extract_knowledge
maybe_extract_knowledge(self, user_message, result.response_text)
```

Mas a assinatura real em `knowledge_updater.py:148`:

```python
def maybe_extract_knowledge(*, journal_session_file, goal_id, had_errors, api_key, knowledge_dir):
```

- Keyword-only arguments, completamente diferentes do call site
- Sempre lança TypeError, engolido pelo `except Exception: pass`

### E. Tokens crescem sem controle durante o agent loop

- O `runtime_agent_loop.py` é um while True sem orçamento
- Cada round acumula o resultado das tools anteriores no messages
- Em 4-5 rounds: 8K → 20K → 38K tokens
- Sem poda, sem resumo, sem limite de rounds

---

## 6. Hipóteses para o travamento da execução do agente

Ordenadas por probabilidade (maior primeiro):

### H1. O router classifica quase tudo como "clarification" (CONFIRMADO)

- **Evidência**: 100% dos handler_completed nos últimos journals
- **Mecanismo**: regexes insuficientes para português + confirmation patterns ancorados
- **Consequência**: mutation_request e mutation_confirmation nunca são invocados
- **Certeza**: Alta — dados do journal são conclusivos

### H2. O system prompt impede a execução mesmo quando o código permite (CONFIRMADO)

- **Evidência**: o agente diz "ferramentas bloqueadas" mesmo no handler clarification que tem acesso a execute_code
- **Mecanismo**: "Never run mutation tools without explicit user approval" no prompt
- **Consequência**: o agente se auto-censura e fornece código como texto
- **Certeza**: Alta — visível no histórico da sessão

### H3. O fluxo de confirmação depende de estado que nunca é setado

- **Evidência**: `session.execution_state.phase` é sempre "idle" porque mutation_request nunca roda
- **Mecanismo**: sem `pending_mutation` no session, sem `phase: awaiting_confirmation`, sem confirmation possível
- **Consequência**: mesmo que o router casasse "sim", não há nada a confirmar
- **Certeza**: Alta — consequência direta de H1

### H4. Acúmulo de contexto causa rate limits e timeouts

- **Evidência**: 429 no journal, 80 segundos em rounds únicos, tokens subindo para 38K
- **Mecanismo**: agent_loop sem budget, reads amplos, sem poda
- **Consequência**: degradação de performance e experiência
- **Certeza**: Média — agrava o problema mas não é causa raiz

### H5. goal_id "untracked" impede o ciclo de aprendizado

- **Evidência**: todos os journal entries com `goal_id: "untracked"`, chamada de maybe_extract_knowledge com assinatura errada
- **Mecanismo**: nenhum handler inicia/finaliza goals no journal
- **Consequência**: learned_patterns.md nunca é atualizado
- **Certeza**: Alta — código confirmado

---

## 7. Caminhos recomendados

### 7.1. Correção imediata: expandir os patterns do router (baixo risco)

No `router.py`, os `_MUTATION_PATTERNS` e `_CONFIRMATION_PATTERNS` precisam de cobertura muito maior para português:

```python
# Confirmação: não exigir string inteira — buscar no início da mensagem
_CONFIRMATION_PATTERNS = [
    r"^\s*(sim|pode|ok|claro|confirma|executa|aplica|faz)\b",  # sem $ no final
    r"\b(pode\s+(ir|fazer|aplicar|executar))\b",
    r"\b(manda\s+(ver|bala))\b",
]

# Mutação: cobrir infinitivos, imperativos, subjuntivos, gerúndios
_MUTATION_PATTERNS = [
    r"\b(cri[ea]r?|crie|criando|adicionar?|adicion[eo]|inseri[ra]|gerar?)\b",
    r"\b(muda[ra]?|mude|alterar?|alter[eo]|ajustar?|ajust[eo]|configurar?)\b",
    r"\b(conectar?|conect[eo]|ligar?|ligu[eo]|desconectar?)\b",
    r"\b(remover?|remov[oa]|apagar?|apagu[eo]|deletar?|delet[eo])\b",
    r"\b(parametriz[ae]r?|implement[ae]r?|constru[ía]r?)\b",
    r"\b(me\s+ajud[ae]\s+a\s+\w+ar)\b",  # "me ajuda a criar/parametrizar/..."
    r"\b(quero\s+que\s+(você\s+)?(\w+[ae]|faça))\b",  # "quero que você crie"
    r"\b(preciso\s+(de\s+)?(\w+ar|que))\b",  # "preciso criar/que crie"
]
```

### 7.2. Correção imediata: alinhar system prompt com a realidade

O `BASE_SYSTEM_PROMPT` precisa refletir o fluxo real:

```python
# ANTES:
"Never run mutation tools without explicit user approval."

# DEPOIS:
"When the user asks for a change, first describe the plan, then generate the code.
The system handles the confirmation flow — you will see a directive when authorized to execute."
```

### 7.3. Fix do knowledge_updater (5 min)

Corrigir a chamada em `agent_runtime.py:286-288`:

```python
# ANTES (broken):
maybe_extract_knowledge(self, user_message, result.response_text)

# DEPOIS:
maybe_extract_knowledge(
    journal_session_file=self.journal.session_file,
    goal_id=self.journal._current_goal_id,
    had_errors=bool(result.phase_transition == "failed"),
    api_key=self.client.api_key,
    knowledge_dir=self.knowledge_domain_dir,
)
```

### 7.4. Refatoração média: classificação híbrida (regex + heurística semântica)

Se os patterns expandidos ainda forem insuficientes, usar uma abordagem de dois níveis:

1. Regex para casos óbvios (como hoje, mas melhor)
2. Fallback: keyword scoring simples — contar palavras-chave de cada classe no texto e escolher a classe com maior score
3. Se ambíguo entre clarification e mutation_request: escolher mutation_request (inverter o default) — é mais fácil o handler de mutation perceber que é só leitura do que o handler de clarification perceber que precisa mutar

### 7.5. Refatoração média: goal lifecycle nos handlers

Cada handler deveria:

- No início: `journal.start_goal(goal_description, user_message)`
- No final: `journal.end_goal(status="success"|"error")`

Isso ativa o knowledge_updater e dá rastreabilidade real.

### 7.6. Refatoração média: budget de tokens no agent_loop

```python
MAX_ROUNDS = 6
MAX_INPUT_TOKENS = 25000

def agent_loop(runtime, system, messages):
    for round_num in range(MAX_ROUNDS):
        estimated = sum(runtime._estimate_tokens(str(m)) for m in messages)
        if estimated > MAX_INPUT_TOKENS:
            # prune oldest tool results
            ...
```

### 7.7. Simplificação estrutural: eliminar o dual persistence

A coexistência legacy/v1 é a fonte de bugs silenciosos. Migrar completamente para v1 e remover:

- `session_store.py` (legacy)
- `_sync_v1_to_legacy` em `agent_runtime.py`
- Os ~60 campos vestigiais em `_default_state()`

### 7.8. Considerar: eliminar o ciclo de confirmação para execute_code

O fluxo mutation_request → awaiting_confirmation → mutation_confirmation é robusto em teoria, mas na prática:

- Depende do router acertar 2x consecutivas (pedido + confirmação)
- Adiciona latência (2 API rounds extras)
- O capture_mode + replay é frágil (staged tool calls podem ficar stale)

Alternativa mais simples: o agente gera código, descreve o que fará, e executa no mesmo turn se a instrução do usuário for clara. Pedir confirmação apenas quando houver ambiguidade real. Isso é o que o CLAUDE.md original previa: "Sem confirmações para operações GN — só para quando precisar do usuário."

---

## 8. Prioridade sugerida

### Onda 1 — Destravar (pode fazer agora, impacto imediato)

| # | O que | Onde | Risco |
|---|-------|------|-------|
| 1 | Expandir _MUTATION_PATTERNS para português | `router.py:90-109` | Baixo |
| 2 | Relaxar _CONFIRMATION_PATTERNS (remover $) | `router.py:111-114` | Baixo |
| 3 | Alinhar BASE_SYSTEM_PROMPT com fluxo real | `agent_runtime.py:34-53` | Baixo |
| 4 | Corrigir chamada de maybe_extract_knowledge | `agent_runtime.py:286` | Nenhum |

**Depois desses 4 fixes, testar os 4 cenários do CLAUDE.md (seção "testes obrigatórios").**

### Onda 2 — Estabilizar (próxima sessão)

| # | O que | Onde |
|---|-------|------|
| 5 | Ativar goal lifecycle nos handlers | `runtime/handlers/*.py` |
| 6 | Adicionar budget de tokens no agent_loop | `runtime_agent_loop.py` |
| 7 | Reduzir exception suppression (logar ao invés de ignorar) | Vários |

### Onda 3 — Simplificar (quando a onda 1+2 estiver estável)

| # | O que | Onde |
|---|-------|------|
| 8 | Eliminar dual persistence (migrar para v1 definitivo) | `session_store.py`, `agent_runtime.py` |
| 9 | Limpar campos vestigiais do session state | `session_store.py:76-150` |
| 10 | Reavaliar se o ciclo de confirmação é necessário | Arquitetura geral |

---

## Conclusão

O sistema está bem arquitetado mas está operando no modo errado — 100% das vezes. A correção mais impactante é simplesmente fazer o router reconhecer português corretamente. Sem isso, o agente nunca entra no fluxo de mutação para o qual toda a máquina de estados foi construída.
