---
title: Roadmap de implementação — Biomodelo V2
applies_when: implementation_plan,biomodel_refactor,skin_migration,clinical_adapter,anchors
topics: biomodelo_v2,pele,sdf,remesh,clinical,anchors,validation
priority: high
lang: pt
status: in_progress
source_kind: live_blend_audit
---
# Roadmap de implementação — Biomodelo V2

## Escopo

Plano baseado na inspeção somente leitura de
`F:\Biomodelo_Refactor.blend`, realizada em 2026-07-25 pelo bridge na porta
65432.

O foco imediato é terminar `Biomodelo_v2` sem alterar ou apagar a árvore viva
antiga. A integração com a órtese entra depois que a saída clínica do V2 estiver
validada.

### O que significa "clínico" neste plano

`Biomodelo_Clinico.002` é o nome da camada de controles já existente no
arquivo. Ela não é outro biomodelo e o nome não significa que o modelo já tenha
validação clínica formal.

Seu papel é:

- expor medidas e sliders compreensíveis para quem ajusta o caso;
- derivar comprimentos e espessuras internas;
- alimentar a implementação geométrica.

Para evitar ambiguidade, a versão V2 dessa camada passa a ser chamada neste
plano de `BM_AjusteScan_v2`. O objetivo não é inventar uma nova interface: é
preservar o conjunto de sliders que já funcionou bem, registrar seus valores por
caso e validá-lo contra todos os scans disponíveis.

## Estado atual observado

`Biomodelo_v2` já contém:

```text
BM_Deriv_Punho_Carpo
BM_Deriv_Palma
BM_Deriv_MCP
  -> BM_Antebraco_Punho
  -> 4 × BM_Dedo_Longo
  -> BM_Polegar
  -> BM_Montagem
  -> Geometry
```

A saída atual é a geometria crua depois da pose, montagem, espelho e correção de
faces. Não existe estágio de remesh/pele dentro do V2.

O objeto `BM_v2_DEV` avaliado possui:

- 1.762 vértices;
- bounding box aproximada de 103,419 × 456,184 × 108,249 unidades do projeto.

O objeto clínico antigo também possui 1.762 vértices no modo atual, mas usa
outros parâmetros e transform de objeto. A igualdade de contagem é um bom sinal,
mas não prova paridade geométrica.

Uma auditoria recursiva percorreu os 16 grupos alcançáveis a partir de
`Biomodelo_v2`. Não foram encontrados `Input Index`, `Sample Index`,
`Named Attribute` ou `Store Named Attribute`. Portanto, a arquitetura V2 atual
não usa índice ou atributo de malha como identidade entre seus módulos.

Na árvore antiga, a saída é:

```text
geometria crua
  -> espelho + Flip Faces
  -> Switch_Remesh
       false: geometria crua
       true: Mesh to Volume -> Volume to Mesh
  -> Ortese_Pele_SDF_Embutida
  -> Switch_Pele
  -> Geometry
```

Parâmetros embutidos observados na árvore viva:

- pele: voxel 5,46; folga 0,33; fechamento 28,52; suavização 7;
- remesh: densidade 0,85; voxel amount 131,3; interior band 149,7;
- volume para mesh: voxel size 5,1; threshold 0,01; adaptivity 0,34.

Esses valores devem ser tratados inicialmente como uma calibração legada a ser
reproduzida, não como valores universais.

## Objetivo científico revisado

O marco anterior à órtese é uma validação final do espaço de parâmetros:

```text
congelar Biomodelo V2
  -> ajustar todos os scans com o mesmo protocolo
  -> registrar vetor inicial e final de parâmetros
  -> medir qualidade regional da aproximação
  -> analisar uso, redundância e limites dos sliders
  -> congelar a interface V2 validada
  -> iniciar integração com a órtese
```

Essa validação deve responder:

1. O mesmo conjunto de parâmetros reproduz diferentes anatomias sem editar a
   topologia?
2. Quais sliders são usados com frequência e magnitude relevante?
3. Quais ficam sempre próximos do default ou são substituídos por outros?
4. Quais parâmetros atingem os limites da interface?
5. Quais regiões do scan continuam com erro sistemático?

## Restrição crítica de interface

Não substituir diretamente o `node_tree` do nó `Nucleo_Biomodelo` em
`Biomodelo_Clinico.002`.

Motivo:

- `Biomodelo` possui 93 entradas;
- `Biomodelo_v2` possui 125 entradas;
- somente 84 nomes são comuns;
- vários identificadores `Socket_*` possuem significados diferentes nas duas
  interfaces;
- quatro conexões atuais do wrapper clínico não têm destino homônimo no V2:
  `Largura Metacarpo`, `Palma - Largura ossos`, `Remesh (volume)` e
  `Pele (SDF)`.

