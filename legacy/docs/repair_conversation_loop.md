# Repair Conversation Loop

> Renomeação conceitual de `docs/post_failure_diagnosis_flow.md` (2026-05-04).
> Substituiu o foco de "diagnóstico formal pós-falha" por "conversa operacional de reparo".
> Versão anterior: `post_failure_diagnosis_flow.md` está mantido como stub de redirecionamento; não consultar para decisões novas.
> **Fonte de verdade deste documento:** arquitetura do ciclo de reparo, rationale, `PendingUserDecision` e acceptance tests state-driven. Não usar como status geral do projeto.
> **Regra de atualização:** quando uma implementação muda, status operacional muda em `CLAUDE.md`; checklist por onda muda em `docs/refactor_handoff/REFACTOR_PLAN.md`; mudanças conceituais/acceptance tests mudam aqui.

---

## 0. Por que esta revisão existe

Em sessão real (`sess-20260429T143019Z-e909c754`, runs 04-mai), o fluxo pós-falha entregou ao designer **a mesma resposta-template em três falhas seguidas (v24, v25, v26)**: mesma "Hipótese: interface de sliders, sockets ou links", mesmas "Opções A/B" (conservadora/robusta), mesma "Pergunta: Qual caminho A ou B?". Verbatim. O `static_evidence` real ("draft claims no falanges changed, but touched nodes/frames include falange-related names" — exatamente o que o usuário reportou) foi gerado, gravado no journal, e nunca apareceu na resposta.

Em paralelo, **duas aprovações de estratégia falharam por falta de regex**: "Caminho B" (turno 75) e "sim segue para a estrategia B" (turno 77) caíram em `pure_inquiry` → `diagnose_only` → 4 rounds de leitura → round_limit → resposta vazia. "Segue pela A" funcionou pela única razão de "segue" estar na lista `_SHORT_CONTINUE_PHRASES`.

Diagnóstico arquitetural: a frente pós-falha foi correta em **bloquear reescrita automática**, mas o esforço de garantir segurança virou **um formulário rígido** com:

- Contrato regex que o LLM falha em cumprir → cai sempre no fallback template.
- Template idêntico em toda falha → o designer perde a confiança no agente como par de pensamento.
- Roteador que precisa de regex específica para reconhecer cada forma de aprovação humana → escala por remendo, não por estado.

A invariante de segurança ("falha não autoriza reescrita automática") está certa. **A forma como ela foi materializada está errada.**

---

## 1. Reframing arquitetural

### 1.1. O problema NÃO é "diagnosticar"

O problema é manter um ciclo conversacional de reparo entre designer e agente após uma falha de execução:

```
script falhou
   ↓
designer relata o que viu
   ↓
agente compara feedback + draft executado + evidência disponível
   ↓
agente conversa de forma operacional (sem formulário obrigatório)
   ↓
agente alinha uma direção curta com o designer
   ↓
agente escreve o próximo draft somente quando há autorização clara
```

O foco é **continuar a conversa de modo que o designer consiga decidir**, não preencher seções obrigatórias.

### 1.2. O que muda conceitualmente

| Conceito antigo | Conceito revisado |
|---|---|
| Post-Failure Diagnosis Flow | Repair Conversation Loop |
| `diagnose_and_propose` (modo de turno) | `repair_conversation` (modo de conversa, mantém o nome interno) |
| Response Contract | Resposta recomendada + fallback seguro |
| Estratégia proposta = texto solto no chat | Estratégia proposta = `PendingUserDecision` persistido |
| Aprovação reconhecida por regex | Aprovação reconhecida por estado conversacional + match contra opções emitidas |
| Sintoma/Hipótese/Evidência/... obrigatório | Estrutura usada **internamente** quando ajuda; opcional na resposta ao usuário |

### 1.3. O que NÃO muda

- **Falha de execução não autoriza reescrita automática.** Mantido.
- **Recuperação prioritária pelo `draft_history`.** Mantido.
- **Pacote de evidência estática quando disponível.** Mantido.
- **`execute_code` e `make_plan` bloqueados no fluxo automático.** Mantido.
- **Contrato regex existe como fallback debug interno**, não como formato obrigatório do que chega ao usuário.

---

## 2. Pending User Decision (entidade central)

A peça que estava faltando.

