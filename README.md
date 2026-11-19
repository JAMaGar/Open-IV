# Open-IV 1.1.2

Programa de controle do **Keithley 2400 SourceMeter** (RS-232) para:

- **capacitores MIS com ou sem efeito memória**: I-V e laços, leitura e multinível, pulsos, sinapse, ciclos, retenção, I(t)/V fixo/V_oc;
- **células solares e diodos**: curva J-V (claro/escuro, histerese), diodo no escuro (n, J0, n local) e estabilidade/MPPT.

Substitui o **MemristorProbe 1.3**, que continua na pasta original, sem alterações.

---

## 1. O problema da largura de pulso e a correção

**No MemristorProbe 1.3**, o pulso era montado pelo PC:

```
:SOUR:VOLT v  ->  :OUTP ON  ->  time.sleep(w)  ->  :OUTP OFF
```

A largura real era de ~50–60 ms para **qualquer** valor nominal, porque somava:

- o tempo de transmissão dos comandos a 9600 baud (~1 ms por caractere);
- a pausa fixa de 15 ms depois de cada comando;
- a granularidade do `time.sleep()` no Windows (~15,6 ms);
- o chaveamento do relé de saída a cada pulso e a cada leitura (o capacitor ficava flutuando entre etapas).

Além disso, o `t_write` gravado incluía o tempo de transmissão do comando de nível, e não o tempo em que a tensão esteve de fato aplicada.

**No Open-IV, toda forma de onda é executada pelo próprio 2400** como uma varredura de lista (*custom sweep*, até 2500 pontos). O PC só envia a lista e recebe os dados no fim. Cada ponto dura:

```
T_ponto = atraso de fonte (:SOUR:DEL) + medida (NPLC/60 s; x3 com autozero; x2 se medir V) + sobrecarga (~1 ms)
```

**O que o primeiro teste no 2400 real mostrou (12/11/2026, SN 0978216, firmware C26):**

- O carimbo de tempo (TIME) do 2400 tem resolução de **1/1024 s = 0,977 ms**: todos os valores medidos eram múltiplos desse tique. Um pulso isolado só pode ser cronometrado a ±1 ms.
- Um passo **sem atraso de fonte** dura ~1 ms (T0 ≈ 0,98 ms com NPLC 0,01).
- Com atrasos pequenos (≈ 1–3 ms), o passo ficou em ~10,7 ms, sem acompanhar o atraso. Com atrasos de 47 e 97 ms, ele acompanhou (48,8 e 99,6 ms).
- Por isso a versão 1.0 errava as larguras curtas: a correção pulso a pulso amplificava a quantização do carimbo.

**Como o pulso é feito a partir da versão 1.1:**

- **Até ~60 ms:** lista `[V_base, V_pulso × k, V_base]` com atraso 0, ou seja, k passos seguidos sem atraso. A largura é **k × T0**.
- **T0** é medido automaticamente no início de cada medida, em 60 passos no **nível de base** (não aplica nada além de V_base à amostra). A resolução dele é ~0,02 ms.
- **Acima de ~60 ms:** um único passo com atraso de fonte; o desvio médio é ajustado pela média dos carimbos.
- **Gravado em cada pulso:**
  - `w_calibrada_ms`: largura pela calibração, resolução = T0. **Use esta na análise.**
  - `t_write_real_ms`: carimbos do 2400, ±0,98 ms. Serve de conferência; a média de vários pulsos converge para a largura real.
  - `passos_pulso`: o k usado.
- **Diagnóstico do atraso de fonte** (aba Instrumento): mede o período real do passo para atrasos de 0 a 100 ms, com nível constante e alternando 0/V, e grava `DIAG_atraso_fonte.csv`. Rode com um resistor e mande o arquivo para documentar o comportamento do seu 2400.
- **Leituras** = lista `[V_leitura] × N` com atraso calculado: a saída volta sozinha a V_base no fim.
- **Laços I-V** = a lista inteira (ex.: −5 → +10 → −5 V, 301 pontos), com taxa de varredura constante e sem pausas nos vértices. No 2400 real, um laço com atraso de 0,1 s deu 0,176 s por ponto, e com 1,0 s deu 1,07 s, sempre gravados em `t_s`.