Uma troca automática por identificador pode ligar um parâmetro clínico ao
controle errado sem produzir erro visível. O adaptador clínico V2 deve ser
construído explicitamente por semântica.

## Priorização

Escala:

- ganho: 1 baixo, 5 muito alto;
- complexidade: 1 simples, 5 alta;
- risco: risco de regressão se feito sem isolamento e testes.

| Ordem | Entrega | Ganho | Complexidade | Risco |
|---:|---|---:|---:|---:|
| P0 | baseline e cópia de trabalho do V2 | 5 | 1 | baixo |
| P0 | `BM_Acabamento_v2` com remesh/pele | 5 | 2 | médio |
| P0 | `BM_AjusteScan_v2` + registro por caso | 5 | 3 | alto |
| P0 | protocolo único de ajuste e métricas | 5 | 2 | médio |
| P1 | replicar todos os scans | 5 | 4 | médio |
| P1 | analisar e congelar parâmetros finais | 5 | 3 | médio |
| P2 | contrato mínimo de anchors fora da pele | 4 | 3 | médio |
| P2 | `ORT_Clearance_Field_v0` diagnóstico | 4 | 3 | médio |
| P2 | `ort_uv`, `patch_id` e frame de superfície | 4 | 4 | médio |
| P3 | limpeza de backups e reorganização final | 2 | 2 | alto se antecipado |

## Fase 0 — congelar o estado atual

### Objetivo

Criar uma referência recuperável antes de tocar na saída do V2.

### Implementação

1. Duplicar `Biomodelo_v2` como backup com timestamp
   `Biomodelo_v2_PRE_PELE_*`.
2. Trabalhar inicialmente em `Biomodelo_v2_DEV_PELE`, conectado a um objeto de
   teste separado.
3. Capturar:
   - contagem de vértices, arestas e faces;
   - bounding box;
   - renderizações frontal, lateral e isométrica;
   - tempo de avaliação;
   - parâmetros usados.
4. Registrar explicitamente a convenção de unidade numérica do arquivo.

### Aceite

- árvore original e objeto atual continuam intactos;
- a geometria crua da cópia coincide com o baseline antes da pele;
- existe um caminho simples de retorno.

## Fase 1 — migrar a pele para um módulo V2

### Decisão arquitetural

Criar `BM_Acabamento_v2` depois de `BM_Montagem`.

Não editar diretamente `Ortese_Pele_SDF_Embutida` nem `Garantir_Folga`, porque
eles pertencem ao legado e podem ter outros consumidores. O módulo V2 pode
envolver uma cópia congelada desses grupos na primeira versão.

Fluxo:

```text
M04_Montagem.Geometria
  -> BM_Acabamento_v2
       -> Raw
       -> Remesh legado compatível
       -> BM_Pele_SDF_v2
  -> Group Output.Geometry
```

### Interface mínima

Entradas:

- `Geometry`;
- `Aplicar Remesh`;
- `Aplicar Pele`;
- parâmetros de remesh;
- `Pele - Voxel`;
- `Pele - Folga`;
- `Pele - Fechamento`;
- `Pele - Suavização`.

Saídas:

- `Geometry`, mantendo o nome da saída pública atual;
- `Geometry Raw`, opcional para depuração e validação.

Os dois switches devem iniciar desligados, preservando o comportamento atual do
V2.

### Compatibilidade

Na primeira versão, reproduzir os quatro estados possíveis da árvore antiga:

1. Raw;
2. Remesh;
3. Pele aplicada diretamente ao Raw;
4. Remesh + Pele.

Depois da validação pode-se substituir os dois booleanos por um modo exclusivo
`Raw / Preview / Pele Final`, evitando remesh duplo acidental.

### Aceite

- Raw continua com a mesma geometria do baseline;
- os quatro modos avaliam sem erro;
- lado esquerdo continua com faces corretamente orientadas;
- nenhum anchor é extraído da geometria remesheada;
- parâmetros da pele estão visíveis e não escondidos em valores mágicos.

### Checkpoint implementado — 2026-07-25

A primeira versão isolada do acabamento foi salva em
`F:\Biomodelo_Refactor.blend`, mantendo `Biomodelo_v2` e `BM_v2_DEV`
inalterados.

Foram criados:

- `Biomodelo_v2_PRE_ACABAMENTO_20260725T225216`, backup interno da árvore;
- `Biomodelo_v2_DEV_ACABAMENTO`, cópia de integração;
- `BM_Acabamento_v2`, com remesh volumétrico e pele SDF independentes;
- `BM_Pele_SDF_v2` e `BM_Garantir_Folga_v2`, cópias congeladas do legado;
- `BM_v2_ACABAMENTO_TEST`, objeto na coleção
  `DEV_Biomodelo_v2_Acabamento`.

Também foi criada a cópia externa recuperável
`F:\Biomodelo_Refactor_PRE_ACABAMENTO_20260725.blend`.