Sempre que o agente termina um turno fazendo uma pergunta de decisão ao designer (escolher entre A/B/C, confirmar reescrita, autorizar leitura ampla, etc.), o sistema **persiste** essa pergunta como uma entidade de sessão. O turno seguinte do designer é interpretado **à luz dessa decisão pendente**, não como mensagem isolada.

### 2.1. Schema conceitual

```python
@dataclass
class PendingUserDecision:
    kind: str            # "strategy_choice" | "write_confirmation" | "repair_direction"
                         # | "read_authorization" | "scope_clarification"
    options: list[str]   # rótulos curtos das opções oferecidas; pode ser ["A", "B"]
                         # ou ["conservadora", "robusta"], conforme o agente emitiu
    prompt_summary: str  # ≤140 chars: resumo da pergunta feita pelo agente
    source_revision: int # revisão do draft a que essa decisão se refere (0 se N/A)
    related_failure: str # "executed_failed" | "executed_no_effect" | "" se N/A
    proposed_at_turn: int
    proposed_at_run_id: str
    status: str          # "pending" | "answered" | "cancelled" | "expired"
    answered_with: str   # rótulo escolhido (preenchido quando status="answered")
    answered_at_turn: int
```

### 2.2. Localização

`session.execution_state.pending_user_decision: PendingUserDecision | None`

Persistido junto com o resto do `ExecutionState`. **Não** vai para `chat_history`. **Não** vai para `working_memory`. É operacional, parte do estado da sessão.

### 2.3. Quando é setado

O helper `set_pending_decision()` é a **única forma válida** de emitir uma pergunta de decisão. Handlers não devem escrever manualmente perguntas A/B no texto sem registrar a entidade operacional correspondente.

Nenhum handler deve terminar com uma pergunta de decisão ao usuário sem registrar `PendingUserDecision`. Isso inclui:

- escolher A/B/C;
- confirmar escrita;
- autorizar leitura focal;
- esclarecer escopo;
- escolher direção de reparo.

O agente seta automaticamente ao **emitir uma resposta que contém pergunta de decisão**. Exemplos:

- Resposta termina com "Qual caminho você prefere, A ou B?" → `kind=strategy_choice, options=["A","B"]`.
- Resposta diz "Antes de reescrever, posso fazer uma leitura focal do subgrafo dos metacarpos?" → `kind=read_authorization, options=["sim","não"]`.
- Resposta diz "Você quer que eu mantenha as falanges intactas, ou reescreva também elas?" → `kind=scope_clarification, options=["mantém","reescreve"]`.

A detecção pode ser do próprio handler (que já sabe se está propondo estratégias) ou de uma função leve de pós-processamento da resposta. **Não cria nova LLM call**. Não introduz regex extensa: o handler que **gera** a pergunta também **registra** a decisão pendente — porque ele sabe o que perguntou.

Regra de bug: se uma resposta contém opções A/B mas não chama `set_pending_decision()` (ou o helper equivalente `emit_decision_prompt()` se esse nome for adotado), isso é defeito arquitetural. Acceptance tests devem cobrir que toda resposta com opções A/B materializa `pending_user_decision`.

### 2.4. Quando é resolvida

No início do próximo turno, antes do roteamento normal:

```
1. Sessão tem pending_user_decision com status="pending"?
   ├── Sim → tentar resolver:
   │       ├── Mensagem do usuário menciona uma das opções? (match em options[])
   │       │       ├── Sim → status="answered", answered_with=<opção>, segue para handler
   │       │       └── Não → próxima checagem
   │       ├── Mensagem é pergunta? (termina com "?", começa com "por que/como/qual")
   │       │       ├── Sim → manter pending, roteamento normal (responder pergunta)
   │       │       └── Não → próxima checagem
   │       ├── Mensagem é negação clara? ("não", "nenhuma", "esquece", "muda")
   │       │       └── Sim → status="cancelled", roteamento normal
   │       └── Mensagem é afirmativa curta sem opção? ("sim", "pode", "ok")
   │               └── Sim:
   │                     ├── Se options tem default → resolver com default
   │                     └── Caso contrário → manter pending + agente pede esclarecimento
   └── Não → roteamento normal
```

### 2.5. Escopo do match

O match contra `options[]` é **estritamente bound ao conjunto que o agente emitiu naquele turno**. Não é regex aberta sobre português. Exemplos do que deve resolver:

| Mensagem | Options registradas | Match |
|---|---|---|
| "Caminho B" | `["A","B"]` | "B" |
| "vou pela B" | `["A","B"]` | "B" |
| "sim, a segunda" | `["A","B"]` | "B" (segunda → última) |
| "fica com a A" | `["A","B"]` | "A" |
| "opção 1" | `["A","B"]` | "A" (1 → primeira) |
| "robusta" | `["conservadora","robusta"]` | "robusta" |
| "manda a B e reescreve" | `["A","B"]` | "B" (e libera escrita) |

Casos não-resolvíveis cedem ao caminho padrão (manter pending ou cancelar). Não há tentativa de "adivinhar" intenção fora do conjunto de opções.

### 2.6. O que isso elimina

- A necessidade de adicionar "Caminho B", "Opção A", "vou pela B", "primeira", "segunda" em `_SHORT_CONTINUE_PHRASES`.
- A dependência de `session_state == STRATEGY_PROPOSED` para o roteamento funcionar.
- O paradoxo atual em que "Segue pela A" funciona e "Caminho B" não, por motivos lexicais.

A regra única passa a ser: **se o agente perguntou A/B no turno anterior, o turno atual é interpretado nessa moldura**.

---

## 3. Modos de conversa de reparo

Mantemos a separação de modos por segurança (read-only vs. escrita), mas o vocabulário e o uso mudam.

### 3.1. `repair_conversation` (antes: `diagnose_and_propose`)

Ativado quando:

- Outcome de execução é falha (`executed_failed`, `executed_no_effect`, `executed_partial_failure`, `reverted_by_user`).
- Mensagem é prefixada por `[RESULTADO DE EXECUÇÃO]` com resultado FALHOU.
- Designer pergunta investigativamente sobre um draft que acabou de falhar (sem imperativo claro de escrita).
- Sessão está em `REPAIRING` e a intenção do turno **não é** aprovação/imperativo de escrita.

Ferramentas permitidas:

- Leitura: `read_script_draft`, `get_node_context`, `get_local_subgraph_context`, `find_tree_nodes`, `get_tree_parameters`, `get_changes_since_last_turn`, `analyze_gn_state`.

Ferramentas proibidas:

- `write_script_draft`, `execute_code`, `make_plan`.

O agente **conversa**: explica o que acabou de ler, o que entendeu da falha, sugere uma direção curta, faz uma pergunta de alinhamento. Não preenche formulário.

### 3.2. `focal_correction` (inalterado em essência)

Ativado quando:

- Há `PendingUserDecision` resolvido com aprovação clara de uma opção.
- Mensagem do usuário tem imperativo explícito de escrita ("reescreve", "corrige agora", "salva uma revisão com X").
- Há evidência suficiente (draft falho lido, target identificado, estratégia conhecida).

Ferramentas permitidas:

- Tudo de `repair_conversation` + `write_script_draft`.

Limite: `max_rounds=4`. Halt-after-write mantido.

### 3.3. Transição entre modos

```
falha reportada
   → repair_conversation (read-only)
   → agente responde + deve chamar set_pending_decision() se emitir pergunta de decisão

próximo turno do usuário
   → resolver PendingUserDecision
       → answered: focal_correction (escrita liberada)
       → mantido pending: repair_conversation (continua conversa)
       → cancelled: volta para CONVERSA padrão
```

Não há "diagnose_only" como destino fixo. O sistema usa `repair_conversation` enquanto faz sentido conversar; vai para `focal_correction` quando há autorização operacional.

---

## 4. Resposta recomendada (suavizada)

### 4.1. Princípio

A resposta do agente em `repair_conversation` deve ser **operacional**: dizer o que viu, dizer o que pensa, perguntar uma coisa só, terminar. Linguagem natural, não cabeçalhos obrigatórios.

### 4.2. Estrutura recomendada (não obrigatória)

Internamente o agente é orientado a cobrir, **quando aplicável**, estas dimensões:

- **O que aconteceu** — paráfrase curta do feedback do usuário, mostrando que entendeu.
- **O que vejo no draft** — referência concreta a nó/socket/link tocado, citando ao menos um item do `static_evidence` quando disponível.
- **Hipótese curta** — uma frase, baseada na evidência, não genérica.
- **Direção proposta** — uma direção operacional concreta; alternativas só quando forem naturalmente úteis, expressas em linguagem do problema (não "conservadora vs robusta" abstratos), com nomes dos nós/regiões reais.
- **Pergunta única de alinhamento** — para o designer responder.