**O que a comunicação serial ainda afeta:** apenas o intervalo **entre** listas, como pulso → leitura (no simulador, ~0,06–0,1 s a 57600 baud e ~0,37 s a 9600 baud). Esse intervalo é medido e gravado em `atraso_leitura_ms`. Use **57600 baud** no 2400 (MENU › COMMUNICATION › RS-232 › BAUD) e no programa.

**Largura mínima:** T0 ≈ 1 ms (NPLC 0,01); até ~60 ms as larguras são múltiplas de T0. Pulsos < 1 ms continuam exigindo gerador + resistor + osciloscópio (G10-P3).

---

## 2. Organização das abas

### Capacitor MIS / Memória

| Aba | Funções | Guias (predefinições) |
|---|---|---|
| I-V e Laços | vértices arbitrários (`0,1,0`, `-5,10,-5`, `0,10,0,-5,0`), N laços seguidos, série de atrasos sorteada; B/A em várias tensões, RR, V_set, V_reset, taxa real, fechamento do laço | G04-E1/E2/E3, G06, G07-T1/T2/T6, G15, G16-L2/L3 |
| Leitura e Multinível | leitura DC (t_on, média do último trecho); séries M1 V_máx, M2 compliance, M3 V_reset com ordem sorteada | G05-M1/M2/M3 |
| Pulsos | SET, RESET, alternado, série de amplitudes, série de larguras; preparo (RESET de referência) por série; leitura após cada pulso | G10-P1/P2/P4 |
| Sinapse | LTP/LTD (N pulsos + / N pulsos −, ciclos), PPF com dt real | G11-S1/S2/S3 |
| Ciclos | DC (varreduras SET/RESET) ou pulsado; arquivos por bloco (B1, B2...); parada automática se a leitura passar de 0,9 × compliance | G08-C1/C2/C3 |
| Retenção | preparo (varredura ou trem de pulsos) + leituras em tempos log ou periódicas; entre leituras a **0 V** ou **flutuante (HIMP)**, que retém a carga do capacitor | G09-R1/R2/R3, G11-S4 |
| I(t), V fixo e V_oc | segmentos `V:duração` sem desligar, captura rápida inicial, marcação de eventos (luz ON/OFF); V_oc com I = 0; carga integrada Q e C_eff = Q/ΔV | G07-T4, G09-R1 (DC), G15, G16-L1, G17, degrau de capacitor |

### Célula Solar / Diodo

| Aba | Funções |
|---|---|
| Curva J-V | reverso, direto ou ambos; área, irradiância; Voc, Jsc, FF, PCE, Vmp/Jmp, Rs (inclinação em Voc, limite superior) e Rsh (inclinação em 0 V); índice de histerese |
| Diodo (escuro) | log\|J\|-V, ajuste de n e J0 na faixa escolhida, **n local(V)** para escolher a faixa, razão de retificação |
| Estabilidade / MPPT | MPPT (perturba e observa), V fixo, Voc(t), Isc(t), com eventos |

### Registros

- Todo o registro da sessão, com fonte ajustável (A− / A+, padrão 13 pt).
- Filtros: tudo, sem SCPI, só avisos e erros.
- **Salvar em arquivo** grava um `.txt`. O painel de registro embaixo da janela continua existindo.

### Barra de progresso e tema

- **Progresso:** cada aba de medida mostra uma barra de progresso com o indicador girando, a etapa atual, o tempo decorrido, uma estimativa do tempo restante e o horário de término.
- **Barra fina:** acompanha a lista que o 2400 está executando e fica em vai-e-vem entre as listas, para indicar que o programa não travou.
- **Estimativa:** é calculada antes da medida a partir das listas. No simulador ficou a ±5 % da duração real, mas é apenas indicativa.
- **Tema:** Escuro ou Claro, no canto superior direito. A interface é reconstruída na hora sem perder a conexão, os valores das abas nem o registro; a escolha fica salva.