Validação do modo Raw:

- 1.762 vértices, 3.524 arestas e 1.812 faces;
- mesmas faces e mesmas coordenadas do `BM_v2_DEV`;
- maior deslocamento entre vértices correspondentes igual a zero.

Os quatro modos avaliam sem erro. Remesh, Pele sobre Raw e Remesh + Pele geram
uma única componente manifold fechada, sem bordas abertas. Entretanto, a
inspeção visual mostrou que a calibração legada ainda não deve ser promovida:

- o remesh volumétrico perde muita definição nos dedos;
- o fechamento legado da pele, 28,52, une os dedos e produz uma forma de luva;
- Pele sobre Raw e Remesh + Pele ficam muito semelhantes com esses valores.

Decisão: manter os dois estágios disponíveis e independentes, com Raw como modo
seguro padrão. Remesh e Pele permanecem experimentais até a calibração com os
scans. Não usar a saída remesheada como fonte de anchors.

### Compatibilidade do backend com Blender 5.2

Na versão 5.2 observada, os valores efetivos por objeto do modificador de
Geometry Nodes estão em
`modifier.properties.inputs.<Socket_ID>.value`. Ler apenas defaults da
interface ou usar `modifier.keys()` perde os ajustes do caso. Antes de registrar
os vetores dos scans, o bridge deve adaptar captura, escrita de parâmetros e
presets para essa API, mantendo compatibilidade com versões anteriores.

## Fase 2 — validar geometria, desempenho e estabilidade

### Matriz mínima

Testar:

- membro direito e esquerdo;
- pose neutra;
- flexão/extensão do punho;
- desvio radial/ulnar;
- flexão dos dedos;
- oposição do polegar;
- ao menos três conjuntos de dimensões: pequeno, referência e grande;
- modos Raw, Remesh, Pele e Remesh + Pele.

### Métricas

- bounding box e medidas clínicas derivadas;
- número de ilhas;
- arestas non-manifold e bordas abertas;
- volume e área;
- tempo de avaliação;
- distância de superfície para a árvore legada com os mesmos parâmetros;
- estabilidade ao mover sliders em sequência.

Como a ordem dos `Join` mudou, não exigir igualdade de índices. Para comparar
forma, usar distância de superfície e anchors canônicos.

### Aceite

- ausência de crashes e geometrias vazias;
- comportamento simétrico controlado entre direita e esquerda;
- tolerâncias de forma documentadas;
- configuração de preview suficientemente rápida para edição;
- configuração final identificada separadamente.

## Fase 3 — criar a camada de ajuste por scan

### Objetivo

Preservar os controles que já produziram bons ajustes e fazê-los alimentar o V2
sem depender da interface interna de 125 sockets.

### Implementação

1. Duplicar o wrapper como `BM_AjusteScan_v2`.
2. Inserir um novo nó `Biomodelo_v2`, sem trocar o `node_tree` do nó antigo.
3. Religar entradas por nome e significado.
4. Resolver explicitamente:
   - largura da palma/metacarpo;
   - largura óssea da palma;
   - referências antropométricas;
   - calibrações por dedo;
   - parâmetros de remesh/pele.
5. Manter calibrações internas do V2 com defaults congelados durante a
   validação, para que elas não se confundam com parâmetros disponíveis ao
   ajuste.
6. Criar um novo objeto de ajuste; não alterar
   `Biomodelo_Renata_Posicionado` nesta fase.
7. Armazenar valores por objeto/modificador ou por manifesto de caso. Não usar
   apenas defaults globais do node group, porque eles não preservam vários
   pacientes/casos simultaneamente.

### Regra de API

```text
BM_AjusteScan_v2 = interface usada para reproduzir cada scan
Biomodelo_v2     = implementação geométrica
calibrações      = camada interna/developer congelada
```

### Aceite

- nenhum link depende de `Socket_*` coincidente;
- todas as entradas clínicas têm destino documentado;
- parâmetros sem destino são bloqueados ou registrados, nunca ignorados
  silenciosamente;
- o objeto clínico V2 passa pela matriz da Fase 2.

### Checkpoint implementado — adaptador de ajuste por scan

Foi criado `BM_AjusteScan_v2` como cópia isolada e religada semanticamente de
`Biomodelo_Clinico.002`. O wrapper antigo e
`Biomodelo_Renata_Posicionado` permanecem inalterados.

Estado validado:

- núcleo conectado diretamente ao `Biomodelo_v2` Raw;
- 87 controles públicos preservados nos painéis clínicos;
- 81 ligações ao núcleo V2 reconstruídas;
- `Largura Metacarpo` mapeada para
  `Ref. antro - largura palma (mm)`;
- `Palma - Largura ossos` mapeada para
  `Ref. antro - largura osso (mm)`;
