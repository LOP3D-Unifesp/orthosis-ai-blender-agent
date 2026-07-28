# Orthosis Bridge

Núcleo de integração entre Python e Blender para inspecionar, construir e
validar incrementalmente árvores Geometry Nodes do projeto de biomodelo e
órtese.

> **Protótipo de pesquisa:** este projeto não é software médico validado. Não
> deve ser usado diretamente para decisões clínicas, tratamento ou fabricação
> de órteses sem validação profissional independente.

## Escopo desta branch

A branch `codex/slim-relevance` mantém o necessário para o trabalho atual:

- addon `Orthosis Bridge`, executado dentro do Blender;
- bridge TCP local em `localhost:65432`;
- cliente Python `blender_connection.py`;
- ferramentas de leitura, edição, render e avaliação de Geometry Nodes;
- painel antropométrico ainda em desenvolvimento;
- testes automatizados e smoke test com o Blender;
- mapas de parâmetros usados durante o refactor;
- documentação técnica segura do biomodelo.

Não fazem parte do núcleo desta branch:

- o antigo agente de chat embutido no Blender;
- integração com Anthropic ou chave de API;
- o adaptador MCP antigo;
- o simulador web React/Three.js;
- arquivos `.blend`, que permanecem como arquivos locais de trabalho;
- relatórios, imagens, inventários e demais materiais de pesquisa ainda não
  revisados para publicação.

Os materiais de pesquisa locais são ignorados pelo Git e devem ser
transportados por armazenamento offline seguro. Isso evita que um `git add .`
publique acidentalmente documentos, imagens ou medidas ainda em elaboração.

## Como funciona

```text
script Python externo
        │
        ▼
blender_connection.py
        │  TCP + JSON, localhost:65432
        ▼
blender_addon/server.py
        │
        ▼
blender_addon/tools/handlers.py
        │  execução na thread principal do Blender
        ▼
bpy / Geometry Nodes
```

O addon inicia o bridge quando é habilitado. O painel **Orthosis**, na lateral
da Viewport 3D, mostra o estado da porta e permite parar ou reiniciar o
servidor.

### Duas instâncias do Blender

A porta padrão continua sendo `65432`. Para abrir uma segunda instância
isolada — por exemplo, uma bancada de análise enquanto outro agente trabalha
no biomodelo — use:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\tools\launch_blender_analysis.ps1 -Port 65433
```

Também é possível abrir diretamente um arquivo:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\tools\launch_blender_analysis.ps1 -Port 65433 `
  -BlendFile "C:\caminho\arquivo.blend"
```

O lançador define `ORTHOSIS_BRIDGE_PORT` somente para o novo processo. No
cliente Python, selecione a mesma porta explicitamente:

```python
from blender_connection import BlenderConnection

analysis_blender = BlenderConnection(port=65433)
print(analysis_blender.ping())
```

Cada instância deve usar uma porta diferente. O bridge continua restrito a
`localhost`.

No Windows, também é possível usar
`tools\abrir_blender_analise.cmd`: dê dois cliques para abrir uma cena vazia ou
arraste um arquivo `.blend` sobre o `.cmd` para abri-lo diretamente na porta
`65433`.

O arquivo importante é `blender_addon/server.py`. O antigo `server.py` que
ficava na raiz era um adaptador MCP de outra arquitetura e foi removido desta
branch.

## Estado atual

| Componente | Estado |
|---|---|
| Bridge TCP e cliente Python | Ativos |
| Leitura e edição incremental de Geometry Nodes | Ativas |
| Avaliação de geometria e render de conferência | Ativas |
| `Biomodelo_v2` | Em construção |
| Painel antropométrico | WIP; ainda não reconciliado com a interface nova |
| Source completo reproduzível do biomodelo | Parcial |
| Arquivos `.blend` | Não versionados intencionalmente |

A árvore antiga `Biomodelo` é usada localmente como referência de comparação.
A nova `Biomodelo_v2` está sendo reconstruída de forma modular. No checkpoint
de 25/07/2026 ela tinha 69 entradas e ainda faltavam módulos como polegar,
montagem final e pele; essa contagem não é um contrato definitivo.

### Atenção ao painel antropométrico

O derivador atual ainda usa um mapa antigo e reduzido de sockets. Portanto,
**não use “Aplicar Antropometria” na árvore de referência nem na
`Biomodelo_v2` até a reconciliação ser concluída**.

Os cálculos puros foram mantidos porque fazem parte do trabalho em andamento.
Os testes desses cálculos podem passar sem que isso signifique que o botão já
esteja compatível com a árvore nova.

## O que são os “contratos” de parâmetros?

Neste projeto, “contrato” não é um documento jurídico. É um mapa entre um
controle visível e o identificador interno que o Blender atribui ao socket:

```text
Socket_21  → comprimento do antebraço
Socket_24  → desvio radial/ulnar do punho
Socket_145 → membro esquerdo
```

As contagens diferentes não representam cinco sistemas que precisam funcionar
ao mesmo tempo. Elas registram fases e finalidades diferentes:

| Artefato | Finalidade |
|---|---|
| `presets/biomodel_sockets_live.json` | captura anterior, com 89 sockets |
| `presets/scan_referencia.json` | valores de um preset; não define toda a interface |
| `blender_addon/biomodel/source_template.py` | consolidação parcial para geração por código |

Durante o refactor:

1. a árvore viva aberta no Blender é a referência operacional;
2. capturas locais mais recentes devem ser revisadas antes de serem
   versionadas;
3. nenhum mapa antigo deve dirigir automaticamente o painel antropométrico;
4. o manifesto canônico será gerado quando a interface da `Biomodelo_v2`
   estiver estável.

## Requisitos

- Blender 4.0 ou mais recente;
- Python 3.10 ou mais recente para o cliente externo;
- `pytest` somente para os testes automatizados.

O addon e o cliente não precisam de Anthropic, MCP ou outros pacotes externos.
O módulo `bpy` já faz parte do Blender e não deve ser instalado com `pip`.

## Instalação no Blender

Clone o repositório:

```bash
git clone https://github.com/LOP3D-Unifesp/orthosis-ai-blender-agent.git
cd orthosis-ai-blender-agent
```

No PowerShell, gere o pacote local do addon:

```powershell
Compress-Archive -Path blender_addon -DestinationPath blender_addon.zip -Force
```

No Blender:

1. abra **Edit → Preferences → Add-ons**;
2. escolha **Install from Disk**;
3. selecione `blender_addon.zip`;
4. habilite **Orthosis Bridge**;
5. abra a lateral da Viewport com `N`;
6. confira em **Orthosis → Bridge** se aparece `localhost:65432`.

O ZIP é um artefato local e está ignorado pelo Git.

## Uso básico

Com o Blender aberto e o addon ativo:

```python
from blender_connection import BlenderConnection

