"""Turn classifier and router for the draft-first product runtime.

``TurnRouter.classify`` maps every incoming user message to exactly one live
product intent:
``trivial_chat``, ``context_inquiry``, ``draft_workspace``,
``execution_feedback``, or ``state_control``.

The classifier is cheap: it looks at draft/execution state first, then applies
lightweight signal checks. No LLM call is made. Imperative change requests now
enter the unified draft workspace only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..runtime_planning import (
    is_natural_continuation_request,
    is_scene_wide_gn_inspection_request,
    is_structured_operational_followup,
)


# ---------------------------------------------------------------------------
# Turn classes
# ---------------------------------------------------------------------------

class TurnClass(str, Enum):
    TRIVIAL_CHAT = "trivial_chat"
    CONTEXT_INQUIRY = "context_inquiry"
    DRAFT_WORKSPACE = "draft_workspace"
    EXECUTION_FEEDBACK = "execution_feedback"
    STATE_CONTROL = "state_control"


@dataclass
class ClassifierMeta:
    """Metadata produced alongside the TurnClass for handler use."""

    turn_class: TurnClass
    confidence: str = "high"          # "high" | "medium" | "low"
    signals: list[str] = field(default_factory=list)
    # True when the handler should run a baseline refresh before its own work.
    needs_baseline_refresh: bool = False
    # Raw message that led to this classification.
    raw_message: str = ""
    # --- Observability fields (read-only, no effect on dispatch) ---
    # Inferred work intent of the message.  See routing_obs.TURN_INTENTS.
    turn_intent: str = ""
    # Inferred session work state.  See routing_obs.SESSION_STATES.
    session_state: str = ""
    # Explicit workspace goal mode for the unified workspace handler.
    goal_mode: str = ""


# ---------------------------------------------------------------------------
# Signal patterns
# ---------------------------------------------------------------------------

_GREETING_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    r"^\s*(ol[aÃ¡]|hi|hey|hello|oi|bom dia|boa tarde|boa noite)\s*[!.]?\s*$",
    r"^\s*(obrigad[oa]|thanks?|thank you|valeu|vlw)\s*[!.]?\s*$",
    r"^\s*(tudo bem|tudo bom|how are you|como vai)\s*[?!.]?\s*$",
]]

# W2-T1 â€" PadrÃµes de continuaÃ§Ã£o: identificam intenÃ§Ã£o de retomar resposta truncada.
# Verificados ANTES do fallback clarification para evitar roteamento errado.
_CONTINUATION_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    # PortuguÃªs
    r"^segue\b",
    r"^continua\b",
    r"^continue\b",
    r"prosseguir\b",
    r"pode\s+seguir\b",
    r"pode\s+esguir\b",
    r"pode\s+prosseguir\b",
    r"tente\s+continuar\b",
    r"a resposta cortou",
    r"foi cortad[ao]",
    r"continue de onde",
    r"^pode continuar",
    r"^termina\b",
    r"^terminar\b",
    r"^pr[oÃ³]xima\s+parte\b",
    r"^pr[oÃ³]ximo\s+passo\b",
    # InglÃªs
    r"^finish\b",
    r"^keep going\b",
    r"response was cut",
    r"finish the answer",
    r"continue from where",
    r"^go on\b",
]]

_BASELINE_REFRESH_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    r"\b(rebuild|refresh|reload|resync|re-read)\s+(the\s+)?(baseline|tree|state)\b",
    r"\b(atualiz[ae]|recarreg[ae]|reconstru[iu])\s+(o\s+)?(baseline|[aÃ¡]rvore|estado)\b",
    r"\bbaseline\s+(is\s+)?(stale|desatualizado|antigo)\b",
]]

_DIAGNOSIS_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    # English
    r"\b(show|list|what|display|describe|explain|summarize|summary|dump)\b.*\b(node|tree|modifier|scene|parameter|socket|link|group|input|output)\b",
    r"\b(what('?s|\s+is)\s+(in|the|this)|show\s+me|tell\s+me\s+about)\b",
    r"\b(which\s+nodes?|how\s+many|what\s+does\s+this|what\s+changed|changes?\s+since)\b",
    r"\b(get|read|fetch|check|inspect|look\s+at)\s+(the\s+)?(node|tree|scene|state)\b",
    r"\b(qual|quais|o\s+que\s+[eÃ©]|mostre?|descreve?|lista?|explica?)\b.*\b(n[oÃ³]|[aÃ¡]rvore|cena|par[aÃ¢]metro)\b",
    # Interrogative starts
    r"^(what|which|how|where|when|who|why|qual|quais|como|onde|quando)\b",
    # Portuguese interrogative / problem-report starts not covered above.
    # "por que" (why) â€" "por" is not in the generic interrogative list above.
    r"^por\s+que\b",
    # "o que aconteceu/deu/houve" â€" past-event questions implying diagnosis.
    r"\b(o\s+que\s+(aconteceu|deu\s+errado|houve))\b",
    # "estou vendo/tendo/encontrando/percebendo" â€" first-person problem reports.
    r"^estou\s+(vendo|tendo|encontrando|percebendo)\b",
    # "parece que/estar" â€" observation / symptom description.
    r"^parece\s+(que|estar)\b",
    # Portuguese analysis / inspection verbs â€" user asking for a look at state.
    r"\banalis[aeio][a-z]*\b",                       # analisa, analise, analisar, analisando
    r"\binspec[ie][a-z]*\b",                         # inspeciona, inspecione, inspecionar
    r"\bverifi[qc][aeioÃº][a-z]*\b",                  # verifica, verifique, verificar
    r"\bconfer[aeiÃ­u][a-z]*\b",                      # confere, conferir, conferiu
    r"\bd[aÃ¡]\s+uma\s+olhada\b",                     # dÃ¡ uma olhada
    r"\bpode\s+(ver|olhar|verificar|conferir|checar|analisar|inspecionar)\b",
    r"\bpode\s+fazer\s+um?\s+screenshot\b",          # pode fazer um screenshot
    r"\bvej[ao]\b",                                  # veja, vejo
]]

_PROPOSAL_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    r"\b(how\s+(would|could|should|do\s+I)|what('?s|\s+is)\s+the\s+(best|smallest|easiest|right|correct)\s+way)\b",
    r"\b(suggest|recommend|propose|advise|what\s+if|could\s+you\s+think|think\s+about)\b",
    r"\b(como\s+(eu\s+)?(faria|poderia|deveria)|qual\s+(seria|Ã©)\s+a\s+(melhor|menor|maior)\s+forma)\b",
    r"\b(suger|recomend|propÃµe?|propor)\b",
]]

_MUTATION_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    # English imperatives
    r"\b(set|change|update|modify|edit|adjust|fix|alter)\s+\w",
    r"\b(wire|connect|link|plug|attach|join)\s+\w",
    r"\b(add|create|insert|make|build|generate)\s+(a\s+)?\w",
    r"\b(remove|delete|disconnect|unlink|detach|destroy)\s+(the\s+)?\w",
    r"\b(rename|move|reorder|duplicate|copy)\s+(the\s+)?\w",
    r"\b(enable|disable|toggle|turn\s+(on|off))\s+(the\s+)?\w",
    # Portuguese â€" verb stems covering infinitive, imperative, subjunctive,
    # gerund and common conjugations (present/past).  Each group ends with
    # \w to require at least one following word character.
    # modify / set / adjust
    r"\b(defin[aei]r?|mud[aeo]u?|mude|alter[aeo]u?|alterar|modific[aeo]u?|modificar|ajust[aeo]u?|ajustar|configur[aeo]u?|configurar|edit[aeo]u?|editar)\b",
    # connect / disconnect
    r"\b(conect[aeo]u?|conectar|lig[aoeu]|ligar|desconect[aeo]u?|desconectar|deslig[aoeu]|desligar)\b",
    # add / create / insert â€" broad conjugation coverage
    r"\b(adicion[aeo]u?|adicionar|adicionando|cri[aeo]u?|criar|crie|criando|inser[ei]u?|inserir|inserindo|ger[aeo]u?|gerar|gerando|constru[Ã­ia]r?|construindo|coloc[aeo]u?|colocar|colocando|inclu[Ã­ia]r?|incluindo|mont[aeo]u?|montar|montando|implement[aeo]u?|implementar|implementando)\b",
    # remove / delete
    r"\b(remov[aeo]u?|remover|removendo|apag[aoeu]|apagar|apagando|delet[aeo]u?|deletar|deletando)\b",
    # rename / move / duplicate
    r"\b(renomei[aeo]u?|renomear|mov[aeo]u?|mover|reorden[aeo]u?|reordenar|duplic[aeo]u?|duplicar|copi[aeo]u?|copiar)\b",
    # do / put / build (irregular verbs)
    r"\b(faz(?:er)?|faÃ§a|fazendo|coloque|ponha|pÃµe)\b",
    # Indirect mutation requests â€" "help me toâ€¦", "I want you toâ€¦", "I need toâ€¦"
    r"\b(me\s+ajud[ae]\s+a\s+\w+)",                         # "me ajuda a parametrizar"
    r"\b(quero|gostaria|preciso)\s+(que\s+(voc[eÃª]\s+)?)?\w",  # "quero que vocÃª crie"
    r"\b(preciso|necessito)\s+(de\s+)?\w+[aei]r\b",          # "preciso adicionar"
    # parametrizar â€" domain-specific verb not in standard groups
    r"\bparametriz[aeo]u?r?\b",
    # execute / run / apply â€" direct execution requests
    # ("executa pra mim", "execute isso", "roda o cÃ³digo", "aplica agora")
    r"\b(execut[aeo][a-z]*|rod[aeo][a-z]*)\b",
    r"\b(pode\s+(executar|rodar|tentar|aplicar|fazer\s+isso|ir\s+em\s+frente))\b",
    r"\b(tenta[a-z]*\s+(executar|rodar|aplicar|fazer))\b",
    # colloquial revert / value-reset requests
    r"\b(pode\s+)?volt(?:a|e|ar)\b.*\b(?:pra|para|to)\s+[-+]?\d+(?:[.,]\d+)?\b",
    r"\b(valor|par[aÃ¢]metro|entrada|sa[iÃ­]da|transla[Ã§c][Ã£a]o|rota[Ã§c][Ã£a]o|escala)\b.*\b(alterad[oa]s?|mudad[oa]s?|modificad[oa]s?)\b.*\b(?:pra|para|to)\s+[-+]?\d+(?:[.,]\d+)?\b",
    # Value assignment patterns
    r"=\s*[\d.]+",                    # x = 1.0
    r"\bpara\s+[\d.]+\b",             # para 1.0
    r"\bto\s+[\d.]+\b",               # to 1.0
    r"\bvalue\s+(of\s+\w+\s+)?to\b",  # value of X to
    # GN interface / socket creation â€" domain-specific (prevents clarification fallback)
    # Catches "socket de entrada", "novo socket float", "preciso de um socket", etc.
    r"\b(novo?|nova?)\s+(socket|input|output|entrada|sa[iÃ­]da)\b",
    r"\bsocket\s+(de\s+)?(entrada|sa[iÃ­]da|float|integer|int|vector|boolean|bool|string|geometry|color|material|image|collection|object)\b",
    r"\b(entrada|sa[iÃ­]da)\s+(de\s+)?(float|integer|int|vector|boolean|bool|string|geometry|color|material)\b",
    r"\bpreciso\s+(de\s+)?(um\s+|uma\s+)?(novo\s+|nova\s+)?(socket|input|output|entrada|sa[iÃ­]da)\b",
    r"\binterface\s+(do?\s+)?(grupo|modificador|[aÃ¡]rvore|GN|geometry)\b",
    r"\b(group\s+)?(input|output)\s+(node|socket|interface)\b",
]]

_CONFIRMATION_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    # Exact short confirmations (full-string match)
    r"^\s*(yes|y|yep|yeah|sure|ok(ay)?|go\s+(ahead|for\s+it)|do\s+it|confirm|execute|proceed|apply|run\s+it)\s*[!.]?\s*$",
    r"^\s*(sim|pode|confirma?|executa?|aplica?|faz\s+(isso|aÃ­)|manda\s*(ver|bala)?)\s*[!.]?\s*$",
    # Confirmation at the START of a longer message ("sim, mas mantenha X",
    # "pode, e também faz Y"). Checked in _looks_like_contextual_script_confirmation
    # (not gated by phase; contextual anchoring limits false-positive risk).
    r"^\s*(sim|pode|ok|claro|confirmed?|yes|sure|go)\s*[.,!;:\-]",
    # Confirmation verb phrases anywhere
    r"\b(pode\s+(ir|fazer|aplicar|executar|rodar))\b",
    r"\b(pode\s+(seguir|continuar|prosseguir))\b",
    r"\b(manda\s+(ver|bala|brasa))\b",
    r"\b(pode\s+aplicar|faz\s+isso|bora|vamo[s]?)\b",
]]

_DENIAL_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    # Exact short denials
    r"^\s*(no|nope|nah|cancel|abort|stop|never\s+mind|forget\s+it|don'?t|do\s+not)\s*[!.]?\s*$",
    r"^\s*(n[aÃ£]o|cancela?|para|esquece?)\s*[!.]?\s*$",
    # Denial at the START of a longer message
    r"^\s*(n[aÃ£]o|cancela|para|stop)\s*[.,!;:\-]",
    # Denial verb phrases
    r"\b(n[aÃ£]o\s+(quero|faz|faÃ§a|execut[ae]|aplic[ae]))\b",
]]

# Drafting mode: patterns detecting "I ran the script" / "executei" etc.
_DRAFT_EXECUTED_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    # Portuguese
    r"^\s*(executei|rodei|apliquei|j[aÃ¡]\s+executei|j[aÃ¡]\s+rodei|feito|pronto|done)\s*[!.]?\s*$",
    r"\b(j[aÃ¡]\s+)?(?:executei|rodei|apliquei|fiz)\s+(?:o\s+)?(?:script|c[oÃ³]digo|draft)\b",
    r"\b(?:script|c[oÃ³]digo|draft)\s+(?:j[aÃ¡]\s+)?(?:foi\s+)?(?:executad[oa]|rodad[oa]|aplicad[oa])\b",
    # English
    r"\bi\s+(?:ran|executed|applied)\s+(?:the\s+)?(?:script|code|draft)\b",
    r"\b(?:script|code|draft)\s+(?:has\s+been\s+)?(?:executed|run|applied)\b",
    r"^\s*(i\s+ran\s+it|done|executed|ran\s+the\s+script)\s*[!.]?\s*$",
    # Onda 5 structured result messages from the work-cycle UI failure button
    # Note: success ("[RESULTADO] Script executado...") is now handled locally
    # in the panel (no agent call) so only the failure prefix needs matching.
    r"^\s*\[RESULTADO\s+DE\s+EXECU",
]]

_DRAFT_EXECUTION_FEEDBACK_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    r"\b(eu\s+)?(rodei|executei|apliquei)\b",
    r"\b(ran|executed|applied)\b",
    r"\b(nada\s+aconteceu|sem\s+efeito|n[aÃ£]o\s+(funcionou|foi|deu)|deu\s+errado|falhou|erro)\b",
    r"\b(nao|n[aã]o)\s+deu\s+certo\b",
    r"\b(slider|sliders|controle|controles)\b.*\b(nao|n[aã]o)\b.*\b(funcion|mex|move|alter|respond)",
    r"\b(nao|n[aã]o)\b.*\b(slider|sliders|controle|controles)\b.*\b(funcion|mex|move|alter|respond)",
    r"\b(sumiu|sumiram|sumindo|desapareceu|desapareceram|apagou)\b",
    r"\b(metacarpo|metacarpos|palma|falange|falanges)\b.*\b(sumiu|sumiram|sumindo|desapareceu|desapareceram|apagou)\b",
    r"\b(control|ctrl)\s*\+?\s*z\b",
    r"\b(partial|parcial|metade|incomplet[oa])\b",
    r"\b(desfiz|undo|ctrl\s*\+?\s*z|voltei\s+atr[aÃ¡]s|reverti|revertido|reverted)\b",
]]

_DRAFT_WRITE_INTENT_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    r"\b(altere|alterar|ajuste|ajustar|corrija|corrigir|mude|mudar|refa[Ã§c]a|refazer)\b.*\b(draft|script|c[oÃ³]digo)\b",
    r"\b(draft|script|c[oÃ³]digo)\b.*\b(altere|alterar|ajuste|ajustar|corrija|corrigir|mude|mudar|refa[Ã§c]a|refazer)\b",
    r"\b(melhor[aei]?r?|arrum[aei]?r?|consert[aei]?r?|repar[aei]?r?|reescrev[ae]r?)\b.*\b(draft|script|c[oÃƒÂ³]digo)\b",
    r"\b(draft|script|c[oÃƒÂ³]digo)\b.*\b(melhor[aei]?r?|arrum[aei]?r?|consert[aei]?r?|repar[aei]?r?|reescrev[ae]r?)\b",
    r"\b(melhorar|arrumar|ajustar|alterar|corrigir|consertar|reparar|reescrever)\b.*\b(problemas?|erro|falha|n[aÃƒÂ£]o\s+(funciona|funcionou|esta\s+funcionando)|aplicando|apliquei|rodei|executei)\b",
    r"\b(diagnostic[ao]r?|diagnosticar)\b.*\b(melhorar|arrumar|corrigir|consertar|ajustar|alterar|draft|script|c[oÃƒÂ³]digo)\b",
    r"\b(melhorar|arrumar|corrigir|consertar|ajustar|alterar)\b.*\b(diagnostic[ao]r?|diagnosticar)\b",
    r"\b(por\s+que|porque)\b.*\b(erro|falh|n[aÃƒÂ£]o\s+funcion)\b.*\b(corrig|arrum|consert|ajust|melhor)\b",
    r"\bn[aÃƒÂ£]o\s+(funciona|funcionou|esta\s+funcionando)\b.*\b(arrum|corrig|consert|ajust|melhor)\b",
    r"\btem\s+que\s+(melhorar|arrumar|corrigir|consertar|ajustar|diagnosticar)\b",
    r"\b(tentar|vamos\s+tentar|tente)\s+(escrever|fazer|criar|gerar)\s+(de\s+)?novo\b",
    r"\b(escrever|fazer|criar|gerar)\s+(de\s+)?novo\b.*\b(draft|script|c[oÃ³]digo)\b",
    r"\b(fix|adjust|change|alter|rewrite|retry|improve|repair)\b.*\b(draft|script|code|problem|error|failure)\b",
]]

_DRAFT_RETRY_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    r"\b(consegue|pode|vc|voc[eê])\s+(tentar|fazer|gerar|escrever|salvar)\s+(de\s+)?novo\b",
    r"\b(tenta|tentar|tent[aã]ramos|refaz|refazer|reescreve|reescrever)\s+(de\s+)?novo\b",
    r"\b(de\s+novo|denovo)\s+(ent[aã]o|agora)?\b",
    r"\b(try|retry|again|one\s+more\s+time)\b",
]]

_DRAFT_HARD_WRITE_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    r"\b(altere|alterar|ajuste|ajustar|corrija|corrigir|mude|mudar|refazer|reescrev\w*)\b",
    r"\b(corrige|arruma|arrumar|conserta|consertar|salva|salvar)\b",
    r"\b(faz|faca|fa.a)\s+(a\s+)?(opcao|op..o|option|estrategia|strategy)\s+[abc123]\b",
    r"\b(aplica|aplicar)\s+(a\s+)?(opcao|op..o|estrategia|strategy)\b",
    r"\b(melhora|melhorar)\b.*\b(agora|ja|j.|entao|ent.o|urgente)\b",
    r"\b(rewrite|fix|adjust|change|alter|save)\b",
]]

_DRAFT_DISCUSSION_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    r"\b(sera|ser.|seria)\s+que\b",
    r"\btalvez\b",
    r"\b(podemos|precisamos|vamos)\s+(agora\s+)?(refletir|pensar|repensar|avaliar|comparar|entender)\b",
    r"\b(refletir|pensar|repensar|raciocinar|diagnosticar|analisar|investigar|avaliar|comparar|decidir)\b.*\b(draft|script|codigo|c.digo|erro|falha|problema|estrat|caminho|opcao|op..o)",
    r"\b(gerar|levantar|ver)\s+(estrategias|estrat.gias|caminhos|opcoes|op..es)\b",
    r"\b(estrategia|estrat.gia|estrategias|estrat.gias|strategy|strategies)\b",
    r"\b(antes\s+de\s+reescrever|antes\s+de\s+corrigir|antes\s+de\s+alterar)\b",
    r"\bqual\b.*\b(estrategia|estrat.gia|caminho|opcao|op..o)\b.*\b(sentido|melhor)\b",
    r"\b(por\s+que|porque|why)\b.*\b(erro|falh|errad|n.o\s+funcion|nada\s+aconteceu|executou|failed|wrong)\b",
    r"\b(o\s+que|que|what)\b.*\b(errad|falh|problema|wrong)\b.*\b(draft|script|codigo|c.digo)\b",
    r"\b(vc|voc.|voce|voc.s)\s+lembra\b.*\berro\b",
    r"\b(lembra|lembrar)\b.*\berro\b",
    r"\bdraft\b.*\b(nem\s+executou|n.o\s+executou|nada\s+aconteceu|n.o\s+funcionou)\b",
    r"\b(revisar|rever)\b.*\b(draft|script|codigo|c.digo)\b",
    r"\bagora\b.*\bdraft\b.*\b(nem\s+executou|n.o\s+executou|nada\s+aconteceu)\b",
    r"\b(erro|falh|n.o\s+funcionou|nada\s+aconteceu)\b.*\b(por\s+que|porque|why)\b",
]]

# Drafting mode: patterns detecting "modify/update the script" refinement intent.
_DRAFT_REFINEMENT_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    # Portuguese â€" asking to change the draft or asking what it does
    r"\b(muda|mude|alter[ae]|modific[ae]|atualiz[ae]|edit[ae]|ajust[ae]|corrij[ae]|troc[ae])\b.*\b(script|c[oÃ³]digo|draft|texto)\b",
    r"\b(script|c[oÃ³]digo|draft)\b.*\b(muda|mude|alter[ae]|modific[ae]|atualiz[ae]|edit[ae]|ajust[ae]|corrij[ae]|troc[ae])\b",
    r"\b(?:no|no\s+)script\b.*\b(adicion[ae]|remov[ae]|tir[ae])\b",
    r"\b(esse|o|este)\s+(draft|script|codigo|c[oÃ³]digo).*(prev[Ãªe]|faz|tem|falta)\b",
    # English
    r"\b(change|update|modify|edit|fix|adjust|correct)\b.*\b(script|code|draft)\b",
    r"\b(script|code|draft)\b.*\b(change|update|modify|edit|fix|adjust|correct)\b",
    r"\bin\s+the\s+(script|draft|code)\b.*\b(add|remove|replace)\b",
    r"\b(does|is)\s+(this|the)\s+(draft|script).*(do|have|miss|predict)\b",
]]

_DRAFT_CONTINUE_REFINEMENT_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    r"\b(pode\s+)?(acabar|terminar|finalizar|completar)\s+(o\s+)?(draft|script|c[oÃ³]digo)\b",
    r"\b(continua|continuar|continue|segue|prossegue|termina|finish|keep\s+going)\b",
    r"\bsegue\s+desse\s+ponto\b",
    r"\bajusta\s+(o\s+)?draft\b",
]]

_DRAFT_READ_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    r"\b(lembra|lembrar|recorda|recordar)\b.*\b(o\s+que|que)\b.*\b(fazendo|tentando|est[aÃ¡]vamos|paramos)\b",
    r"\b(onde\s+paramos|qual\s+foi\s+a\s+[uÃº]ltima\s+vers[aÃ£]o)\b",
    r"\b(consegue|pode)\s+(ler|ver|reler|abrir)\b.*\b(draft|script|c[oÃ³]digo)\b",
    r"\b(ler|reler|l[eÃª]|ver|abre|abrir)\b.*\b(draft|script|c[oÃ³]digo)\b",
    r"\b(o\s+que|que)\s+(esse|este|o)?\s*(draft|script|c[oÃ³]digo)\s+(faz|tem|prev[eÃª])\b",
    r"\b(explica|explique|me\s+explica|resume|resuma|resumir)\b.*\b(draft|script|c[oÃ³]digo)\b",
    r"\b(draft|script|c[oÃ³]digo)\b.*\b(atual|salvo|corrente|[uÃº]ltima\s+vers[aÃ£]o)\b",
    r"\b(do\s+you\s+remember|remember)\b.*\b(what\s+we\s+were|where\s+we\s+left|trying\s+to\s+do)\b",
    r"\b(where\s+did\s+we\s+leave\s+off|where\s+were\s+we|last\s+version)\b",
    r"\b(can|could|please)?\s*(read|open|show|recall)\b.*\b(draft|script|code)\b",
    r"\b(what\s+does|explain|summari[sz]e)\b.*\b(draft|script|code)\b",
    r"\b(current|latest)\s+(draft|script|code|version)\b",
]]

_FACTUAL_TREE_INQUIRY_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    r"^\s*(qual|quais|what|which)\b.*\b(nome|name)\b.*\b(n[oó]|node|nodos?|nodes?)\b",
    r"^\s*(qual|quais|what|which)\b.*\b(n[oó]|node|nodos?|nodes?)\b.*\b(controla|controlam|controls?|drives?)\b",
    r"^\s*(qual|quais|what|which)\b.*\b(socket|par[aâ]metro|parameter|input|entrada)\b",
    r"\b(mostra|mostre|show|lista|liste|list)\b.*\b(n[oó]s?|nodes?|socket|par[aâ]metros?|parameters?)\b",
    r"\b(estado|state|estrutura|structure)\b.*\b([aá]rvore|tree|gn|geometry\s+nodes)\b",
]]

_ANSWER_CORRECTION_INQUIRY_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    r"\b(vc|voc[eê]|você)\s+falou\b.*\b(n[oó]|node|cube|label|metacarpo|falange)\b",
    r"\b(sua|a)\s+resposta\b.*\b(errad[ao]|incorret[ao]|n[oó]\s+errad[ao]|node\s+errad[ao])\b",
    r"\b(isso|essa\s+label|esse\s+label)\b.*\b(indica|mostra|quer\s+dizer)\b.*\b(n[oó]|node)\s+errad[ao]\b",
    r"\bn[aã]o\s+(e|é)\s+d[oa]\s+(metacarpo|falange|palma|punho)\b",
]]

_DRAFT_SUBJECT_RE = re.compile(r"\b(draft|script|c[oó]digo|code|texto)\b", re.I)
_WRITE_OR_FEEDBACK_RE = re.compile(
    r"\b("
    r"corrig|consert|arrum|ajust|muda|altera|revis|reescrev|salv|escrev|"
    r"erro|falh|n[aã]o\s+funcion|nada\s+aconteceu|sem\s+efeito|desfiz|revert"
    r")\b",
    re.I,
)

_DRAFT_WRITE_REQUEST_PATTERNS: list[re.Pattern] = [re.compile(p, re.I) for p in [
    # Portuguese
    r"\b(escrever?|cri[ae]r?|fazer?|adicionar?|gerar?)\s+(o|um|uma)?\s*(draft|script|c[oÃ³]digo)\b",
    r"\b(vamos\s+)?escrever\s+o\s+draft\b",
    # English
    r"\b(let'?s\s+)?(write|create|make|generate)\s+(the\s+)?(draft|script|code)\b",
]]

_CONTEXTUAL_SCRIPT_CONFIRMATION_RE: re.Pattern[str] = re.compile(
    r"\b(script|c[oÃ³]digo|python|bpy|execute_code|socket|painel|panel|interface|biomodelo)\b",
    re.IGNORECASE,
)

_RECENT_CONFIRMATION_PROMPT_RE: re.Pattern[str] = re.compile(
    r"\b(confirm|confirma|confirmo|ok|pode confirmar|rodar o script|execute agora|execute now|script)\b",
    re.IGNORECASE,
)


def _matches_any(patterns: list[re.Pattern], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def _recent_history_texts(session: Any, limit: int = 6) -> list[str]:
    history = getattr(getattr(session, "history", None), "messages", []) or []
    texts: list[str] = []
    for item in history[-limit:]:
        content = str(getattr(item, "content", "") or "").strip()
        if content:
            texts.append(content)
    return texts


def _looks_like_contextual_script_confirmation(session: Any, message: str) -> bool:
    msg = (message or "").strip()
    if not msg:
        return False
    if not _matches_any(_CONFIRMATION_PATTERNS, msg):
        return False

    recent = _recent_history_texts(session)
    joined_recent = "\n".join(recent)
    if _CONTEXTUAL_SCRIPT_CONFIRMATION_RE.search(msg):
        return True
    if _CONTEXTUAL_SCRIPT_CONFIRMATION_RE.search(joined_recent) and _RECENT_CONFIRMATION_PROMPT_RE.search(joined_recent):
        return True
    return False


def _has_active_draft(session: Any) -> bool:
    es = getattr(session, "execution_state", None)
    if es is None:
        return False
    if getattr(es, "current_draft", None) is not None:
        return True
    if int(getattr(es, "draft_revision", 0) or 0) > 0:
        return True
    return bool(getattr(es, "drafting_mode", False)) and bool(getattr(es, "draft_block_name", ""))


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class TurnRouter:
    """Classifies a user message into one of the draft-first product intents.

    The classifier never makes an LLM call.  When genuinely ambiguous it
    defaults to the more conservative class (context inquiry over draft creation when read intent is clearer).
    """

    def classify(self, session: Any, message: str) -> tuple[TurnClass, ClassifierMeta]:
        """Return ``(TurnClass, ClassifierMeta)`` for *message* given *session* state.

        Routing logic lives in ``_classify_inner``; this wrapper enriches the
        returned meta with observability fields (``turn_intent``,
        ``session_state``) that are logged to the journal but never influence
        dispatch.
        """
        turn_class, meta = self._classify_inner(session, message)
        try:
            from .routing_obs import enrich_meta_observability
            enrich_meta_observability(meta, session, message)
        except Exception:
            pass
        return turn_class, meta

    def _classify_inner(self, session: Any, message: str) -> tuple[TurnClass, ClassifierMeta]:
        """Core routing logic — do not call directly outside tests."""
        msg = (message or "").strip()
        msg_lower = msg.lower()
        signals: list[str] = []

        # ------------------------------------------------------------------
        # 1. Phase-gated routing — legacy string guards
        # ------------------------------------------------------------------
        phase = session.execution_state.phase

        # awaiting_confirmation was removed from EXECUTION_PHASES in Onda 1F-B.
        # Sessions loaded directly from disk may still carry it as a raw string;
        # normalise to idle/drafting before any routing logic runs.
        if phase == "awaiting_confirmation":
            signals.append("legacy_awaiting_confirmation_purged")
            phase = "drafting" if _has_active_draft(session) else "idle"

        if phase == "failed":
            signals.append("legacy_failed_phase_purged")
            return TurnClass.EXECUTION_FEEDBACK, ClassifierMeta(
                turn_class=TurnClass.EXECUTION_FEEDBACK,
                signals=signals,
                raw_message=msg,
            )

        # Drafting phase gate: route everything to the unified draft workspace
        if phase == "drafting":
            if _matches_any(_DRAFT_EXECUTION_FEEDBACK_PATTERNS, msg) or _matches_any(_DRAFT_EXECUTED_PATTERNS, msg):
                signals.append("draft_execution_feedback_pattern")
                return TurnClass.EXECUTION_FEEDBACK, ClassifierMeta(
                    turn_class=TurnClass.EXECUTION_FEEDBACK,
                    signals=signals,
                    raw_message=msg,
                )
            if _is_factual_tree_inquiry(msg):
                signals.append("factual_tree_inquiry_in_drafting")
                needs_refresh = _session_needs_baseline_refresh(session, msg)
                return TurnClass.CONTEXT_INQUIRY, ClassifierMeta(
                    turn_class=TurnClass.CONTEXT_INQUIRY,
                    signals=signals,
                    needs_baseline_refresh=needs_refresh,
                    raw_message=msg,
                )
            if _is_answer_correction_inquiry(msg):
                signals.append("answer_correction_in_drafting")
                needs_refresh = _session_needs_baseline_refresh(session, msg)
                return TurnClass.CONTEXT_INQUIRY, ClassifierMeta(
                    turn_class=TurnClass.CONTEXT_INQUIRY,
                    signals=signals,
                    needs_baseline_refresh=needs_refresh,
                    raw_message=msg,
                )
            if _matches_any(_DENIAL_PATTERNS, msg):
                signals.append("draft_state_control_pattern")
                return TurnClass.STATE_CONTROL, ClassifierMeta(
                    turn_class=TurnClass.STATE_CONTROL,
                    signals=signals,
                    raw_message=msg,
                )
            signals.append("draft_workspace_routing")
            return TurnClass.DRAFT_WORKSPACE, ClassifierMeta(
                turn_class=TurnClass.DRAFT_WORKSPACE,
                signals=signals,
                raw_message=msg,
            )

        if is_scene_wide_gn_inspection_request(msg):
            signals.append("scene_wide_gn_inspection")
            needs_refresh = _session_needs_baseline_refresh(session, msg)
            return TurnClass.CONTEXT_INQUIRY, ClassifierMeta(
                turn_class=TurnClass.CONTEXT_INQUIRY,
                signals=signals,
                needs_baseline_refresh=needs_refresh,
                raw_message=msg,
            )

        # In REPAIRING/STRATEGY_PROPOSED state the agent has already analyzed the
        # failure.  A bare approval ("pode", "sim") means "write the fix now."
        # The normal contextual-confirmation gate requires recent history that may
        # not be present after snapshot restore, so we check the state explicitly.
        _repair_state = str(getattr(getattr(session, "execution_state", None), "session_state", "") or "")
        if _repair_state in {"REPAIRING", "STRATEGY_PROPOSED"} and _matches_any(_CONFIRMATION_PATTERNS, msg):
            signals.append("repairing_write_approval")
            return TurnClass.DRAFT_WORKSPACE, ClassifierMeta(
                turn_class=TurnClass.DRAFT_WORKSPACE,
                confidence="medium",
                signals=signals,
                raw_message=msg,
            )

        if _looks_like_contextual_script_confirmation(session, msg):
            signals.append("contextual_script_confirmation")
            _write_eligible = _has_active_draft(session) or _repair_state in {"REPAIRING", "STRATEGY_PROPOSED"}
            draft_class = TurnClass.DRAFT_WORKSPACE if _write_eligible else TurnClass.CONTEXT_INQUIRY
            return draft_class, ClassifierMeta(
                turn_class=draft_class,
                confidence="medium",
                signals=signals,
                raw_message=msg,
            )

        # ------------------------------------------------------------------
        # 2. Trivial social patterns
        # ------------------------------------------------------------------
        if _matches_any(_GREETING_PATTERNS, msg):
            signals.append("greeting_pattern")
            return TurnClass.TRIVIAL_CHAT, ClassifierMeta(
                turn_class=TurnClass.TRIVIAL_CHAT,
                signals=signals,
                raw_message=msg,
            )

        # ------------------------------------------------------------------
        # 3. Explicit baseline refresh request
        # ------------------------------------------------------------------
        if _matches_any(_BASELINE_REFRESH_PATTERNS, msg):
            signals.append("baseline_refresh_pattern")
            return TurnClass.CONTEXT_INQUIRY, ClassifierMeta(
                turn_class=TurnClass.CONTEXT_INQUIRY,
                signals=signals,
                raw_message=msg,
            )

        # ------------------------------------------------------------------
        # 3.5. Draft Recovery intent (Idle phase intercept)
        # ------------------------------------------------------------------
        active_draft = _has_active_draft(session)
        hard_write_intent = _matches_any(_DRAFT_HARD_WRITE_PATTERNS, msg)
        discussion_intent = _matches_any(_DRAFT_DISCUSSION_PATTERNS, msg)
        tentative_discussion = discussion_intent and bool(re.search(
            r"\b(sera|ser.|talvez|refletir|pensar|repensar|avaliar|comparar|estrategia|estrat.gia|estrategias|estrat.gias|caminhos|opcoes|op..es|antes\s+de)\b",
            msg,
            re.I,
        ))
        feedback_intent = (
            _matches_any(_DRAFT_EXECUTION_FEEDBACK_PATTERNS, msg)
            or _matches_any(_DRAFT_EXECUTED_PATTERNS, msg)
        )

        if active_draft and feedback_intent:
            signals.append("draft_execution_feedback_recovery")
            return TurnClass.EXECUTION_FEEDBACK, ClassifierMeta(
                turn_class=TurnClass.EXECUTION_FEEDBACK,
                signals=signals,
                raw_message=msg,
            )

        if active_draft and (
            hard_write_intent 
            or _matches_any(_DRAFT_RETRY_PATTERNS, msg)
            or discussion_intent 
            or _matches_any(_DRAFT_WRITE_INTENT_PATTERNS, msg)
            or _matches_any(_DRAFT_CONTINUE_REFINEMENT_PATTERNS, msg)
            or _matches_any(_DRAFT_READ_PATTERNS, msg)
            or _matches_any(_DRAFT_REFINEMENT_PATTERNS, msg)
        ):
            signals.append("draft_workspace_recovery")
            return TurnClass.DRAFT_WORKSPACE, ClassifierMeta(
                turn_class=TurnClass.DRAFT_WORKSPACE,
                signals=signals,
                raw_message=msg,
            )

        refinement_recovery = _matches_any(_DRAFT_REFINEMENT_PATTERNS, msg)
        explicit_refinement_write = bool(re.search(
            r"\b(muda|mude|altera|altere|modifica|modifique|atualiza|atualize|edita|edite|ajusta|ajuste|corrige|corrija|troca|troque)\b.*\b(draft|script|texto)\b|"
            r"\b(draft|script)\b.*\b(muda|mude|altera|altere|modifica|modifique|atualiza|atualize|edita|edite|ajusta|ajuste|corrige|corrija|troca|troque)\b",
            msg,
            re.I,
        ))
        if refinement_recovery and (
            hard_write_intent
            or _matches_any(_DRAFT_WRITE_INTENT_PATTERNS, msg)
            or explicit_refinement_write
        ):
            signals.append("draft_refinement_write_pattern")
            return TurnClass.DRAFT_WORKSPACE, ClassifierMeta(
                turn_class=TurnClass.DRAFT_WORKSPACE,
                signals=signals,
                raw_message=msg,
            )

        if refinement_recovery:
            signals.append("draft_inquiry_recovery")
            return TurnClass.CONTEXT_INQUIRY, ClassifierMeta(
                turn_class=TurnClass.CONTEXT_INQUIRY,
                signals=signals,
                raw_message=msg,
            )

        # ------------------------------------------------------------------
        # 4. Proposal shape ("how would youâ€¦", "suggestâ€¦")
        #    Must come before mutation check because proposals are less
        #    risky â€" prefer them when both signals fire.
        # ------------------------------------------------------------------
        if is_structured_operational_followup(msg):
            signals.append("structured_operational_followup")
            needs_refresh = _session_needs_baseline_refresh(session, msg)
            draft_class = TurnClass.DRAFT_WORKSPACE
            return draft_class, ClassifierMeta(
                turn_class=draft_class,
                confidence="medium",
                signals=signals,
                needs_baseline_refresh=needs_refresh,
                raw_message=msg,
            )

        if is_natural_continuation_request(msg):
            signals.append("natural_continuation")
            draft_class = TurnClass.DRAFT_WORKSPACE if _has_active_draft(session) else TurnClass.CONTEXT_INQUIRY
            return draft_class, ClassifierMeta(
                turn_class=draft_class,
                confidence="medium",
                signals=signals,
                raw_message=msg,
            )

        is_proposal = _matches_any(_PROPOSAL_PATTERNS, msg)
        is_mutation = _matches_any(_MUTATION_PATTERNS, msg)
        is_diagnosis = _matches_any(_DIAGNOSIS_PATTERNS, msg)

        if is_proposal:
            signals.append("proposal_pattern")
            needs_refresh = _session_needs_baseline_refresh(session, msg)
            return TurnClass.CONTEXT_INQUIRY, ClassifierMeta(
                turn_class=TurnClass.CONTEXT_INQUIRY,
                signals=signals,
                needs_baseline_refresh=needs_refresh,
                raw_message=msg,
            )

        # ------------------------------------------------------------------
        # 4.5. Explicit draft write/create intent
        # ------------------------------------------------------------------
        if _matches_any(_DRAFT_WRITE_REQUEST_PATTERNS, msg):
            signals.append("draft_write_request_pattern")
            needs_refresh = _session_needs_baseline_refresh(session, msg)
            return TurnClass.DRAFT_WORKSPACE, ClassifierMeta(
                turn_class=TurnClass.DRAFT_WORKSPACE,
                signals=signals,
                needs_baseline_refresh=needs_refresh,
                raw_message=msg,
            )

        # ------------------------------------------------------------------
        # 5. Mutation (imperative change intent)
        # ------------------------------------------------------------------
        if is_mutation:
            signals.append("mutation_pattern")
            needs_refresh = _session_needs_baseline_refresh(session, msg)
            draft_class = TurnClass.DRAFT_WORKSPACE
            return draft_class, ClassifierMeta(
                turn_class=draft_class,
                signals=signals,
                needs_baseline_refresh=needs_refresh,
                raw_message=msg,
            )

        # ------------------------------------------------------------------
        # 6. Diagnosis (interrogative / read intent)
        # ------------------------------------------------------------------
        if is_diagnosis:
            signals.append("diagnosis_pattern")
            needs_refresh = _session_needs_baseline_refresh(session, msg)
            return TurnClass.CONTEXT_INQUIRY, ClassifierMeta(
                turn_class=TurnClass.CONTEXT_INQUIRY,
                signals=signals,
                needs_baseline_refresh=needs_refresh,
                raw_message=msg,
            )

        # ------------------------------------------------------------------
        # 7. Continuation (retomar resposta truncada)
        #    Verificado ANTES do default clarification para que "segue" /
        #    "continue" nÃ£o caia em Haiku+600 tokens.
        # ------------------------------------------------------------------
        if _matches_any(_CONTINUATION_PATTERNS, msg):
            signals.append("continuation_pattern")
            draft_class = TurnClass.DRAFT_WORKSPACE if _has_active_draft(session) else TurnClass.CONTEXT_INQUIRY
            return draft_class, ClassifierMeta(
                turn_class=draft_class,
                signals=signals,
                raw_message=msg,
            )

        # ------------------------------------------------------------------
        # 8. Default: context inquiry (Modern Architecture)
        # ------------------------------------------------------------------
        signals.append("default_context_inquiry")
        return TurnClass.CONTEXT_INQUIRY, ClassifierMeta(
            turn_class=TurnClass.CONTEXT_INQUIRY,
            confidence="low",
            signals=signals,
            raw_message=msg,
        )


def _is_factual_tree_inquiry(message: str) -> bool:
    """True for narrow read-only questions about the live GN tree.

    In drafting phase this prevents factual questions from being treated as
    draft diagnosis/refinement. Draft/script questions remain in the draft
    workspace, and any write/feedback wording still goes through the safer
    draft/execution paths.
    """
    msg = str(message or "").strip()
    if not msg:
        return False
    if _DRAFT_SUBJECT_RE.search(msg):
        return False
    if _WRITE_OR_FEEDBACK_RE.search(msg):
        return False
    return _matches_any(_FACTUAL_TREE_INQUIRY_PATTERNS, msg)


def _is_answer_correction_inquiry(message: str) -> bool:
    """True when the user is correcting our previous factual node reading."""
    msg = str(message or "").strip()
    if not msg:
        return False
    if _DRAFT_SUBJECT_RE.search(msg):
        return False
    return _matches_any(_ANSWER_CORRECTION_INQUIRY_PATTERNS, msg)


def _session_needs_baseline_refresh(session: Any, message: str) -> bool:
    """Return True if the handler should pre-refresh the baseline."""
    bw = getattr(session, "baseline_workspace", None)
    if bw is None:
        return True
    if getattr(bw, "stale", False):
        return True
    if not getattr(bw, "structural_summary", ""):
        return True
    return False