### Instrumento e Arquivos

- Metadados e pasta raiz.
- Terminais frontal/traseiro, 2/4 fios, modo da saída desligada, display, autozero.
- Calibração da sobrecarga e teste de larguras.
- Console SCPI.

---

## 3. Arquivos gravados

O padrão segue `01_Gestao/Padrao_Arquivos_e_Metadados.md`.

- **Nome:** `<amostra>_<pad>_<guia-etapa>_<parâmetro>_<AAAAMMDD-HHMMSS>.csv`. Nunca sobrescreve um arquivo existente.
- **Pasta:** se a raiz for `Caracterizacao_Eletrica_Definitiva`, cada guia grava em `<pasta da técnica>/dados/<amostra>/` (G04 → `20_IV`, G10 → `32_Pulsos`, G17 → `62_Voc`...). Outras etapas (ex.: `SOL-JV`) gravam em `<raiz>/<amostra>/`.
- **Cabeçalho** (`# chave: valor`):
  - campos da campanha: amostra, pad, grupo, guia_etapa, sessão, data_hora_inicio, operador, instrumento (IDN + SN), programa_versao, luz, T_amb_C, UR_pct, parâmetros e observação;
  - acréscimos: `config_instrumento` (terminais, 4 fios, saída desligada, autozero, baud, rede, sobrecarga) e `resumo_*` (B/A, V_set, larguras reais etc.).
- **Colunas com unidade:**
  - I-V: `t_s, V_set_V, V_med_V, I_A, compliance_flag, laco, segmento`;
  - pulsos: `n, V_write_V, w_nominal_ms, w_calibrada_ms, t_write_real_ms, passos_pulso, I_write_A, atraso_leitura_ms, V_read_V, I_read_A, R_ohm, G_S, t_s`;
  - retenção: `t_s, V_read_V, I_A, I_std_A`;
  - ciclos: `ciclo, I_LRS_read_A, I_HRS_read_A, razao, V_set_V, V_reset_V, t_s`;
  - V_oc: `t_s, V_V`.
- **compliance_flag** vem do bit 3 da palavra de status do 2400 (compliance real), ponto a ponto.
- **Cópia de segurança:** em medidas longas, `_parcial_<nome>.csv` é regravado periodicamente e apagado ao fim.
- **PNG:** um PNG do gráfico é gravado com o mesmo nome base (pode ser desligado).

---

## 4. Instalação e uso

- **Instalar:** execute `instalar.bat`. Ele cria `%LOCALAPPDATA%\Open-IV` com um ambiente Python próprio, roda o autoteste e cria o atalho `Open-IV.vbs` na Área de Trabalho.
- **Simulador (treinar sem o instrumento):** `python Open-IV.py --simular mis` (ou `solar`, `resistor`), ou escolha o simulador na barra de conexão. Os modelos são qualitativos e não representam nenhuma amostra.
- **Executável único:** `build.bat` roda os testes e gera `dist\Open-IV.exe` com o PyInstaller.
- **Testes do motor:** `python testes\teste_motor.py`. São 11 grupos (temporização de pulsos, laços, G06, pulsos, sinapse, multinível, ciclos, retenção, V_oc, J-V/diodo/MPPT, cabeçalho).
- **Configuração:** fica em `%APPDATA%\Open-IV\config.json` (porta, baud, metadados, valores de todas as abas, sobrecarga calibrada).

---

## 5. Roteiro de validação no instrumento real (fazer antes das amostras)

O programa foi testado contra um simulador do subconjunto SCPI usado (que agora reproduz o relógio de 1024 Hz e o patamar de atraso observados). No 2400 real, já foram verificados conexão, laços I-V e o teste de larguras da versão 1.0, que motivou o esquema de pulsos da 1.1. Faça esta sequência com um **resistor de 10 kΩ a 1 MΩ** no lugar da amostra:

