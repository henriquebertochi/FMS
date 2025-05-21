import os
import subprocess
import time
import threading
import ctypes
import psutil
import json
import datetime
from ctypes import wintypes
import pythoncom
import win32com.client
# Adicione no início do arquivo (após os imports)
try:
    import colorama
    colorama.init()
    GREEN = colorama.Fore.GREEN
    RED = colorama.Fore.RED
    YELLOW = colorama.Fore.YELLOW
    BLUE = colorama.Fore.BLUE
    RESET = colorama.Fore.RESET
except ImportError:
    # Fallback para códigos ANSI se colorama não estiver disponível
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

# Importando as APIs do Windows necessárias
kernel32 = ctypes.windll.kernel32

# Estruturas e constantes do Windows para acessar informações de processos


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


class FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class ProcessMonitor:
    """Classe responsável por monitorar recursos de um processo"""

    def __init__(self, pid, cpu_quota, memory_limit, timeout):
        self.pid = pid
        self.cpu_quota = cpu_quota  # Tempo de CPU em segundos
        self.memory_limit = memory_limit  # Limite de memória em MB
        self.timeout = timeout  # Timeout em segundos
        self.start_time = time.time()
        self.process = psutil.Process(pid)
        self.max_memory_usage = 0
        self.total_cpu_time = 0
        self.monitoring = True
        self.killed = False
        self.process_tree = []
        self.update_process_tree()

    def update_process_tree(self):
        """Atualiza a árvore de processos filho"""
        try:
            self.process_tree = [self.process]
            for child in self.process.children(recursive=True):
                self.process_tree.append(child)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def get_process_memory(self):
        """Obtém o uso de memória do processo e seus filhos"""
        total_memory = 0
        self.update_process_tree()

        for proc in self.process_tree:
            try:
                total_memory += proc.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return total_memory / (1024 * 1024)  # Converte para MB

    def get_process_cpu_time(self):
        """Obtém o tempo total de CPU (usuário + sistema) do processo e seus filhos"""
        total_cpu_time = 0
        self.update_process_tree()

        for proc in self.process_tree:
            try:
                total_cpu_time += proc.cpu_times().user + proc.cpu_times().system
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return total_cpu_time

    def is_process_running(self):
        """Verifica se o processo principal ainda está em execução"""
        try:
            return self.process.is_running()
        except psutil.NoSuchProcess:
            return False

    def kill_process_tree(self):
        """Mata o processo e todos os seus filhos"""
        self.update_process_tree()
        for proc in reversed(self.process_tree):  # Mata do filho para o pai
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        self.killed = True

    def monitor_resources(self):
        """Monitora recursos do processo em uma thread separada"""
        while self.monitoring and self.is_process_running():
            current_time = time.time()
            elapsed_time = current_time - self.start_time

            # Verifica memória utilizada
            memory_usage = self.get_process_memory()
            if memory_usage > self.max_memory_usage:
                self.max_memory_usage = memory_usage

            # Verifica o tempo de CPU
            cpu_time = self.get_process_cpu_time()
            self.total_cpu_time = cpu_time

            # Verificação de créditos em tempo real (pré-pago)
            if hasattr(self, 'credit_manager') and self.payment_mode == "prepaid":
                execution_cost = self.credit_manager.calculate_execution_cost(
                    cpu_time,
                    self.max_memory_usage,
                    elapsed_time
                )
                if execution_cost > self.credit_manager.credits:
                    print(
                        "\n\033[91mCRÉDITOS ESGOTADOS DURANTE A EXECUÇÃO!\033[0m")
                    print(
                        f"\033[91mCusto atual: {execution_cost:.2f} créditos | Créditos disponíveis: {self.credit_manager.credits:.2f}\033[0m")
                    self.kill_process_tree()
                    return "NO_CREDITS"

            # Exibe progresso
            print(f"\rProgresso: CPU={cpu_time:.2f}s/{self.cpu_quota:.2f}s ({cpu_time/self.cpu_quota*100:.1f}%), "
                  f"Memória={memory_usage:.2f}MB/{self.memory_limit:.2f}MB ({memory_usage/self.memory_limit*100:.1f}%), "
                  f"Tempo={elapsed_time:.2f}s/{self.timeout if self.timeout else 'inf'}s", end="")

            # Verifica limites de recursos
            if self.memory_limit and memory_usage > self.memory_limit:
                print(
                    f"\n\033[91mProcesso excedeu o limite de memória: {memory_usage:.2f}MB > {self.memory_limit:.2f}MB\033[0m")
                self.kill_process_tree()
                return "MEMORY_EXCEEDED"

            if cpu_time > self.cpu_quota:
                print(
                    f"\n\033[91mProcesso excedeu a quota de CPU: {cpu_time:.2f}s > {self.cpu_quota:.2f}s\033[0m")
                self.kill_process_tree()
                return "CPU_EXCEEDED"

            if self.timeout and elapsed_time >= (self.timeout - 0.5):
                print(
                    f"\n\033[91mProcesso excedeu o timeout: {elapsed_time:.2f}s > {self.timeout:.2f}s\033[0m")
                self.kill_process_tree()
                return "TIMEOUT"

            memory_usage = self.get_process_memory()
            if memory_usage > self.max_memory_usage:
                self.max_memory_usage = memory_usage

            cpu_time = self.get_process_cpu_time()
            self.total_cpu_time = cpu_time

            print(f"\rProgresso: CPU={cpu_time:.2f}s/{self.cpu_quota:.2f}s ({cpu_time/self.cpu_quota*100:.1f}%), "
                  f"Memória={memory_usage:.2f}MB/{self.memory_limit:.2f}MB ({memory_usage/self.memory_limit*100:.1f}%), "
                  f"Tempo={elapsed_time:.2f}s/{self.timeout if self.timeout else 'inf'}s", end="")

            time.sleep(0.1)  # Verificação mais frequente

        return "NORMAL_EXIT"

    def start_monitoring(self):
        """Inicia o monitoramento em uma thread separada"""
        monitor_thread = threading.Thread(target=self.monitor_resources)
        monitor_thread.daemon = True
        monitor_thread.start()
        return monitor_thread

    def stop_monitoring(self):
        """Para o monitoramento"""
        self.monitoring = False