- controles de Remesh e Pele removidos da interface de ajuste;
- objeto-base `BM_AJUSTE_SCAN_BASE` criado na coleção
  `BIOMODELO_V2_SCANS`;
- valores iniciais e transform copiados do caso
  `Biomodelo_Renata_Posicionado`, como preset inicial conhecido;
- independência dos valores do modificador comprovada por teste de duplicação;
- geometria avaliada com 1.762 vértices, 3.524 arestas e 1.812 faces.

Regra operacional:

```text
BM_AjusteScan_v2 = node group único e compartilhado
BM_AJUSTE_SCAN_BASE = objeto-base
BM_SCAN_<case_id> = cópia do objeto-base com valores próprios
```

Não duplicar o node group para cada paciente. Duplicar somente o objeto. Os
painéis organizam controles que podem ser ajustados de forma iterativa e
simultânea; seus números não definem uma sequência rígida.

O antigo `BM_v2_ACABAMENTO_TEST` e sua coleção temporária foram removidos da
cena após a validação.

Após revisão visual, a árvore pública foi refatorada para não reintroduzir a
complexidade do wrapper legado no topo da arquitetura modular:

```text
BM_AjusteScan_v2
  Controles do caso
    -> M01 · Ajuste do scan → Biomodelo V2 Raw
    -> Biomodelo ajustado
```

O grupo público contém somente três nós recolhidos. A implementação detalhada
foi encapsulada em `BM_AS_Nucleo_Clinico_v2`, organizada em quatro frames:
derivações dimensionais, dedos, polegar e curvatura da palma.

A refatoração visual preservou:

- interface e identificadores dos 87 controles;
- todos os valores armazenados no modificador do objeto-base;
- contagem e ordem das faces;
- coordenadas dos 1.762 vértices, com deslocamento máximo igual a zero.

## Fase 4 — replicar scans e validar os parâmetros

### Preparação de cada caso

1. Pseudonimizar o scan com `case_id`.
2. Registrar versão/hash do biomodelo e unidade.
3. Fazer primeiro o alinhamento rígido do scan. Translação e rotação do scan não
   devem ser absorvidas pelos sliders anatômicos.
4. Iniciar sempre do mesmo preset ou de medidas antropométricas registradas.
5. Seguir a mesma ordem de ajuste:
   - medidas globais;
   - pose global;
   - mão/palma;
   - dedos;
   - polegar;
   - correções finas.
6. Salvar vetor inicial, vetor final, tempo e observações.

### Manifesto mínimo

```text
case_id
model_version
scan_reference
side
base_measurements
initial_parameters
final_parameters
fit_metrics
fit_time
operator
notes
```

Não armazenar identificação pessoal nos manifestos de desenvolvimento.

### Métricas de ajuste

- erro em landmarks anatômicos;
- distância mediana e percentil 95 entre superfícies;
- erro regional: antebraço, punho, palma, dedos e polegar;
- parâmetros que atingiram mínimo ou máximo;
- quantidade e magnitude dos sliders alterados;
- tempo necessário para chegar ao ajuste.

### Flexão/extensão do punho

No V2 atual esse controle é aplicado em `BM_Montagem` como rotação rígida do
bloco da mão. Ele deve ser classificado como **pose global opcional**, não como
ajuste primário de forma.

A observação de que elevar/reposicionar as pontas dos metacarpos reproduz melhor
o scan deve ser testada, não descartada:

- registrar quanto `Flex/Ext Punho` foi usado em cada caso;
- registrar os ajustes de avanço, altura/arco e posição das MCPs;
- comparar o erro obtido com rotação global e com ajustes dos metacarpos;
- verificar se o problema é o conceito do slider, o pivô de rotação ou uma
  deformação real da palma que não é rígida.

Até essa análise, manter o slider, mas não obrigar seu uso. Se ele permanecer
próximo de zero ou piorar o ajuste na maioria dos scans, pode ser removido,
renomeado ou reconstruído em torno de `wrist_pivot_anchor`.

### Análise final dos sliders

Para cada parâmetro calcular:

- frequência de alteração;
- delta absoluto e delta normalizado pelo intervalo;
- média, mediana e dispersão;
- casos que atingem limites;
- correlação com outros parâmetros;
- contribuição para reduzir erro regional;
- tempo/custo de ajuste.

Classificação final:

- **essencial**: usado frequentemente e melhora o ajuste;
- **situacional**: útil em anatomias específicas;
- **redundante**: substituído por outro controle;
- **instável**: produz efeitos difíceis de interpretar;
- **interno**: calibração fixa, não deve aparecer ao operador.

### Aceite

- todos os scans possuem manifesto reproduzível;
- nenhum caso exige alteração manual de topologia;
- parâmetros essenciais e situacionais estão identificados;
- sliders redundantes/instáveis têm evidência para revisão;
- limites e erros regionais estão documentados;
- uma interface V2 final pode ser congelada.