1. **Conexão.** No 2400, ajuste 57600 baud e terminador `<CR+LF>` ou `<LF>`; no programa, Conectar. O log deve mostrar o `*IDN?` e "rede 60 Hz".
2. **Fila de erros.** Na aba Instrumento, clique em **Erros**: deve estar vazia. Se algum comando não for aceito pelo seu firmware, ele aparece aqui como erro −1xx/−2xx. Envie o texto para corrigirmos.
3. **T0.** Clique em **Medir T0** (200 passos a 0 V). No 2400 de 12/11/2026 deu ~0,98 ms com NPLC 0,01.
4. **Larguras.** Rode **Testar larguras de pulso** (1, 2, 5, 10, 50, 100 ms). Para cada uma:
   - `w_calibrada` deve ficar a menos de T0/2 da nominal até 60 ms e a ~1 % acima disso;
   - a média dos carimbos deve ficar a menos de ~1 ms de `w_calibrada`.
5. **Diagnóstico do atraso de fonte.** Rode e guarde o `DIAG_atraso_fonte.csv`. Ele mostra se existe o patamar de ~10 ms com atrasos pequenos.
6. **Osciloscópio (recomendado uma vez).** Use **Iniciar trem** (aba Instrumento, seção *Osciloscópio*). Ele gera pulsos contínuos com a largura e o período escolhidos (padrão 10 ms / 50 ms) pela duração pedida, e assim o osciloscópio não precisa segurar uma captura única.
   - **Ligação:** ponta de prova sobre o resistor (HI do 2400) e garra no LO.
   - **Disparo:** modo **NORMAL** (não AUTO), borda de subida, nível em ~metade de V.
   - **Base de tempo:** ~2–5 ms/div para 10 ms.
   - **Leitura:** use a medida automática **+Width**, ou "Largura positiva", com estatística ou média. O valor deve coincidir com a largura esperada que aparece no registro.
   - **Congelar:** **SINGLE** (ou Run/Stop) captura um único pulso e congela a tela até você rearmar.
   - Entre uma lista e outra (~1,6 s) aparece uma pausa extra a 0 V, que não afeta a largura.
7. **Retorno ao nível de base.** Com o osciloscópio, confirme que, ao fim de cada lista, a saída volta a V_base (0 V) e não fica no último nível. O programa depende desse comportamento do *custom sweep*.
8. **Laço.** Rode um laço −1 → +1 → −1 V nos dois modos de temporização. As curvas devem ser retas (resistor) e coincidir; `periodo_ponto_s` no cabeçalho deve bater com atraso + medida.
9. **Compliance.** Com compliance baixa (ex.: 10 µA a 1 V em 10 kΩ), confirme que `compliance_flag = 1` aparece nos pontos limitados.
10. **V_oc.** Rode o modo `I = 0 → V_oc` com a ponta levantada ou numa pilha. A leitura deve ser a esperada e o arquivo deve registrar `atraso_preparo_para_1a_leitura_s`.

---

## 6. Limites conhecidos

- **Botão Parar:** age ao fim da lista que está rodando no instrumento. Por RS-232 não há como abortar uma lista no meio. Em listas longas, use o EXIT do painel do 2400 em emergência.
- **Tamanho das listas:** cada laço tem no máximo 2500 pontos. Laços seguidos são agrupados na mesma lista quando cabem, para não haver pausa entre eles.
- **Gráfico:** no modo "Instrumento", ele atualiza no fim de cada lista. Use "Ponto a ponto" para ver ao vivo, sabendo que o período por ponto fica maior e irregular.
- **Corrente durante o pulso:** é medida numa faixa fixa (= compliance) e com NPLC baixo. É indicativa, e não substitui a leitura.
- **Medir V:** marcar "Medir V" com autozero dobra o tempo de medida por ponto (2 funções). Isso entra na taxa de varredura real, que está sempre na coluna `t_s`.
- **Análises na tela** (B/A, V_set, Rs, n etc.): servem para acompanhar a medida. A análise definitiva é feita em `90_Analise` a partir dos dados brutos.

