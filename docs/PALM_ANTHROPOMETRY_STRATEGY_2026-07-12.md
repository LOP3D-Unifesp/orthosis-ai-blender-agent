# Estratégia antropométrica local — punho, palma e curvas

Data: 2026-07-12

## Decisão atual

- A ancoragem geométrica das curvas usa a **Espessura da Palma efetiva** (`Socket_31`).
- O estado vivo de **23,06999 mm** é a referência neutra: nenhuma curva muda nessa medida.
- A face palmar inferior do biomodelo varia por:

  `DeltaZ = -0,4713219472 * (EspessuraAtual - 23,06999)`

- O perímetro do punho ainda não substitui a espessura. Ele poderá fornecer uma estimativa inicial,
  enquanto medição, scan ou ajuste clínico continuam podendo corrigir a forma local.

## Implementação corrigida em 2026-07-13

Os efeitos geométricos ficaram deliberadamente separados:

- **Perímetro do punho:** continua governando as larguras existentes e agora desloca a curva ulnar
  apenas para dentro/fora, na direção lateral local. Não avança a curva longitudinalmente e não
  substitui a espessura da palma.
- **Punho até MCP médio:** desloca longitudinalmente, em bloco e na proporção 1:1, tanto a curva do
  polegar quanto a curva ulnar. Os oito perfis ancorados entre elas acompanham o mesmo avanço sem
  deformação.
- **Espessura da palma:** permanece sendo o controle vertical independente já descrito acima.

Essa separação evita que a circunferência seja interpretada como comprimento e preserva o ajuste de
comprimento da mão que já existia antes da ancoragem dos perfis na borda ulnar.

## Por que não usar somente o perímetro do punho

Circunferência, largura e espessura não são a mesma informação geométrica. Duas seções podem ter o
mesmo perímetro e relações largura/espessura diferentes. Isso é ainda mais relevante em órteses,
porque edema, deformidade, musculatura, tecido adiposo e posição da mão alteram a seção local.

As referências antropométricas consultadas seguem essa separação:

- A [ISO 7250-1:2017](https://www.iso.org/standard/65246.html) padroniza landmarks e medidas para
  comparação populacional e prevê medidas adicionais específicas da aplicação.
- O [banco de mãos da AIST](https://www.airc.aist.go.jp/dhrt/hand/index.html) mediu 530 adultos
  saudáveis e publica 72 dimensões separadas de comprimento, largura, espessura e circunferência.
  Na espessura no terceiro metacarpo, as médias foram 32,1 mm para homens e 27,8 mm para mulheres;
  no perímetro da mão, 202,5 e 179,1 mm, respectivamente.
- O relatório [Hand Anthropometry of U.S. Army Personnel](https://studylib.net/doc/28364003/ada244533)
  usa dezenas de dimensões, matrizes de correlação, regressões e componentes principais; não reduz
  a mão a uma única escala corporal.
- O estudo de sizing de luvas [Ahn et al., 2009](https://doi.org/10.1016/j.apergo.2008.07.003)
  selecionou comprimento e circunferência da mão como dimensões-chave do sistema de tamanhos.
- Em amostra brasileira, [Fernandes et al., 2011](https://doi.org/10.1590/S1809-29502011000200009)
  mediram separadamente largura da palma, espessura da palma, largura da mão e circunferências.

Essas bases são referências de ergonomia e população saudável, não uma validação clínica para mãos
com patologia. No fluxo da órtese, o scan e a avaliação do profissional devem prevalecer.

## Arquitetura recomendada

### Modo simples

Poucas medidas fáceis com fita:

1. Perímetro do punho — governa carpo e transição do antebraço.
2. Perímetro da mão no nível das cabeças metacarpais — governa a seção da palma.
3. Punho até MCP médio — governa o comprimento da palma.

No estado corrigido em 2026-07-13, essa terceira medida preserva a parametrização longitudinal
preexistente da mão e desloca rigidamente o polegar, as duas bordas longitudinais da órtese e seus
oito perfis transversais. Ela não escala a curva do polegar e nenhum extremo dos perfis fica fixo
para esse movimento. O ajuste `Polegar - CMC recuo` permanece como correção fina independente.

O sistema estima largura e espessura e mostra o resultado imediatamente.

### Modo clínico / avançado

Expõe correções independentes:

- largura da palma;
- espessura da palma;
- largura dos ossos;
- folga palmar da órtese;
- assimetrias e arcos locais.

Assim, o conhecimento tácito não disputa com o modelo estatístico: ele corrige o prior quando o caso
real foge da média.

## Próxima evolução sugerida

Adicionar `Perímetro da mão (MCP)` como medida mestra local. Com largura conhecida, uma seção elíptica
pode fornecer uma espessura inicial; depois, `Ajuste de espessura da palma` corrige o valor. Na ausência
do perímetro da mão, o perímetro do punho fornece apenas um fallback proporcional calibrado no caso vivo.

Essa hierarquia deve ser implementada como uma camada de **estimativa/preset**, separada da camada de
geometria. Dessa forma, trocar a regressão no futuro não exige reconstruir as âncoras das curvas.
