# File Monitoring System (FMS)

Este programa implementa um sistema de monitoramento de execução de binários com controle de recursos (CPU, memória e timeout) conforme especificado nos requisitos.

## Requisitos

- Windows (devido ao uso das APIs específicas do Windows)
- Python 3.6 ou superior
- Biblioteca psutil

## Instalação

Instale a biblioteca necessária usando pip:

```
pip install -r requirements.txt
```

Ou diretamente:

```
pip install psutil
```

## Funcionalidades implementadas

- **Requisitos obrigatórios**:
  - Lança a execução de qualquer programa executável informado pelo usuário
  - Solicita ao usuário:
    - Quota de tempo de CPU para execução
    - Timeout para execução
    - Montante máximo de memória para execução
  - Monitora a execução do processo:
    - Identifica quando o programa termina
    - Quantifica o tempo de CPU utilizado (usuário e sistema)
    - Quantifica o máximo de memória utilizado
    - Controla o tempo de relógio e mata o processo caso o timeout expire
  - Funciona em laço, solicitando um novo binário enquanto houver quota disponível
  - Encerra em caso de limite de CPU ou memória excedido (o timeout não encerra o FMS)

- **Requisitos recomendados**:
  - Utiliza thread para monitorar constantemente o consumo de CPU e memória (a cada segundo)
  - Reporta ao usuário o progresso do consumo de CPU e memória
  - Não desconta da quota execuções que falham
  - Monitora a árvore completa de processos criados

## Como usar

1. Execute o script `FMS.py`:
   ```
   python FMS.py
   ```

2. Informe a quota total de tempo de CPU (em segundos)

3. Para cada programa a ser executado:
   - Informe o caminho completo do binário
   - Defina a quota de CPU para este binário específico
   - Defina o limite de memória (em MB)
   - Defina o timeout (em segundos)

4. O sistema monitora a execução e apresenta:
   - Progresso em tempo real
   - Relatório após a execução
   - Encerramento automático se limites forem excedidos

5. Digite 'sair' para encerrar o programa a qualquer momento

## Implementação

O programa utiliza:
- `psutil`: para monitoramento de recursos do processo
- `ctypes`: para acessar as APIs do Windows (Sysinfoapi.h e processthreadsapi.h)
- `threading`: para monitoramento em paralelo
- `subprocess`: para execução de processos

## Observações

- O tempo de CPU é diferente do tempo de relógio (walltime)
- O programa monitora tanto o tempo de CPU quanto o tempo real de execução
- A memória é monitorada em MB
- O programa é capaz de monitorar toda a árvore de processos criada pelo binário principal

Retorno consistente: A função agora sempre retorna um dos seguintes valores:

"COMPLETED" - Execução concluída normalmente

"TIMEOUT" - Processo foi encerrado por timeout

"ERROR" - Ocorreu um erro durante a execução

"LIMIT_EXCEEDED" - Processo excedeu algum limite (CPU, memória)

"NO_CREDITS" - Modo pré-pago sem créditos suficientes