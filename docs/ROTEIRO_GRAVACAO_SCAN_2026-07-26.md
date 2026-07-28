# Roteiro de gravação — reprodução do scan pelo biomodelo

Aid de tela para a gravação via **Cowork → + → Record a skill**.
Deixe aberto no segundo monitor. Não leia em voz alta — é lembrete, não script.

Objetivo da tomada: **um scan, uma mão, do import ao encaixe aprovado.**
Não é demo, não é aula. É você trabalhando e falando o que pensa.

---

## Antes de apertar gravar

- [ ] Blender aberto, bridge ligada, `.blend` no estado inicial (scan **não** importado)
- [ ] Arquivo do scan localizado no disco, caminho conhecido — não gaste a tomada procurando
- [ ] Baseline capturado (Claude roda `capture_state.py antes`)
- [ ] Fechar o que não for Blender — a gravação pega a tela inteira
- [ ] Ensaio seco de 2 min **sem gravar**: só confirmar onde está cada coisa
- [ ] Microfone testado

---

## 3 regras de ouro

1. **Digite, não arraste.** N-panel e campos de socket: valor digitado aparece na tela e nas
   teclas. Gizmo arrastado vira "arrasta até parecer certo" — irreproduzível.
2. **Narre o critério, não a ação.** "Clico em importar" é inútil, a tela já mostra.
   "Uso OBJ porque o PLY do scanner vem sem escala" é ouro.
3. **Erre em voz alta.** Se rejeitar um encaixe, diga *o que* estava errado e *como percebeu*.
   Rejeição explicada vale mais que acerto silencioso.

---

## Nível da narração

Existe um nível certo. Acima e abaixo dele a gravação não vale nada.

| Nível | Exemplo | Valor |
|---|---|---|
| Baixo demais | "clico aqui, arrasto ali" | zero — a tela já mostra |
| **Certo** | "ancoro pelo estiloide ulnar porque é o ponto que menos deforma com a pose; se eu ancorasse pela cabeça do 3º MC, uma flexão de punho no scan jogaria tudo fora" | **é isso** |
| Alto demais | "a mão tem 27 ossos e o arco transversal é fundamental na preensão" | zero — é livro, não é você |

O nível certo é **decisão + alternativa rejeitada + por quê**. A alternativa rejeitada é
a parte que todo mundo pula e é justamente onde mora a regra.

Mais duas exigências de nível:

- **Dê o número mesmo chutando.** "Uns 2 mm, acho" >>> "pouquinho". Chute sinalizado vira
  limiar testável; "pouquinho" não vira nada.
- **Nomeie igual sempre.** Se é estiloide, é estiloide toda vez — não "aquele ossinho ali".
  A transcrição é a entrada; nomenclatura instável degrada a skill inteira.

---

## Como falar com o Cowork

Você não narra pra uma câmera nem pra um aluno. **Você está instruindo um colega que vai
fazer essa tarefa sozinho, num scan que ele nunca viu, sem você na sala.** Segure essa
imagem e o nível da narração se corrige sozinho.

### Abertura — antes do primeiro clique (~45 s)

Fale isso em voz alta, com suas palavras:

> "Vou te ensinar a encaixar o biomodelo paramétrico da mão num scan 3D de paciente.
>
> O gatilho é: chegou um scan novo de uma mão, preciso do biomodelo reproduzindo aquela
> mão específica.
>
> A entrada é um arquivo de scan e o arquivo Blender com o biomodelo. A saída é o
> biomodelo alinhado e com os parâmetros ajustados, com erro residual dentro da
> tolerância — vou dizer qual no fim.
>
> São quatro etapas: importar o scan, triar se ele presta, alinhar rigidamente por
> landmarks anatômicos, e ajustar os parâmetros do modelo. Vou narrar o critério de
> cada decisão, não só o clique."

### O que varia e o que não varia

**Diga isso explicitamente durante a gravação.** É o que evita que a skill grave os
números do Edu como se fossem lei.

- **Varia a cada execução:** caminho do arquivo, a pessoa escaneada, a pose, todos os
  valores numéricos de socket, a magnitude das correções
- **Nunca varia:** quais landmarks ancoram, a ordem de ancoragem, a ordem em que os
  sockets são tocados, o critério de aprovação

### Quando ele deve parar e perguntar

Diga em voz alta cada vez que encontrar um desses:

- Scan com defeito que você não sabe se dá pra salvar
- Landmarks que conflitam além da tolerância
- Residual que não converge por mais que ajuste
- Qualquer caso em que **você mesmo** chamaria alguém

### Encerramento — antes de parar a gravação

> "Terminei. O resultado bom é esse: residual de N mm na região X. Se der mais que isso,
> não aprove — volte pro alinhamento rígido antes de mexer em parâmetro."

---

## Bloco 1 — Import

- Que formato, e por quê esse
- Escala / unidades: o scanner entrega em quê? converte pra quê?
- Eixo up / forward: qual, e como você sabe que está certo
- Alguma limpeza imediata (decimate, remove doubles, normais)?

## Bloco 2 — Triagem do scan

- O que você olha **primeiro** pra saber se o scan presta
- Que defeito faz você descartar o scan em vez de tentar consertar
- Buracos, ruído, dedos grudados: o que tolera, o que não

## Bloco 3 — Alinhamento rígido

- Quais landmarks você ancora — nomeie em voz alta cada um
- Em que **ordem** ancora, e por que essa ordem
- Quando dois landmarks conflitam, **qual você privilegia** e por quê
- Move o biomodelo até o scan, ou o scan até o biomodelo? por quê?
- Origem/pivô: onde está, precisou mexer?

## Bloco 4 — Ajuste paramétrico

Para cada socket que tocar, fale a tríade:

> "medi **[o quê]** no scan, deu **[quanto]**, então **[socket]** vai pra **[valor]**"

- Como você mede no scan (régua? empírico? de onde a onde exatamente?)
- Em que **ordem** mexe nos sockets — o que trava primeiro
- Qual socket é causa e qual é consequência (o que você nunca mexe direto)
- Quando o desvio é do *tamanho* (comprimento) e quando é da *pose* (flexão/abdução)
  — esse discernimento é o mais difícil de automatizar, gaste tempo aqui

## Bloco 5 — Julgamento

- O que te faz dizer "tá bom"
- **Quantos mm** de residual você aceita — chute em voz alta se não souber
- Onde o encaixe *precisa* estar perfeito e onde pode folgar
  (a órtese não usa a mão inteira — diga qual região manda)
- O que você olharia depois pra confirmar que não errou

---

## Depois da tomada

1. Claude roda `capture_state.py depois` e faz o diff contra o baseline
2. **Leia a skill gerada antes de reusar** (checklist abaixo)
3. Você passa o conteúdo dela pro Claude Code
4. Cruzamento: narração dá o **porquê**, diff dá o **número** → v1 da rotina automática

Sem o passo 1 a gravação vira um roteiro sem gabarito.

### Checklist de revisão da skill gerada

A gravação captura a tela literal, então ela **vai** ter colado coisa específica demais:

- [ ] Caminhos de arquivo do scan de hoje virando regra
- [ ] Valores de socket do Edu tratados como padrão em vez de exemplo
- [ ] Nomes de objeto da cena atual (`Sombra_Edu_Garra_D` etc.) hardcoded
- [ ] Passos de UI que na verdade deveriam ir pela bridge
- [ ] Algum critério que você narrou errado ou pela metade

Corrija na skill, ou anote pro Claude Code corrigir na rotina.