Quando uma dimensão não tem informação útil (ex: não há `static_evidence`), o agente **omite** em vez de preencher com "Evidência: ainda parcial".

### 4.3. Exemplo concreto (bom)

> Você executou v26 e nada mudou na cena. Olhei o draft: ele escreve em `TF_Metacarpo1.001.Translation` e em `TF_Falange21.001.Translation`, e o segundo nó tem o nome de "Falange21" mas está no frame "Metacarpos" — ou seja, você renomeou esse nó como metacarpo, mas o draft está tratando os dois com a mesma fórmula simétrica e isso pode ser exatamente o que está empurrando uma das pontas para fora.
>
> Minha direção seria primeiro isolar esses dois TF e confirmar se algum link sobrescreve `Translation` depois do draft. Se esse conflito se confirmar, a próxima revisão ajusta só essa região, preservando as falanges fora do escopo.
>
> Quer que eu siga por essa direção na próxima revisão?

### 4.4. Exemplo concreto (ruim — atual)

> Sintoma:
> O usuario relatou: [RESULTADO DE EXECUÇÃO — Revisão v26] Resultado: FALHOU Descrição: Nao aconteceu nada...
>
> Hipotese:
> A causa mais provavel esta em interface de sliders, sockets ou links, com o draft alterando um alvo diferente do pretendido ou desconectando parte da cadeia existente.
>
> Evidencia:
> revisei a revisao 26 de GN_Agent_Draft a partir de draft_history; operation_counts: default_value_writes=2, links_removed=1...
>
> [+ 4 seções obrigatórias]
>
> Opcoes:
> A. Correcao conservadora: preservar a estrutura atual e ajustar apenas nomes, sockets e links suspeitos.
> B. Correcao robusta: reconstruir somente a regiao afetada do draft com validacoes antes de relinkar geometria ou controles.
>
> Pergunta:
> Qual caminho voce aprova para a proxima revisao, A ou B?

A diferença não é de comprimento nem de quantidade de opções. É de **especificidade**: a resposta boa nomeia nós reais, hipótese real, direção real; a resposta ruim usa rótulos abstratos que não significam nada para o designer.

### 4.5. Contrato como fallback interno

O contrato `Sintoma:/Hipotese:/Evidencia:/Confianca:/Limitacoes:/Opcoes:/Pergunta:` deixa de ser **formato obrigatório de toda resposta** e passa a ser:

- **Modo debug**: invocável quando `agent_runtime.debug.force_diagnostic_format=true`.
- **Fallback interno seguro**: quando o LLM produz resposta vazia, com erro, ou abaixo de um limiar de qualidade (definido adiante), o sistema cai num template padrão. **Esse fallback não substitui a tentativa principal — só preenche quando ela falha de fato.**
- **Não roda como contrato regex sobre a resposta principal.** Resposta livre é aceita.

O limiar de qualidade não é "texto longo". Uma resposta longa, fluente e genérica ainda falha se ignorar a evidência real. Em particular:

- Se `static_evidence_mismatches` estiver vazio e houver `static_evidence` disponível, a resposta precisa citar ao menos uma referência concreta a nó/socket/link/frame/label.
- Se `static_evidence_mismatches` NÃO estiver vazio, a resposta principal precisa incorporar pelo menos um mismatch na hipótese ou direção proposta.
- Não basta citar `operation_counts`.
- Não basta dizer "pode ser problema de sockets ou links".
- Se o LLM não usa o mismatch real, o fallback roda.
- O fallback também usa o mismatch real; não gera template genérico.

---

## 5. Evidência: como usar

Quando o `static_evidence` estiver disponível (`failed_draft_evidence_pack` no prompt), a resposta principal **deve citar pelo menos um item concreto**: um nó tocado, um socket, um link removido, uma referência ausente, um conflito semântico (ex: "draft claims no falanges changed, but touched nodes/frames include falange-related names").

Quando o pacote indica um conflito semântico forte (`static_evidence_mismatches`/`semantic_mismatches` não-vazio), a hipótese da resposta **deve incorporar o conflito**, não tratar como nota lateral. Foi exatamente esse o caso de v26: o conflito detectado era "draft claims no falanges changed, but touched nodes/frames include falange-related names"; a resposta precisa nomear esse conflito como hipótese central ou direção de reparo. Enterrar o dado em `operation_counts` ou responder genericamente sobre sockets/links é regressão.