---

## 7. Mudanças da versão 1.1.2 (19/11/2026)

Validado no 2400 real com um resistor de 100 kΩ, sem nenhum erro na fila: 100 listas de 200 pontos e 20 de 2500; T0 medido 10× (0,633 a 0,638 ms); laço de 401 pontos; 5 min de pulsos alternados. No osciloscópio, o trem de 10 ms / 50 ms saiu com os valores nominais, e o pulso de 1 ms (2 × T0) deu 1,28 ms.

- **Causa dos comandos perdidos:** o driver do adaptador CH340 recusa o `SetCommState` (erro Win32 31) ou não aplica o baud ao chip, conforme a configuração anterior da porta. O driver Win32 do Open-IV ignorava essa falha, então a porta ficava com a configuração que já estava no Windows (9600 no Gerenciador de Dispositivos) ou com uma mudança aplicada pela metade. O pyserial falhava pelo mesmo motivo.
- **Abertura da porta:** sempre a sequência alvo → 9600 → alvo, com o retorno conferido e a configuração lida de volta. Em 20 aberturas seguidas, partindo de 9600, 19200, 38400 ou 57600, o 2400 respondeu em todas. No Windows o driver próprio passou a ser o padrão; o pyserial fica como reserva (e com timeout fixo, porque alterá-lo refaz o `SetCommState`).
- **Sincronismo `*OPC?` (padrão):** depois de cada bloco de lista, e sempre que ~96 bytes estiverem em trânsito, o programa espera o `1` do `*OPC?`. O modo antigo, só com pausas, continua disponível na aba Instrumento.
- **XON/XOFF (reserva):** opção na aba Instrumento. Exige FLOW-CTRL = XON-XOFF no 2400.
- **Recuperação:** qualquer erro na fila descarta o cache, inclusive quando a fila é lida pelo botão Erros ou por Aplicar configuração; antes, esse caminho deixava o cache errado. Antes do `:READ?`, a configuração completa é reenviada e o preparo é refeito uma vez. Se o erro persistir, a medida é interrompida. Nenhum pulso é repetido, porque a recuperação ocorre antes da execução.
- **Conferência:** quando a configuração muda, o programa lê de volta `:SOUR:DEL?`, `:TRIG:COUN?`, `:SOUR:LIST:VOLT:POIN?` e `:SOUR:VOLT:MODE?`. Pode ser desligada na aba Instrumento.
- **Atrasos arredondados a 10 µs,** que é a resolução com que o 2400 guarda o `:SOUR:DEL`.
- **Simulador:** modela o buffer de entrada e reproduz o `-363` quando o `*OPC?` está desligado. Novos testes em `testes/teste_motor.py` (seções 10c e 10d).
- **`testes/teste_serial_2400.py`:** testes no instrumento real (envio de listas, aceitação e pulsos alternados), com os limites de segurança embutidos.

## 7a. Mudanças da versão 1.1.1 (19/11/2026)

Teste no 2400 real (SN 0978216) em 19/11/2026:

- **Problema:** a 57600 baud apareceram erros `-363 Input buffer overrun` e `-223 Too much data`. O 2400 aceita no máximo ~100 valores por comando de lista, e o buffer de entrada RS-232 dele é pequeno. Com comandos perdidos, o programa supunha atraso 0 quando ele não estava aplicado, e por isso o primeiro T0 saiu errado (10,5 ms).
- **Depois de reconectar:** T0 = 0,63 ms, larguras 1 → 1,26, 2 → 1,89, 5 → 5,03, 10 → 10,06, 50 → 50,0 e 100 → 99,9 ms.
- **Atraso de fonte:** 0 → 0,64 ms por passo; de 0,1 a 7 ms → ~10 ms por passo; de 10 ms em diante → atraso + ~3 ms.