blender = BlenderConnection()

print(blender.ping())
print(blender.capture_scene())

nodes = blender.list_tree_nodes("Biomodelo_v2")
print(nodes)
```

Comece pelas operações de leitura:

- `capture_scene`;
- `capture_node_trees`;
- `list_tree_nodes`;
- `find_tree_nodes`;
- `get_node_context`;
- `trace_subgraph`.

O cliente também oferece mutações tipadas, avaliação geométrica, render de
conferência e `execute_code`. Use operações de escrita somente com o arquivo
salvo e o alvo explicitamente conferido.

## Testes

Instale a dependência de desenvolvimento:

```bash
python -m pip install -r requirements.txt
```

Execute a suíte que não depende do Blender:

```bash
python -m pytest -q
```

Execute os testes novamente após qualquer mudança no mapa antropométrico.

Esses testes cobrem os cálculos antropométricos puros. Eles não comprovam que
o painel antropométrico já funciona com a `Biomodelo_v2`.

Para testar o canal completo com o Blender aberto:

```bash
python smoke_bridge.py --tree Biomodelo_v2
```

O smoke test faz uma alteração pequena e a restaura na mesma execução. Rode-o
somente com o arquivo salvo ou em uma cópia de teste.

## Segurança

O bridge escuta apenas em `localhost`, mas não possui autenticação. O comando
`execute_code` pode executar Python arbitrário dentro do Blender.

- não exponha a porta em uma interface de rede;
- não execute clientes ou scripts não confiáveis;
- confira o alvo antes de qualquer mutação;
- mantenha snapshots locais dos marcos importantes;
- pare o bridge quando ele não estiver em uso.

## Estrutura principal

```text
blender_addon/          addon instalado no Blender
blender_connection.py   cliente TCP externo
smoke_bridge.py         teste ponta a ponta com Blender aberto
tests/                  testes Python sem bpy
presets/                mapas e capturas versionadas de sockets
docs/                   decisões e histórico técnico do biomodelo
knowledge/              referências técnicas usadas durante o desenvolvimento
biomodel_source/         fonte parcial reproduzível do Geometry Nodes
```

Os documentos datados em `docs/` registram decisões de fases anteriores e
podem mencionar componentes que já foram removidos desta branch.

## Arquivos Blender

Arquivos `.blend`, `.blend1`, materiais de pesquisa privados e snapshots de
`runtime/` são deliberadamente ignorados. Um commit desta branch não é backup
do arquivo Blender aberto nem dos documentos científicos em elaboração.

Quando o `Biomodelo_v2` estiver pronto para distribuição, deve ser escolhido
um único `.blend` canônico e uma estratégia própria de publicação, como Git
LFS, GitHub Release ou armazenamento externo com checksum.

## Licença

A licença do repositório ainda não foi definida. O uso atual está restrito ao
contexto de pesquisa do projeto.