### Checkpoint 2026-07-28 — candidato de interface clínica V3

A árvore da sessão de trabalho foi auditada a partir do autosave correspondente
ao mesmo PID do Blender aberto. A comparação corrigiu a classificação dos
objetos:

```text
BM_v2_DEV
└─ Biomodelo_v2                       = núcleo Raw / bancada de engenharia

BM_AJUSTE_SCAN_BASE_v1
└─ BM_AjusteScan_v2
   └─ BM_AS_Nucleo_Clinico_v2
      └─ Biomodelo_v2                 = fachada clínica legada sobre o mesmo núcleo
```

Os dois objetos avaliam a mesma topologia de 1.762 vértices, 3.524 arestas e
1.812 faces. `BM_AJUSTE_SCAN_BASE_v1` é a base correta para evoluir o fluxo
clínico; `BM_v2_DEV` deve continuar fora do uso rotineiro porque expõe os 125
parâmetros técnicos e calibrações.

Foi construído de forma não destrutiva o candidato:

```text
BM_AJUSTE_SCAN_BASE_v3
└─ BM_AjusteScan_v3
   └─ BM_AS_Nucleo_Clinico_v3
      └─ Biomodelo_v2
```

O V3:

- mantém `Biomodelo_v2`, o adaptador V2 e o objeto-base V1 inalterados;
- registra os objetos no collection `BIOMODELOS_CLINICOS`, distinguindo
  `raw_core_dev`, `clinical_adapter_legacy` e `clinical_scan_primary`;
- possui 79 controles públicos em 12 painéis, incluindo cinco subpainéis
  recolhidos;
- encerra `1. Medidas do indivíduo` em `Espessura palmar-dorsal`;
- reúne dimensões dos dedos, com três masters aditivos para falanges
  proximal/média/distal de D2–D5, três comprimentos independentes do polegar e
  doze correções por falange;
- reúne MCP/PIP/DIP e as doze correções de flexão por dedo;
- reúne abertura, curvatura radial/ulnar e arco palmar;
- substitui a translação lateral MCP global por um master `2 + 2`, com sinais
  `D2/D3 = +1` e `D4/D5 = -1`;
- remove o avanço MCP global da interface e preserva quatro ajustes por dedo;
- mantém apenas o radial global como controle público dos metacarpos;
- substitui o Arco Z global ponderado por um master que acrescenta exatamente o
  mesmo ângulo aos quatro raios; quatro deltas individuais refinam o arco;
- concentra todos os controles de posição e ajuste fino do polegar;
- rebaixa flexão/extensão do punho e recuo global dos metacarpos para
  `7. Punho e legado`;
- migra o estado efetivo do BASE V1 como baseline interno e inicializa 55
  controles V3 aditivos em zero.

Validação automatizada do candidato:

- diferença geométrica V1 → V3 em repouso: `0,0 mm`;
- 79/79 controles públicos ligados exatamente uma vez;
- 79/79 controles produziram resposta geométrica finita;
- nenhum controle alterou a topologia;
- restauração após a varredura: `0,0 mm`;
- `Biomodelo_v2` permaneceu com 34 nós, 230 links e 125 inputs;
- nenhum link inválido na fachada ou no adaptador;
- valores de modificador independentes entre BASE e cópia por scan.

Foi preparado o par de usabilidade `BM_SCAN_RENATA_v3` +
`SCAN_RENATA_REFERENCIA_v3` no collection `BM_TESTE_USABILIDADE_V3`. O
alinhamento inicial é somente rígido por centro da bounding box e serve para
testar a ordem e a legibilidade dos sliders; não representa um ajuste clínico
concluído.

Artefatos reproduzíveis:

- contrato: `presets/biomodel_clinical_contract_v3.json`;
- construção: `tools/build_biomodel_clinical_v3.py`;
- bancada de scan: `tools/setup_biomodel_clinical_v3_scan_test.py`;
- validação integral: `tools/validate_biomodel_clinical_v3.py`.

### Revisão clínica V3.1 — medidas reais e neutro anatômico

Em 2026-07-28, a revisão de uso no arquivo vivo gerou o ramo não destrutivo:

```text
BM_AJUSTE_SCAN_BASE_v3_1
└─ BM_AjusteScan_v3_1
   └─ BM_AS_Nucleo_Clinico_v3_1
      └─ Biomodelo_v3_1
         └─ 4 × BM_Dedo_Longo_v3_1
            └─ BM_Dedo_AberturaZ_v1
```

A V3.1 corrige quatro pontos clínicos:

- o grupo 2 recebe medidas absolutas das falanges proximal, média e distal do
  dedo médio; os comprimentos de D2–D5 são derivados por fatores calibrados no
  `BM_v2_DEV`;