Correções:

- **Envio das listas:** no máximo 50 valores por comando (`:APPend` para o resto). Comandos longos vão em blocos de 32 bytes com pausa.
- **Conferência:** depois de cada lista, `:SOUR:LIST:VOLT:POIN?` confere quantos pontos o 2400 recebeu. Na conexão, uma sonda verifica uma lista de 300 pontos.
- **Erros:** antes de cada medida, se a configuração mudou, o programa lê a fila de erros. Qualquer erro **interrompe a medida** com a mensagem do instrumento e descarta o cache.
- **Osciloscópio:** novo trem contínuo de pulsos (aba Instrumento).
- **Simulador:** agora rejeita comandos com mais de 100 valores, como o 2400.

## 7b. Mudanças da versão 1.1 (12/11/2026)

- **Pulsos:** passaram a ser k passos sem atraso (largura = k × T0, com T0 recalibrado a cada medida no nível de base). A correção pulso a pulso foi removida; a nova coluna `w_calibrada_ms` traz a largura usada na análise.
- **Instrumento:** novo diagnóstico do atraso de fonte e teste de larguras com média dos carimbos.
- **Simulador:** agora tem relógio de 1024 Hz e patamar de ~10 ms para atrasos pequenos, como observado no 2400 real.
- **Interface:** tema claro, aba **Registros** com fonte ajustável, filtro e gravação em `.txt`, e barra de progresso com indicador de atividade, tempo decorrido, restante e término.
- **Conexão:** se o pyserial não abrir a porta e o programa usar o driver Win32, o motivo aparece no registro.

## 8. Mudanças em relação ao MemristorProbe 1.3

- **Temporização:** pulsos, leituras e laços passaram a ser listas temporizadas pelo 2400. A largura real vem dos carimbos de tempo, e não do relógio do PC.
- **Saída:** a saída fica ligada no nível de base durante a medida; o relé não chaveia a cada pulso.
- **Comunicação:** foi removida a pausa fixa de 15 ms por comando; comandos repetidos não são reenviados (cache).
- **Faixas:** a faixa da fonte é fixa durante a varredura (`:SOUR:SWE:RANG BEST`), sem degraus de troca de faixa.
- **Compliance:** é detectada ponto a ponto pela palavra de status.
- **Estados:** o estado deixou de ser inferido pela polaridade ("LRS se V > 0"). As séries são nomeadas pela escrita, e as leituras "após SET" e "após RESET" são gravadas como tal.
- **Organização:** as funções foram redistribuídas em duas áreas (MIS/memória e células solares/diodos) mais a aba Instrumento. Foram incluídas as medidas dos guias da campanha que o programa antigo não fazia: multinível, sinapse/PPF, retenção agendada, flutuante, V_oc e transientes.
- **Arquivos:** nome e cabeçalho seguem o padrão da campanha, inclusive o **pad**, que as medidas Keithley de 2026 não registravam.
- **Testes:** simulador do instrumento e testes automáticos.

## 9. Estrutura

```
Open-IV.py                 ponto de entrada (--simular mis|solar|resistor)
open_iv/transporte.py      serial (pyserial; fallback Win32)
open_iv/keithley.py        driver SCPI: listas temporizadas, configuracao, parse com status
open_iv/medidas.py         motor: primitivas (varrer, ler, pulso) e experimentos por guia
open_iv/analise.py         B/A, V_set, RR, taxa real; parametros solares; ajuste de diodo
open_iv/arquivos.py        nomes, pastas, CSV com cabecalho, configuracao persistente
open_iv/simulador.py       simulador do 2400 (capacitor MIS, celula solar, resistor)
open_iv/gui/               interface (customtkinter): app, mis, solar, instrumento, base
testes/teste_motor.py      testes do motor com o simulador
```
