O FMS é um código em Python para executar e monitorar arquivos binários, controlando o uso de CPU, memória e tempo de execução.

## Recursos Principais

* Execução de binários com limites de recursos (CPU, memória, timeout).
* Três modos de operação:
    * **Pré-pago**: Use créditos para pagar pela execução.
    * **Pós-pago**: Registre o uso para faturamento posterior.
    * **Tradicional**: Use uma quota total de CPU.
* Gerenciamento de créditos e relatórios de uso.
* Interface de linha de comando.
* Interrupção de processos com a tecla Enter.

## Requisitos

* Python 3.x
* Bibliotecas: `psutil`, `colorama` (opcional), `pywin32` (otimizado para Windows).

## Como Usar

1.  **Configure o Modo de Operação**:
    * Ao iniciar, escolha entre Pré-pago (1), Pós-pago (2) ou Tradicional/Quota (3).
    * **Pré-pago**: Digite um nome de usuário. Adicione créditos se necessário.
    * **Pós-pago**: Digite um nome de usuário. Os custos serão registrados.
    * **Tradicional**: Defina uma quota total de CPU.

2.  **Menu Principal**:
    * **Executar binário (Opção 1)**:
        * Forneça o caminho do arquivo.
        * Defina a quota de CPU para a execução.
        * Defina o limite de memória (MB, `0` para sem limite).
        * Defina o timeout (segundos, `0` para sem limite).
    * **Gerenciar créditos/pagamentos (Opção 2, se aplicável)**:
        * **Pré-pago**: Adicionar/ver créditos.
        * **Pós-pago**: Ver relatório de uso/limpar histórico.
    * **Sair (Opção 0)**.

3.  **Interromper Processo**: Durante a execução de um binário, você pode pressionar `Enter` para encerrá-lo.
    * No fim do processo, dependendo do modo escolhido, ele irá gerar um arquivo com as informações utilizadas:
        * `fms_credits_<username>.json`: Saldo de créditos (modo pré-pago).
        * `fms_usage_<username>.json`: Log de uso (modo pós-pago).