- o grupo 2a permanece opcional e explicitamente aditivo: cada valor é uma
  diferença em milímetros, com neutro em zero, sem alterar a medida clínica do
  grupo 2;
- o arco palmar deixa de herdar os offsets antigos de aproximadamente
  `−31°` a `−35°`; `Flexão/extensão do arco da mão = 0°` agora significa
  rotação metacarpal neutra;
- a abertura MCP `2 + 2` passa a ser uma rotação em Z, conjugada como
  `T(P) · Rz · T(−P)` ao redor da base fixa de cada metacarpo, em vez de
  translação lateral.

O desvio radial/ulnar do punho foi movido para
`4. Punho, abertura e arco da palma`. A flexão/extensão legada do punho
permanece no grupo técnico, mas começa em `0°`.

As referências iniciais são `46,10 mm`, `28,40 mm` e `18,20 mm`. Os fatores
antropométricos por dedo e segmento estão registrados em
`presets/biomodel_clinical_patch_v3_1.json`.

Validação no arquivo vivo `E:\Biomodelo_Refactor_v2.blend`:

- topologia preservada: 1762 vértices, 3524 arestas e 1812 polígonos;
- os três controles de referência responderam individualmente;
- abertura MCP angular, arco palmar e desvio do punho responderam;
- restauração exata após os testes: `0,0 mm`;
- `Biomodelo_v2` e `BM_Dedo_Longo` permaneceram inalterados;
- o V3 anterior foi mantido oculto como rollback.

Artefatos da revisão:

- contrato incremental: `presets/biomodel_clinical_patch_v3_1.json`;
- aplicação versionada: `tools/patch_biomodel_clinical_v31.py`;
- lançador do arquivo vivo: `runtime/apply_live_biomodel_clinical_v31.py`.

### Correção V3.2 — zero de pose confiável

A revisão visual do V3.1 revelou que o adaptador ainda somava, de modo oculto,
correções migradas do objeto V1. Assim, valores públicos em zero produziam
flexões diferentes nos quatro dedos e no polegar. Exemplos encontrados:
`Mindinho MCP = −23,86°`, `Mindinho PIP = +11,31°` e correções palmares do
polegar de até `−27,95`.

O V3.2 elimina esses baselines de pose do V1 e usa `BM_v2_DEV` como referência
canônica espalmada:

```text
BM_AJUSTE_SCAN_BASE_v3_2
└─ BM_AjusteScan_v3_2
   └─ BM_AS_Nucleo_Clinico_v3_2
      └─ Biomodelo_v3_1
```

Os controles públicos continuam sendo ajustes clínicos, mas agora:

- os 51 controles de pose em zero reproduzem a pose-base espalmada;
- MCP, PIP e DIP dos quatro dedos ficam retos e coplanares;
- o polegar retorna à implantação e ao alinhamento calibrados no
  `BM_v2_DEV`;
- os valores dimensionais já informados no V3.1 são preservados;
- `Flexão/extensão do arco da mão` é o primeiro controle do grupo 4,
  seguido pelo desvio radial/ulnar;
- as antigas correções V1 deixam de participar das fórmulas de pose.

A distância excessiva entre a cabeça MCP e a falange proximal tinha uma segunda
causa: a folga permanecia fixa em `8,3082 + 2,5 mm`, mesmo quando a espessura
clínica do dedo reduzia o raio da cabeça MCP. O V3.2 usa:

```text
folga MCP = espessura atual do dedo × 0,492 + 2,5 mm
```

Assim, a conexão visual acompanha a escala real do dedo.

Validação do V3.2:

- 1762 vértices, 3524 arestas e 1812 polígonos;
- 51/51 controles de pose em zero;
- respostas confirmadas para flexão MCP, flexão do polegar, arco palmar e
  abertura angular 2+2;
- restauração exata após os testes: `0,0 mm`;
- conferência superior, lateral e isométrica contra `BM_v2_DEV`.

Artefatos:

- contrato incremental: `presets/biomodel_clinical_patch_v3_2.json`;
- aplicação: `tools/patch_biomodel_clinical_v32.py`;
- lançador vivo: `runtime/apply_live_biomodel_clinical_v32.py`.

### Revisão V3.3 — início do ajuste pelo antebraço e punho

O V3.3 foi criado a partir da cópia de ajuste ativa
`BM_AJUSTE_SCAN_BASE_v3_2.001`, preservando integralmente seus 79 controles e
transform global:

```text
BM_AJUSTE_SCAN_BASE_v3_3
└─ BM_AjusteScan_v3_3
   └─ BM_AS_Nucleo_Clinico_v3_3
      └─ Biomodelo_v3_3
         └─ BM_Antebraco_Punho_v3_3
```

O início do grupo 1 passou a seguir a sequência clínica:

1. comprimento do antebraço;
2. perímetro proximal do antebraço;
3. perímetro do punho;
4. flexão/extensão do punho;
5. pronação/supinação da base proximal;
6. razão largura/espessura da base proximal.