class CreditManager:
    """Gerenciador de créditos para o sistema de pré-pago e pós-pago"""

    def __init__(self, user="default_user"):
        self.user = user
        self.credits_file = f"fms_credits_{user}.json"
        self.usage_file = f"fms_usage_{user}.json"
        self.credits = self.load_credits()
        self.cost_per_cpu_second = 1.0  # Custo por segundo de CPU
        self.cost_per_mb_second = 0.1   # Custo por MB*segundo de memória

    def load_credits(self):
        """Carrega os créditos do usuário do arquivo"""
        try:
            if os.path.exists(self.credits_file):
                with open(self.credits_file, 'r') as f:
                    data = json.load(f)
                    return data.get('credits', 0)
            return 0
        except Exception as e:
            print(f"Erro ao carregar créditos: {str(e)}")
            return 0

    def save_credits(self):
        """Salva os créditos do usuário em arquivo"""
        try:
            with open(self.credits_file, 'w') as f:
                json.dump({'user': self.user, 'credits': self.credits}, f)
        except Exception as e:
            print(f"Erro ao salvar créditos: {str(e)}")

    def add_credits(self, amount):
        """Adiciona créditos à conta do usuário"""
        if amount > 0:
            self.credits += amount
            self.save_credits()
            print(
                f"\nAdicionado {amount:.2f} créditos. Total: {self.credits:.2f} créditos")
            return True
        return False

    def deduct_credits(self, amount):
        """Deduz créditos da conta do usuário"""
        if amount <= 0:
            return True

        if self.credits >= amount:
            self.credits -= amount
            self.save_credits()
            print(
                f"\nDeduzido {amount:.2f} créditos. Restante: {self.credits:.2f} créditos")
            return True
        else:
            print(
                f"\nCréditos insuficientes. Necessário: {amount:.2f}, Disponível: {self.credits:.2f}")
            return False

    def calculate_execution_cost(self, cpu_time, memory_max, execution_time):
        """Calcula o custo da execução baseado no uso de recursos"""
        cpu_cost = cpu_time * self.cost_per_cpu_second
        memory_cost = memory_max * execution_time * \
            self.cost_per_mb_second / 60  # Custo da memória é por minuto
        total_cost = cpu_cost + memory_cost
        return total_cost

    def log_usage(self, binary_name, cpu_time, memory_max, execution_time, cost):
        """Registra o uso para faturamento no modo pós-pago"""
        try:
            usage_data = []
            if os.path.exists(self.usage_file):
                with open(self.usage_file, 'r') as f:
                    usage_data = json.load(f)

            # Registra novo uso
            usage_entry = {
                'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'binary': binary_name,
                'cpu_time': cpu_time,
                'memory_max': memory_max,
                'execution_time': execution_time,
                'cost': cost
            }

            usage_data.append(usage_entry)

            with open(self.usage_file, 'w') as f:
                json.dump(usage_data, f, indent=2)

            print(f"\nUso registrado para faturamento: {cost:.2f} créditos")

        except Exception as e:
            print(f"Erro ao registrar uso: {str(e)}")

    def show_usage_report(self):
        """Mostra relatório de uso para faturamento pós-pago"""
        try:
            if not os.path.exists(self.usage_file):
                print("\nNenhum registro de uso encontrado.")
                return

            with open(self.usage_file, 'r') as f:
                usage_data = json.load(f)

            if not usage_data:
                print("\nNenhum registro de uso encontrado.")
                return

            print("\n=== Relatório de Uso (Pós-pago) ===")
            print(
                f"{'Data/Hora':<20} {'Binário':<30} {'CPU(s)':<10} {'Mem(MB)':<10} {'Tempo(s)':<10} {'Custo':<10}")
            print("-" * 90)

            total_cost = 0
            for entry in usage_data:
                print(f"{entry['timestamp']:<20} {os.path.basename(entry['binary']):<30} "
                      f"{entry['cpu_time']:<10.2f} {entry['memory_max']:<10.2f} "
                      f"{entry['execution_time']:<10.2f} {entry['cost']:<10.2f}")
                total_cost += entry['cost']

            print("-" * 90)
            print(f"Total a pagar: {total_cost:.2f} créditos")

        except Exception as e:
            print(f"Erro ao gerar relatório: {str(e)}")

    def clear_usage_history(self):
        """Limpa o histórico de uso após o pagamento"""
        try:
            if os.path.exists(self.usage_file):
                os.remove(self.usage_file)
                print("\nHistórico de uso limpo após pagamento.")
            else:
                print("\nNão há histórico de uso para limpar.")
        except Exception as e:
            print(f"Erro ao limpar histórico: {str(e)}")