Três falhas com evidências diferentes não podem produzir o mesmo fallback verbatim. A variação não é estética: o fallback deve ser derivado do nó/socket/link/frame/label ou mismatch real disponível em cada falha.

Quando o pacote está vazio ou inconclusivo, o agente declara isso em uma frase curta ("não tenho como dizer com certeza qual nó causou — quer que eu leia o subgrafo de X antes de propor algo?") e **pede autorização** para uma leitura focal extra. Não tenta fingir certeza.

---

## 6. State persistence rules

### 6.1. STRATEGY_PROPOSED não pode colapsar no mesmo run

Bug observado em `run-20260504T145800Z-87e94235.jsonl:9-12`, `run-20260504T151831Z-807f9a9c.jsonl:9-12` (idem para v25): o handler grava `post_failure_state=STRATEGY_PROPOSED` e a FSM emite `state_transition: STRATEGY_PROPOSED → REPAIRING` no mesmo run, segundos depois. Resultado: quando o próximo turno do usuário chega, `session_state == REPAIRING` e qualquer caminho que dependesse de `STRATEGY_PROPOSED` está morto.

Regra arquitetural revisada:

> **`STRATEGY_PROPOSED` (e qualquer estado que represente decisão pendente) só pode ser alterado por (a) ação do próximo turno do usuário ou (b) `clear()` explícito pelo handler. A FSM de fundo não pode rebatê-lo automaticamente para `REPAIRING` antes do próximo turno.**

Equivalente operacional: enquanto `pending_user_decision.status == "pending"`, o `session_state` permanece em `STRATEGY_PROPOSED` (ou no estado correspondente à `kind`). Não há "limpeza ao final do run" automática.

### 6.2. PendingUserDecision sobrevive a reload

Como o restante do `ExecutionState`, persiste no Session V1 JSON. Sobrevive a "Enviar e Reverter" + reabertura do `.blend`. O fluxo de revert + reopen + reabrir painel deve **encontrar a decisão pendente intacta** e o painel deve refletir isso.

### 6.3. Expiração

`PendingUserDecision` que não foi respondida em N turnos (sugestão: 5) recebe `status="expired"` para evitar que o estado fique pendurado indefinidamente. Isso é uma defesa, não fluxo principal.

---

## 7. O que não fazer

Repetir aqui para registro arquitetural permanente:

1. **Não adicionar mais regex no router** para reconhecer aprovação humana. Cada nova regex é evidência de que falta estado, não de que falta padrão. A microfrente em §10 substitui isso por estado.
2. **Não criar IntentResolver com LLM por turno.** Custo permanente, fragilidade nova. Quando o match contra `options[]` falhar, o agente pede esclarecimento no chat — custa um turno, não um modelo.
3. **Não transformar toda falha em formulário diagnóstico obrigatório.** O contrato Sintoma/Hipótese/... vira fallback interno, não formato canônico de saída.
4. **Não duplicar state machines.** A `pending_user_decision` é parte do `ExecutionState`. Não criar uma máquina paralela. Quando a Onda 7 introduzir a state machine formal, `pending_user_decision` deve ser absorvida como input/condição, não substituída por outro mecanismo paralelo.
5. **Não sobrescrever `STRATEGY_PROPOSED` para `REPAIRING` automaticamente** dentro do mesmo run. Bug atual que precisa ser explicitamente impedido.
6. **Não esconder `static_evidence_mismatches` em campo de log.** Se foi detectado, vai para a hipótese principal da resposta ou para uma pergunta operacional ao usuário.
7. **Não responder com mensagens-bumper** ("Nao salvei o draft porque este turno estava em modo de diagnostico"). Resposta sempre tem conteúdo: o que leu, o que pensa, o que pergunta.
8. **Não tornar a resposta principal dependente de regex de cabeçalho** ("^Sintoma:"). O LLM produz Markdown, headings, bullets, prosa — tudo aceitável.
9. **Não emitir pergunta de decisão fora do helper.** `set_pending_decision()`/`emit_decision_prompt()` é o caminho arquitetural obrigatório; pergunta A/B sem entidade operacional é bug.

---

## 8. Status real (validação no código vs. journal)

Reconciliação honesta entre o que `post_failure_diagnosis_flow.md` (versão antiga) afirmava e o que o código + journal mostram em 2026-05-04.

