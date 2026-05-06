# Post-Failure Diagnosis Flow — DEPRECATED (renomeado conceitualmente)

> Este documento foi substituído por **`docs/repair_conversation_loop.md`** em 2026-05-04.
>
> A frente continua existindo no código como `repair_conversation` (antes `diagnose_and_propose`) e mantém as mesmas invariantes de segurança. O que mudou é o foco arquitetural: deixou de ser um formulário diagnóstico rígido (Sintoma/Hipótese/Evidência/Confiança/Limitações/Opções/Pergunta como contrato obrigatório de saída) e passou a ser um **ciclo conversacional de reparo** em que o estado conversacional (`PendingUserDecision`) substitui o roteamento por regex.
>
> **Não consultar este arquivo para decisões novas.** Toda discussão arquitetural, status real, padrões, regras, acceptance tests e implementation targets vivem agora em `docs/repair_conversation_loop.md`.

---

## Por que o documento foi renomeado

A versão original deste arquivo (criada 2026-05-01, atualizada 2026-05-04) tratava o problema como "Post-Failure Diagnosis": após uma falha, o agente devia preencher um contrato de resposta com seções obrigatórias e oferecer opções A/B/C de forma estruturada.

O comportamento observado em sessão real (`sess-20260429T143019Z-e909c754`, runs 04-mai) mostrou que essa formulação produz três efeitos indesejados:

1. **Resposta-template idêntica em toda falha**, porque o LLM falha em cumprir o contrato regex e o sistema cai num fallback genérico (`_fallback_post_failure_diagnosis`).
2. **Aprovação humana de estratégia falha por falta de regex** ("Caminho B" → `pure_inquiry` → `diagnose_only` → round_limit), porque o roteador depende de listas lexicais como `_SHORT_CONTINUE_PHRASES`.
3. **`STRATEGY_PROPOSED` é sobrescrito para `REPAIRING` no mesmo run** pela FSM de fundo, então o estado pós-falha nunca chega a ser observado pelo turno seguinte.

A invariante de segurança ("falha de execução não é permissão automática para reescrever") está correta e foi preservada. O que mudou é como ela é materializada.

## Mapeamento rápido de seções

| Seção antiga | Novo destino |
|---|---|
| 0. Implementation Status | `repair_conversation_loop.md` §8 (Status real, com reconciliação honesta) |
| 1. Problem Statement | `repair_conversation_loop.md` §0, §1 |
| 2. Original Failure Pattern | `repair_conversation_loop.md` §0 (evidência observada) |
| 3. Intent Layer Rule | `repair_conversation_loop.md` §3, §10.3 (resolvido por estado, não por regex) |
| 4. Post-Failure Goal Mode | `repair_conversation_loop.md` §3.1, §3.2 |
| 5. Draft History Requirement | `repair_conversation_loop.md` §1.3 (mantido) |
| 6. Conversation Context Requirement | `repair_conversation_loop.md` §4 (suavizado) |
| 7. Response Contract | `repair_conversation_loop.md` §4 (Resposta recomendada — não mais contrato regex obrigatório) |
| 8. Implementation Waves 1-3 | `repair_conversation_loop.md` §8 |
| 8. Wave 4 UI | `repair_conversation_loop.md` §8 (mantida pendente, depende da microfrente) |
| 9. Acceptance Tests | `repair_conversation_loop.md` §9 (state-driven, não regex-driven) |
| 10. Non-Goals | `repair_conversation_loop.md` §7 (O que não fazer) |
| 11. Files To Inspect | `repair_conversation_loop.md` §10 (Implementation Targets) |
| 12. Final Notes | `repair_conversation_loop.md` §8, §11 |

## Itens novos que NÃO estavam aqui

- `PendingUserDecision` como entidade de primeira classe da sessão (`repair_conversation_loop.md` §2).
- Microfrente arquitetural antecipada (Wave 5.C no `REFACTOR_PLAN.md`) para impedir colapso de `STRATEGY_PROPOSED` e introduzir resolução por estado em vez de regex.
- Acceptance tests state-driven, incluindo "Caminho B" deve resolver sem regex específica.
