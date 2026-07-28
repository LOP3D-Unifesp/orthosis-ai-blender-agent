# Handoff — Biomodelo clínico / checkpoint CBEB

Data: 2026-07-28  
Prazo imediato: resumo expandido do CBEB em 2026-07-30

## Estado congelado

- Arquivo principal: `E:\Biomodelo_Refactor_v2.blend`
- Checkpoint independente:
  `E:\Biomodelo_Refactor_v2_CHECKPOINT_CBEB_V3_5_20260728_175320.blend`
- Baseline aprovado e ativo: `BM_AJUSTE_SCAN_BASE_v3_5`
- Painel do baseline: `BM_AjusteScan_v3_5`
- Experimento preservado, mas oculto: `BM_AJUSTE_SCAN_BASE_v3_6`
- Topologia validada: 1762 vértices, 3524 arestas e 1812 polígonos
- Controles preservados na V3.5: 84

Valores clínicos conferidos no checkpoint:

- perímetro do punho: `199,280 mm`;
- largura do punho: `50,910 mm`;
- espessura do punho: `36,467 mm`.

## Decisões aceitas na V3.5

O início do grupo 1 está organizado assim:

1. comprimento do antebraço;
2. perímetro proximal do antebraço;
3. perímetro do punho;
4. largura do punho;
5. espessura do punho;
6. flexão/extensão do punho;
7. pronação/supinação da base proximal;
8. largura da base proximal;
9. espessura da base proximal.

Também foram aceitos:

- largura e espessura proximais independentes em milímetros;
- largura e espessura do punho independentes em milímetros;
- transição contínua entre a seção do punho e a seção proximal;
- pronação/supinação progressiva com o punho fixo;
- flexão/extensão do punho disponível como controle de pose;
- preservação dos valores ajustados sobre o scan.

## V3.6: experimento não aprovado

A V3.6 não deve ser usada como base do painel nem estendida com uma V3.7.

Problemas confirmados:

- `Base dos metacarpos — avanço/recuo` reutilizou o recuo antigo da âncora Y;
- como a base também é pivô do arco, esse recuo alterou a altura aparente dos
  MCPs;
- `Base dos metacarpos — altura` foi aplicado depois da montagem do raio e
  moveu metacarpo, MCP e falanges juntos;
- portanto os dois controles não isolaram a altura do ponto proximal desejado.

O conceito de comprimento axial do punho pode ser reavaliado no futuro, mas
não está aprovado para integração enquanto não for testado isoladamente na
árvore nativa.

## Direção do próximo refactor

Não criar outra cadeia
`facade clínica → adaptador → cópia do núcleo → cópias dos subgrupos`.
A V3.5 permanece como protótipo e referência visual, não como arquitetura a
ser expandida.

Na próxima sessão:

1. usar o arquivo Blender aberto como fonte da verdade;
2. auditar primeiro, sem mutações, `BM_v2_DEV`, `Biomodelo_v2` e seus grupos;
3. escolher uma única cópia direta da árvore nativa para o painel clínico;
4. organizar a própria interface dessa árvore, sem nova fachada/adaptador;
5. transferir um recurso aprovado da V3.5 por vez;
6. comparar cada alteração com o baseline V3.5;
7. validar quais vértices/regiões cada controle realmente move;
8. somente promover a nova árvore depois de testar nos scans.

Definição futura para `Altura da base dos metacarpos`:

- alterar somente os pontos proximais dos quatro metacarpos;
- manter os centros MCP fixos;
- não reutilizar recuo longitudinal;
- não traduzir o raio inteiro depois da montagem;
- testar separadamente de arco palmar e flexão/extensão do punho.

## Escopo recomendado para o CBEB

Até a entrega do resumo, evitar novas mudanças estruturais no biomodelo.
Apresentar a V3.5 como protótipo paramétrico clínico em evolução, destacando:

- modularização em Geometry Nodes;
- interface clínica organizada;
- ajuste do mesmo modelo a scans;
- controles dimensionais e de pose;
- validação de preservação topológica e de valores;
- desenvolvimento assistido por IA sob supervisão humana.

Não apresentar o painel como ferramenta clínica final ou já validada.

## Prompt sugerido para a nova sessão

> Use o arquivo Blender aberto como fonte da verdade. O baseline aprovado é
> `BM_AJUSTE_SCAN_BASE_v3_5`, preservado também no checkpoint
> `E:\Biomodelo_Refactor_v2_CHECKPOINT_CBEB_V3_5_20260728_175320.blend`.
> A V3.6 é um experimento rejeitado e não deve ser continuada. Primeiro faça
> uma auditoria somente de leitura de `BM_v2_DEV`, `Biomodelo_v2` e seus
> subgrupos. Proponha como incorporar diretamente na árvore nativa os
> controles aceitos da V3.5, organizando sua própria interface e sem criar
> fachada ou adaptador adicional. Não altere a geometria até apresentar o
> mapa de dependências, o plano de migração dos 84 valores e a estratégia de
> testes de regressão.