| Item | Antes afirmado | Status real | Fonte |
|---|---|---|---|
| Wave 1 — feedback de falha não dispara reescrita automática | concluída | **implementado em código; observado funcionando** | `drafting.py:2003+` `handle_execution_feedback`; chat history confirma ausência de write em turnos de feedback |
| Wave 1 — recuperação prioritária pelo `draft_history` | concluída | **implementado e validado** | journal `failed_draft_source: "draft_history"` em runs `145800Z`, `151831Z` |
| Wave 2 — contrato regex + fallback | concluída | **implementado, mas o contrato regex falha sistematicamente** | runs 04-mai: 3 falhas seguidas resultam em fallback verbatim. `diagnosis_contract_satisfied=true` é registrado **após** o fallback ter rodado, mascarando a falha do LLM |
| Wave 3 — STRATEGY_PROPOSED / STRATEGY_APPROVED na sessão | concluída | **schema criado, comportamento quebrado**: STRATEGY_PROPOSED é sobrescrito para REPAIRING no mesmo run | journal: `state_transition: STRATEGY_PROPOSED → REPAIRING` imediatamente após `script_draft_execution_diagnosis` em runs `145800Z`, `151831Z` |
| Wave 3 — aprovação explícita de estratégia libera o próximo draft | concluída | **funciona somente quando a mensagem do usuário tem token reconhecido (`segue`); falha em "Caminho B", "sim segue para a estrategia B"** | runs `151938Z` e `152101Z`: `turn_intent=pure_inquiry → diagnose_only → round_limit, write_allowed=false` |
| Pacote de evidência estática | concluído | **detector funciona; surfacing está enterrado** | journal `static_evidence_mismatches` correto para v26; fallback embute como string achatada em "Evidencia"; nunca aparece como hipótese |
| Wave 4 — UI de estratégia | pendente | **pendente** | sem UI |

**Conclusão:** Waves 1, 2 e 3 estão **documentadas como implementadas, comportamento parcialmente quebrado em produção**. A frente exige a microfrente da §10 antes de seguir para Wave 4 ou para a Onda 6.

---

## 9. Acceptance tests (state-driven)

Substituem os testes regex-based do documento anterior. Todos têm critério de saída observável no journal e/ou no chat.

### Teste 1 — Aprovação A/B sem regex

```
Pré-condição:
  Turno N: agente respondeu propondo opções A e B; setou
  pending_user_decision={kind:"strategy_choice", options:["A","B"], status:"pending"}.
  session_state = STRATEGY_PROPOSED.

Turno N+1, mensagem do usuário: "Caminho B"

Esperado:
  - pending_user_decision.status="answered", answered_with="B"
  - session_state transita para STRATEGY_APPROVED
  - handler entra em focal_correction (write_allowed=true)
  - write_script_draft é chamado
  - journal mostra pending_decision_resolved com label="B"
  - turno NÃO termina em round_limit

Anti-regressão:
  - "Caminho B", "vou pela B", "sim, a segunda", "manda a B" devem todos resolver para "B"
  - SEM adicionar regex para cada variação
```

### Teste 2 — Pergunta sem aprovação mantém pending

```
Pré-condição:
  pending_user_decision com options ["A","B"] e status pending.

Turno N+1, mensagem: "mas por que a B?"

Esperado:
  - pending_user_decision.status permanece "pending"
  - agente responde a pergunta operacionalmente
  - NÃO chama write_script_draft
  - turno seguinte ainda enxerga a decisão pendente
```

### Teste 3 — Negação clara cancela pending

```
Pré-condição:
  pending_user_decision pendente.

Turno N+1, mensagem: "esquece, muda a abordagem"

Esperado:
  - pending_user_decision.status="cancelled"
  - session_state volta para REPAIRING ou IDLE conforme contexto
  - agente responde reabrindo conversa, sem escrever
```

### Teste 4 — STRATEGY_PROPOSED não colapsa no mesmo run

```
Pré-condição:
  Turno de execution_feedback emite diagnose com strategies. Handler seta
  post_failure_state=STRATEGY_PROPOSED, session_state=STRATEGY_PROPOSED.

Esperado dentro do MESMO run:
  - NÃO há state_transition: STRATEGY_PROPOSED → REPAIRING
  - Ao final do run, session_state ainda é STRATEGY_PROPOSED
  - pending_user_decision persistido com status="pending"

Esperado no run seguinte (próximo turno do usuário):
  - Roteamento consulta pending_user_decision ANTES das regras lexicais
  - Mensagem do usuário é interpretada à luz da decisão pendente
```