class FMS:
    """Classe principal do File Monitoring System"""

    def __init__(self):
        self.run_binary_results = {}
        self.remaining_cpu_quota = 0
        self.used_cpu_quota = 0
        self.payment_mode = None  # "prepaid" ou "postpaid"
        self.credit_manager = None

    def run_binary(self, binary_path, cpu_quota, memory_limit, timeout):
        """Executa um binário com monitoramento de recursos"""
        try:
            # Verifica se o arquivo existe
            if not os.path.exists(binary_path):
                print(f"{RED}Erro: O arquivo '{binary_path}' não existe!{RESET}")
                return "ERROR"

            print(f"\nExecutando: {binary_path}")
            print(f"Quota de CPU: {cpu_quota:.2f}s")
            print(f"Limite de memória: {memory_limit:.2f}MB")
            print(f"Timeout: {timeout if timeout else 'Sem limite'}s")

            # Resolve atalhos .lnk
            if binary_path.lower().endswith(".lnk"):
                try:
                    shell = win32com.client.Dispatch("WScript.Shell")
                    binary_path = shell.CreateShortCut(binary_path).Targetpath
                    print(f"Caminho real resolvido: {binary_path}")
                except Exception as e:
                    print(f"{RED}Erro ao resolver o atalho: {e}{RESET}")
                    return "ERROR"

            # Executa o processo
            start_time = time.time()
            process = subprocess.Popen(binary_path)
            monitor = ProcessMonitor(process.pid, cpu_quota, memory_limit, timeout)
            monitor_thread = monitor.start_monitoring()

            # Adiciona a verificação da tecla ENTER
            def check_for_enter():
                input()  # Espera ENTER
                monitor.stop_monitoring()
                process.terminate()
                
            enter_thread = threading.Thread(target=check_for_enter)
            enter_thread.daemon = True
            enter_thread.start()

            # Monitora com verificações mais frequentes
            while monitor.is_process_running():
                if not monitor.monitoring:
                    break
                time.sleep(0.1)

                # Verificação antecipada do timeout (0.5s antes)
                elapsed_time = time.time() - start_time
                if timeout and elapsed_time >= (timeout - 0.5):
                    print(f"\n{YELLOW}Aviso: Aproximando-se do timeout ({timeout}s){RESET}")
                    monitor.stop_monitoring()
                    process.terminate()
                    break

                time.sleep(0.1)

            # Encerramento seguro
            if process.poll() is None:
                print(f"\n{RED}Encerrando processo forçadamente.{RESET}")
                process.kill()
            process.wait()

            # Finaliza monitoramento
            monitor.stop_monitoring()
            enter_thread.join(timeout=0.1)
            monitor_thread.join(timeout=1)
            end_time = time.time()
            execution_time = end_time - start_time
            final_cpu = monitor.total_cpu_time
            final_mem = monitor.max_memory_usage

            # Verificação de créditos (pré-pago)
            if hasattr(self, 'credit_manager') and self.payment_mode == "prepaid":
                execution_cost = self.credit_manager.calculate_execution_cost(
                    final_cpu,
                    final_mem,
                    execution_time
                )
                if execution_cost > self.credit_manager.credits:
                    print(f"\n{RED}ERRO: Créditos insuficientes durante a execução!{RESET}")
                    print(f"{RED}Custo total: {execution_cost:.2f} créditos | Créditos disponíveis: {self.credit_manager.credits:.2f}{RESET}")
                    return "NO_CREDITS"

            # Exibir relatório (sempre)
            print(f"\n{GREEN}=== RELATÓRIO ==={RESET}")
            print(f"{GREEN}Tempo de execução: {execution_time:.2f}s{RESET}")
            print(f"{GREEN}Tempo de CPU utilizado: {final_cpu:.2f}s{RESET}")
            print(f"{GREEN}Uso máximo de memória: {final_mem:.2f}MB{RESET}")

            # Atualizar quota no modo tradicional
            if not hasattr(self, 'credit_manager') or self.credit_manager is None:
                # Atualizar quota apenas se não excedeu os limites
                if monitor.killed:
                    if final_cpu > cpu_quota:
                        print(f"{RED}CPU excedida: {final_cpu:.2f}s > {cpu_quota:.2f}s{RESET}")
                        return "LIMIT_EXCEEDED"
                    elif final_mem > memory_limit:
                        print(f"{RED}Memória excedida: {final_mem:.2f}MB > {memory_limit:.2f}MB{RESET}")
                        return "LIMIT_EXCEEDED"
                    elif timeout and execution_time >= timeout:      
                        print(f"{RED}Timeout: {execution_time:.2f}s >= {timeout:.2f}s{RESET}")
                        return "TIMEOUT"
                
                self.used_cpu_quota += final_cpu
                print(f"{GREEN}Quota utilizada: {self.used_cpu_quota:.2f}s/{self.remaining_cpu_quota:.2f}s{RESET}")
                print(f"{GREEN}Quota restante: {self.remaining_cpu_quota - self.used_cpu_quota:.2f}s{RESET}")

            # Verificação de créditos (apenas para modos pré/pós-pago)
            if hasattr(self, 'credit_manager') and self.credit_manager is not None:
                execution_cost = self.credit_manager.calculate_execution_cost(
                    final_cpu,
                    final_mem,
                    execution_time
                )
                print(f"{GREEN}Custo: {execution_cost:.2f} créditos{RESET}")
                
                if self.payment_mode == "postpaid":
                    self.credit_manager.log_usage(
                        binary_path,
                        final_cpu,
                        final_mem,
                        execution_time,
                        execution_cost
                    )
                elif self.payment_mode == "prepaid":
                    if not self.credit_manager.deduct_credits(execution_cost):
                        print(f"{RED}Créditos insuficientes!{RESET}")
                        return "NO_CREDITS"

            return "SUCCESS"

        except Exception as e:
            print(f"{RED}Erro executando binário: {str(e)}{RESET}")
            return "ERROR"

    def setup_payment_mode(self):
        """Configura o modo de pagamento"""
        print("\n=== Configuração do Modo de Pagamento ===")
        print("1. Operação pré-paga (com base em créditos)")
        print("2. Operação pós-paga (pague pelo uso)")
        print("3. Operação tradicional (baseada em quota)")

        while True:
            option = input("\nEscolha o modo de operação: ")

            if option == "1":
                self.payment_mode = "prepaid"
                username = input("Digite seu nome de usuário: ")
                self.credit_manager = CreditManager(username)
                print(f"Modo Pré-pago configurado para {username}.")
                print(
                    f"Créditos disponíveis: {self.credit_manager.credits:.2f}")

                if self.credit_manager.credits <= 0:
                    add_credits = input(
                        "Você não tem créditos. Deseja adicionar agora? (s/n): ")
                    if add_credits.lower() == "s":
                        try:
                            amount = float(
                                input("Digite a quantidade de créditos a adicionar: "))
                            self.credit_manager.add_credits(amount)
                        except ValueError:
                            print("Quantidade inválida. Nenhum crédito adicionado.")
                return True

            elif option == "2":
                self.payment_mode = "postpaid"
                username = input("Digite seu nome de usuário: ")
                self.credit_manager = CreditManager(username)
                print(f"Modo Pós-pago configurado para {username}.")
                print("Os custos serão registrados e faturados posteriormente.")
                return True

            elif option == "3":
                self.payment_mode = None
                self.credit_manager = None
                # Configure a quota tradicional
                while True:
                    try:
                        quota = float(
                            input("\nDigite a quota total de tempo de CPU (em segundos): "))
                        if quota <= 0:
                            print("A quota deve ser positiva.")
                        else:
                            self.remaining_cpu_quota = quota
                            break
                    except ValueError:
                        print("Por favor, digite um número válido.")
                return True

            else:
                print("Opção inválida. Por favor, escolha 1, 2 ou 3.")

    def main_loop(self):
        """Loop principal do programa FMS"""
        print("=== File Monitoring System (FMS) ===")
        
        # Configura o modo de pagamento
        if not self.setup_payment_mode():
            print("Configuração falhou. Encerrando FMS.")
            return

        running = True
        while running:
            # Verificação de quota/créditos
            if self.payment_mode is None:
                remaining = self.remaining_cpu_quota - self.used_cpu_quota
                print(f"\n{GREEN}Quota CPU restante: {remaining:.2f}s{RESET}")
                # Só encerra se a quota foi totalmente consumida sem exceder
                if remaining <= 0 and not any(self.run_binary_results.values()):
                    print("\nQuota total de CPU esgotada. Encerrando FMS.")
                    break
            elif self.payment_mode == "prepaid":
                print(f"\n{GREEN}Créditos disponíveis: {self.credit_manager.credits:.2f}{RESET}")
                if self.credit_manager.credits < 5:
                    add_more = input("Créditos baixos. Deseja adicionar mais? (s/n): ")
                    if add_more.lower() == "s":
                        self.credit_management_menu()

            # Menu principal
            print("\n=== Menu Principal ===")
            print("1. Executar binário")
            if self.credit_manager:
                print("2. Gerenciar créditos/pagamentos")
            print("0. Sair")

            option = input("\nEscolha uma opção: ")

            if option == "0":
                running = False  # Sai do loop principal
                continue

            elif option == "1":
                binary_path = input("\nDigite o caminho do binário a ser executado: ")
                if binary_path.lower() == 'sair':
                    running = False
                    continue

                try:
                    binary_cpu_quota = float(input("Digite a quota de tempo de CPU (segundos): "))
                    if binary_cpu_quota <= 0:
                        print("A quota deve ser positiva.")
                        continue

                    if self.payment_mode is None and binary_cpu_quota > (self.remaining_cpu_quota - self.used_cpu_quota):
                        print(f"Erro: Quota excede a disponível ({self.remaining_cpu_quota - self.used_cpu_quota:.2f}s)")
                        continue

                    memory_limit = float(input("Limite de memória (MB, 0 para sem limite): ") or 0)
                    timeout_input = input("Timeout (segundos, 0 para sem timeout): ")
                    timeout = float(timeout_input) if timeout_input and float(timeout_input) > 0 else None

                    result = self.run_binary(binary_path, binary_cpu_quota, memory_limit, timeout)
                    self.run_binary_results[binary_path] = result  # Armazenar resultados

                    if result == "NO_CREDITS":
                        print("\nCréditos esgotados. Encerrando FMS.")
                        running = False
                    elif result == "LIMIT_EXCEEDED":
                        print("\nLimite de recursos excedido. Retornando ao menu...")
                        continue
                    elif result == "TIMEOUT":
                        continue_option = input("\nDeseja continuar no menu? (s/n): ")
                        if continue_option.lower() != 's':
                            running = False

                except ValueError:
                    print("Valores inválidos. Tente novamente.")

            elif option == "2" and self.credit_manager:
                self.credit_management_menu()

            else:
                print("Opção inválida.")

        # Relatório final
        print(f"\n{GREEN}=== FMS encerrado ==={RESET}")
        if self.payment_mode is None:
            print(f"{GREEN}Tempo CPU total: {self.used_cpu_quota:.2f}s/{self.remaining_cpu_quota:.2f}s{RESET}")
        elif self.payment_mode == "prepaid":
            print(f"{GREEN}Créditos finais: {self.credit_manager.credits:.2f}{RESET}")
        elif self.payment_mode == "postpaid":
            print(f"{GREEN}Consulte seu histórico para ver a fatura.{RESET}")

if __name__ == "__main__":
    fms = FMS()
    fms.main_loop()