A flexão/extensão do punho foi removida do grupo técnico, perdeu a marca
“legado” e recebeu intervalo de `−180°` a `+180°`. A árvore
`BM_Montagem` já trabalhava sem clamp interno; portanto a limitação anterior
era apenas do slider público.

A pronação/supinação é uma torção progressiva em torno do eixo longitudinal:
o punho recebe 0% do ângulo e permanece fixo, enquanto a seção proximal recebe
100%. O teste de `35°` moveu somente os 64 vértices do cone do antebraço e
manteve os outros 1698 vértices imóveis.

A seção proximal agora é uma elipse parametrizada pela razão
`largura/espessura`, com intervalo `0,6–2,2`. Os semieixos são calculados pela
aproximação de perímetro de Ramanujan, de modo que alterar o achatamento não
invalide o perímetro clínico informado. O valor inicial `1,25` reproduz uma
base mais larga que espessa; a medição avaliada foi `1,25000018`.

Validação:

- topologia preservada: 1762 vértices, 3524 arestas e 1812 polígonos;
- flexão do punho testada em `150°` sem clamp;
- respostas confirmadas para pronação/supinação e razão proximal;
- restauração exata depois dos testes: `0,0 mm`;
- 79/79 valores da cópia de ajuste migrados sem diferença.

Artefatos:

- contrato incremental: `presets/biomodel_clinical_patch_v3_3.json`;
- aplicação: `tools/patch_biomodel_clinical_v33.py`;
- lançador vivo: `runtime/apply_live_biomodel_clinical_v33.py`.

### Revisão V3.4 — largura e espessura proximais independentes

O controle único de razão da base proximal foi substituído por duas medidas
clínicas absolutas, ambas em milímetros:

1. `Base proximal — largura`;
2. `Base proximal — espessura`.

Os dois controles ficam logo depois da pronação/supinação no grupo 1. A V3.4
foi inicializada com as dimensões derivadas da forma ajustada na V3.3
(`98,484 mm × 149,218 mm`), preservando a geometria corrente com diferença
máxima de `0,000024 mm`. Assim, a migração não provoca salto visual e o
profissional pode ajustar separadamente as vistas superior e lateral.

O perímetro proximal continua disponível como medida clínica de referência.
Como largura e espessura agora são independentes, elas têm precedência
geométrica sobre a razão anterior; uma etapa futura poderá avisar quando o
perímetro calculado da elipse divergir do perímetro informado.

Validação:

- topologia preservada: 1762 vértices, 3524 arestas e 1812 polígonos;
- resposta independente confirmada para largura e espessura;
- restauração exata depois dos testes: `0,0 mm`;
- pose, transform e demais valores clínicos da V3.3 preservados;
- V3.3 mantida oculta na cena como rollback.

Artefatos:

- contrato incremental: `presets/biomodel_clinical_patch_v3_4.json`;
- aplicação: `tools/patch_biomodel_clinical_v34.py`;
- lançador vivo: `runtime/apply_live_biomodel_clinical_v34.py`.

### Revisão V3.5 — seção elíptica do punho

A esfera do punho deixou de depender apenas de um raio circular e recebeu duas
medidas clínicas absolutas:

1. `Punho — largura`;
2. `Punho — espessura`.

Elas ficam imediatamente depois de `Perímetro do punho`. A seção da esfera do
carpo e a extremidade distal do cone do antebraço recebem as mesmas dimensões.
Ao longo do antebraço, largura e espessura são interpoladas linearmente entre
o punho e a base proximal; assim não existe uma troca abrupta de proporção.

A V3.5 foi inicializada com a seção que já existia na V3.4
(`48,558 mm × 38,847 mm`). A comparação avaliada entre as versões produziu
diferença máxima de `0,0 mm`, portanto não houve salto na geometria ajustada.
O perímetro do punho permanece como medida clínica de referência.

Validação:

- topologia preservada: 1762 vértices, 3524 arestas e 1812 polígonos;
- largura e espessura responderam independentemente;
- restauração exata depois dos testes: `0,0 mm`;
- V3.4 preservada oculta como rollback.

Artefatos:

- contrato incremental: `presets/biomodel_clinical_patch_v3_5.json`;
- aplicação: `tools/patch_biomodel_clinical_v35.py`;
- lançador vivo: `runtime/apply_live_biomodel_clinical_v35.py`.

### Revisão V3.6 — comprimento do punho e base dos metacarpos

O volume do punho recebeu a terceira dimensão clínica
`Punho — comprimento axial`, independente da largura e da espessura. Esse
valor controla simultaneamente:

- o tamanho da esfera do carpo ao longo do eixo do antebraço;
- o limite distal do carpo usado para ancorar os metacarpos;
- a parcela de `Punho até MCP` disponível para o comprimento metacarpal.