### Teste 5 — Conversa de reparo, não formulário

```
Cenário:
  Falha reportada via [RESULTADO DE EXECUÇÃO], static_evidence_mismatches
  contém ["draft claims no falanges changed, but touched nodes/frames
  include falange-related names"].

Esperado na resposta do agente:
  - Cita ao menos um nó/socket/link concreto (não rótulo abstrato).
  - A hipótese principal incorpora o mismatch detectado, não trata como nota lateral.
  - Não basta citar operation_counts.
  - Não basta dizer "pode ser problema de sockets ou links".
  - NÃO é obrigado a usar cabeçalhos "Sintoma:/Hipotese:/...".
  - Termina com no máximo UMA pergunta de alinhamento ou propõe um próximo passo concreto.
  - PendingUserDecision é setada se houver opções A/B/etc.
```

### Teste 5b — Fallback usa mismatch real

```
Cenário:
  static_evidence_mismatches contém
  "draft claims no falanges changed, but touched nodes/frames include
  falange-related names".

Esperado:
  - Se a resposta principal não incorpora esse conflito na hipótese ou direção,
    o fallback roda.
  - O fallback menciona esse conflito como hipótese central ou direção de reparo.
  - Três falhas com evidências diferentes não produzem o mesmo fallback verbatim.
```

### Teste 6 — Read-only continua read-only

```
Mensagem: "pode ler o draft?"

Esperado:
  - NÃO chama write_script_draft
  - read_script_draft permitido
  - resposta explica o que viu, sem propor estratégia obrigatória
  - PendingUserDecision NÃO é setada (não há decisão a tomar)
```

### Teste 7 — Imperativo sem decisão pendente exige evidência

```
Pré-condição:
  pending_user_decision = None.
  session_state = REPAIRING (turno anterior foi diagnose).
  Mensagem: "corrige o draft agora"

Esperado:
  - Se há evidência suficiente (draft falho lido, target identificado),
    handler entra em focal_correction.
  - Se NÃO há evidência suficiente, agente responde pedindo confirmação:
    "antes de reescrever, preciso confirmar X" — write NÃO acontece neste turno.
  - Decisão é registrada como PendingUserDecision(kind="write_confirmation").
```

### Teste 8 — Rollback não destrói pending_user_decision

```
Cenário:
  Turno N: agente propõe A/B, seta pending_user_decision.
  Designer clica "Enviar e Reverter": .blend é restaurado para snapshot pré-script,
  Blender reabre, painel rehidrata.

Esperado após reabertura:
  - pending_user_decision intacto no JSON da sessão.
  - Painel exibe estado consistente (revisão, fase, decisão pendente).
  - Próximo turno do usuário continua de onde parou.
```

### Teste 9 — Default seguro quando match é ambíguo

```
Pré-condição:
  pending_user_decision com options ["A","B"].

Turno N+1, mensagem: "vamos lá"

Esperado:
  - Match contra options[] falha (não menciona A nem B nem 1ª/2ª).
  - É afirmativa curta, mas SEM opção identificada.
  - Agente NÃO escolhe um lado por conta própria.
  - Agente pede esclarecimento: "você quer dizer A ou B?".
  - pending_user_decision permanece "pending".
```

---

## 10. Implementation Targets

**Esta seção lista pontos de código que provavelmente precisam mudar para implementar a microfrente. Não inclui patches.**

### 10.1. Schema

| Arquivo | Mudança esperada |
|---|---|
| `blender_addon/session/schema.py` | Adicionar `@dataclass PendingUserDecision`. Adicionar campo `pending_user_decision: PendingUserDecision \| None = None` em `ExecutionState`. |
| `blender_addon/session/store.py` | Garantir serialização/desserialização de `PendingUserDecision`. Migração lazy: sessões antigas carregam com `None`. |

### 10.2. Handler de feedback de execução

| Arquivo | Mudança esperada |
|---|---|
| `blender_addon/runtime/handlers/drafting.py` (`handle_execution_feedback` ~linha 2003) | Quando o handler emite resposta com opções A/B (ou via fallback ou via LLM com opções identificáveis), chamar `set_pending_decision()` antes de retornar. Pergunta A/B sem `pending_user_decision` é bug. |
| Helper conceitual `set_pending_decision()` / `emit_decision_prompt()` | Caminho único para materializar perguntas de decisão: escolher A/B, confirmar escrita, autorizar leitura focal, esclarecer escopo, escolher direção de reparo. |
| `blender_addon/runtime/handlers/drafting.py` (`_fallback_post_failure_diagnosis` ~linha 1626) | Reduzir uso. Manter como fallback interno apenas; deixar de ser obrigatório. Quando `static_evidence_mismatches` não-vazio, hipótese gerada deve referenciar o mismatch real, não ignorá-lo. Fallback não pode ser template genérico idêntico para evidências diferentes. |
| `blender_addon/runtime/handlers/drafting.py` (`_post_failure_contract_status` ~linha 1370) | Deixar de ser gate principal. Resposta livre do LLM é aceita; fallback só roda se LLM retorna vazio/erro/abaixo de limiar de qualidade. Se não há mismatches, exigir referência concreta a nó/socket/link/frame/label quando houver `static_evidence`; se há mismatches, exigir que hipótese/direção use ao menos um mismatch real. |
| `blender_addon/runtime/prompt_builder.py` (`POST_FAILURE_DIAGNOSIS_CONTRACT` ~linha 69) | Suavizar. Trocar "Use this exact Portuguese structure with short sections: Sintoma:/Hipotese:/..." por instrução operacional: "Conversa de reparo. Cite pelo menos um nó/socket/link concreto da `Failed draft static evidence` quando disponível. Termine com no máximo uma pergunta de alinhamento. Se houver opções, rotule-as A, B (sem prefixos longos)." |

### 10.3. Resolução de PendingUserDecision

| Arquivo | Mudança esperada |
|---|---|
| `blender_addon/runtime/router.py` ou `blender_addon/agent_runtime.py` (início de `run_turn`) | **Antes** do roteamento normal, checar `session.execution_state.pending_user_decision`. Se `status=="pending"`, tentar resolver via match contra `options[]` + heurísticas curtas (afirmativa, negação, pergunta). Atualizar `pending_user_decision.status` conforme. |
| `blender_addon/runtime/routing_obs.py` (~linha 280-381) | A função `infer_turn_intent()` passa a consultar `pending_user_decision` como primeira regra. Se decisão foi resolvida com aprovação, intent vira `strategy_approval`. Se mantida pendente por pergunta, intent é `pure_inquiry`. **Não adicionar listas regex novas.** |
| Match contra `options[]` | Match curto, case-insensitive, sobre o conjunto fechado das opções emitidas no turno anterior. Suporte mínimo a sinônimos numéricos ("primeira", "segunda", "1", "2") e a frases-padrão ("vou pela X", "fica com a X", "manda a X"). Sem regex extensa. |

### 10.4. State machine guard

| Arquivo | Mudança esperada |
|---|---|
| `blender_addon/runtime/state_machine.py` | Impedir transição automática de `STRATEGY_PROPOSED` → `REPAIRING` no mesmo run. Transição de `STRATEGY_PROPOSED` só ocorre por evento de turno do usuário (resolução de pending_user_decision) ou por clear explícito do handler. |
| `blender_addon/agent_runtime.py` (final de `run_turn`) | Não rodar "limpeza de fim de run" que descarte `pending_user_decision` ou regrida `session_state` para REPAIRING. |

### 10.5. UI

| Arquivo | Mudança esperada (não-bloqueante para a microfrente) |
|---|---|
| `blender_addon/ui/panel.py` | Indicador visual de "decisão pendente: A/B" quando `pending_user_decision.status=="pending"`. Não obrigatório para funcionalidade — útil para o designer. |

### 10.6. Testes

| Arquivo | Mudança esperada |
|---|---|
| `tests/test_pending_user_decision.py` (novo) | Cobrir Tests 1-9 da seção 9, incluindo o Teste 5b. Sem dependência de Blender; usar mock de Session/ExecutionState. |
| `tests/test_repair_conversation_loop.py` (novo) | Cobrir interação handler → setar pending → próximo turno → resolver. |

---

## 11. Migration from Post-Failure Diagnosis Flow

O documento `docs/post_failure_diagnosis_flow.md` foi reduzido a um stub de redirecionamento. Conteúdo arquitetural, status, padrões, contratos e acceptance tests vivem aqui. Referências antigas a "Wave 1/2/3 do Post-Failure Diagnosis Flow" continuam válidas e mapeiam para o que está em §8 desta documentação. A microfrente da §10 é uma adição, **não** uma substituição das Waves 1-3 — endereça as quebras observadas no comportamento delas.