Assim, encurtar o volume do punho aproxima naturalmente o início dos
metacarpos sem deslocar arbitrariamente o MCP distal.

O antigo `Metacarpos — recuo global (avançado)` foi promovido e renomeado para
`Base dos metacarpos — avanço/recuo`. Ele continua sendo um ajuste relativo em
milímetros e agora aparece no grupo 4. O novo
`Base dos metacarpos — altura` move juntos os quatro raios longos no eixo
palmar-dorsal, mantendo metacarpo, cabeça MCP e falanges coerentes.

`Flexão/extensão do punho` permanece como controle de pose: gira o bloco da
mão no pivô do punho e não é usado para compensar comprimento ou altura.

A V3.6 foi inicializada com o comprimento axial já existente
(`67,239 mm`) e altura/recuo em zero. A diferença máxima para a V3.5 foi
`0,000023 mm`.

Validação:

- topologia preservada: 1762 vértices, 3524 arestas e 1812 polígonos;
- respostas independentes confirmadas para comprimento axial, avanço/recuo,
  altura e flexão/extensão;
- 84/84 controles anteriores migrados sem diferença;
- restauração exata depois dos testes: `0,0 mm`;
- V3.5 preservada oculta como rollback.

Artefatos:

- contrato incremental: `presets/biomodel_clinical_patch_v3_6.json`;
- aplicação: `tools/patch_biomodel_clinical_v36.py`;
- lançador vivo: `runtime/apply_live_biomodel_clinical_v36.py`.

## Relação com o resumo expandido do CBEB

O trabalho pode ser apresentado como um processo metodológico mais amplo, e não
apenas como comparação de medidas:

1. criação de um biomodelo paramétrico anatômico em Geometry Nodes;
2. modularização em antebraço, palma, dedos, polegar e montagem;
3. desenvolvimento assistido por IA, com decisões e validação sob supervisão
   humana;
4. construção de controles globais e correções locais;
5. ajuste padronizado em múltiplos scans;
6. análise quantitativa da geometria e da utilidade dos parâmetros.

A IA deve ser descrita como apoio à engenharia — inspeção, geração/refatoração
de scripts e nós, documentação e testes — e não como sistema autônomo de decisão
clínica.

## Fase 5 — anchors canônicos

### Objetivo

Preparar a integração com a órtese sem depender da pele ou da numeração de
vértices.

Criar `BM_AnchorGraph_v0` ou sockets de matriz nomeados para, no mínimo:

- `forearm_origin_anchor`;
- `wrist_pivot_anchor`;
- `palm_center_anchor`;
- `thumb_root_anchor`;
- `hand_radial_group_anchor`;
- `hand_ulnar_group_anchor`.

O ramo de anchors deve nascer das mesmas derivações/matrizes do biomodelo,
antes de `Join`, remesh e pele.

### Aceite

- mesmos anchors em Raw, Remesh e Pele;
- IDs/matrizes independentes da ordem dos `Join`;
- teste do membro esquerdo definido;
- V4 da órtese pode consumir transforms sem acessar a malha do biomodelo.

## Fase 6 — ganhos seguintes para a órtese

Somente depois do V2 clínico validado:

1. criar `ORT_Clearance_Field_v0` próprio, inspirado na comparação entre
   `Garantir_Folga` e o asset externo `SDF Mesh`;
2. manter o campo inicialmente diagnóstico;
3. expor `ort_uv` e `patch_id` dentro do patch de Coons;
4. criar frame U/V para orientação de perfurações, slots e reforços;
5. conectar curvas V4 aos anchors canônicos.

Esses itens trazem ganho alto, mas não devem atrasar a conclusão da pele e do
adaptador clínico V2.

## Itens que não devem entrar no curto prazo

- reproduzir a antiga ordem global de vértices;
- importar diretamente assets externos sem licença explícita;
- física, wobble ou simulação por frame;
- reescrever o patch de Coons;
- apagar grupos `ARCHIVE`, `PRE_*`, `ORACLE` ou backups;
- ativar correção automática de folga sem diagnóstico;
- substituir o objeto clínico vivo antes da matriz de validação.

## Definition of Done do Biomodelo V2 de curto prazo

O V2 pode ser considerado concluído para a próxima etapa quando:

- produz Raw, Remesh e Pele por módulo próprio;
- preserva Raw como default;
- possui objeto de teste e baseline recuperável;
- passou pela matriz de lado, pose e tamanho;
- possui `BM_AjusteScan_v2` religado semanticamente;
- preserva um vetor de parâmetros por scan;
- todos os scans foram replicados pelo mesmo protocolo;
- parâmetros finais foram classificados e congelados;
- não usa índice de vértice como identidade;
- mantém anchors fora da pele;
- não exige alterações na árvore legada para funcionar.
