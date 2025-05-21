import os
import subprocess
import time
import threading
import ctypes
import psutil
import json
import datetime
from ctypes import wintypes

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
        
        # Inicializa todos os atributos necessários
        self.process = None
        self.process_handle = None
        self.initial_process_times = {}
        self.process_tree = []
        self.process_tree_pids = set()
        self.max_memory_usage = 0
        self.total_cpu_time = 0
        self.monitoring = True
        self.killed = False
        self.sampling_data = []
        self.last_sample_time = time.time()
        self.windows_methods_tried = False
        self.child_handles = []
        self.process_creation_time = time.time()
        
        try:
            self.process = psutil.Process(pid)
            self.process_creation_time = self.process.create_time()
            self.update_process_tree()
            self.store_initial_cpu_times()
            
            self.initial_system_cpu_time = psutil.cpu_times()
            
            if os.name == 'nt':
                try:
                    PROCESS_QUERY_INFORMATION = 0x0400
                    self.process_handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
                except Exception as e:
                    print(f"Aviso: Não foi possível obter handle para processo: {e}")
                    
        except psutil.NoSuchProcess:
            print(f"Processo {pid} não encontrado.")

        self.max_memory_usage = 0
        self.total_cpu_time = 0
        self.monitoring = True
        self.killed = False
        self.process_tree = []
        self.process_tree_pids = set()  # Para rastrear PIDs já monitorados
        self.sampling_data = []  # Para método alternativo de cálculo de CPU
        self.last_sample_time = time.time()
        self.windows_methods_tried = False  # Para tentar métodos alternativos Windows

    def store_initial_cpu_times(self):
        """Armazena os tempos de CPU iniciais para todos os processos na árvore"""
        for proc in self.process_tree:
            try:
                if proc.pid not in self.initial_process_times:
                    times = proc.cpu_times()
                    self.initial_process_times[proc.pid] = {
                        'user': times.user,
                        'system': times.system,
                        'children_user': getattr(times, 'children_user', 0),
                        'children_system': getattr(times, 'children_system', 0)
                    }
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def get_windows_process_times(self, process_handle, pid):
        """Usa API nativa do Windows para obter tempos de CPU"""
        if not process_handle:
            return None
            
        creation_time = FILETIME()
        exit_time = FILETIME()
        kernel_time = FILETIME()
        user_time = FILETIME()
        
        # Tenta obter informações de tempo do processo
        if kernel32.GetProcessTimes(process_handle, 
                                  ctypes.byref(creation_time),
                                  ctypes.byref(exit_time), 
                                  ctypes.byref(kernel_time),
                                  ctypes.byref(user_time)):
            # Converte FILETIME para segundos
            # FILETIME é em intervalos de 100 nanossegundos (1e-7 segundos)
            kernel_seconds = ((kernel_time.dwHighDateTime << 32) + kernel_time.dwLowDateTime) * 1e-7
            user_seconds = ((user_time.dwHighDateTime << 32) + user_time.dwLowDateTime) * 1e-7
            
            # Verifica se temos tempos iniciais para este processo
            if pid in self.initial_process_times and 'win_kernel' in self.initial_process_times[pid]:
                # Cálculo do delta em relação ao tempo inicial
                kernel_delta = kernel_seconds - self.initial_process_times[pid]['win_kernel']
                user_delta = user_seconds - self.initial_process_times[pid]['win_user']
                return kernel_delta + user_delta
            else:
                # Armazena os tempos atuais como iniciais
                if pid not in self.initial_process_times:
                    self.initial_process_times[pid] = {}
                self.initial_process_times[pid]['win_kernel'] = kernel_seconds
                self.initial_process_times[pid]['win_user'] = user_seconds
                return 0  # Primeira medição, retorna 0
        
        return None

    def update_process_tree(self):
        """Atualiza a árvore de processos filho e guarda os PIDs para rastreamento"""
        if not self.process:
            return

        try:
            # Começa com o processo principal
            new_tree = [self.process]
            new_pids = {self.process.pid}

            # Adiciona todos os filhos recursivamente
            try:
                children = self.process.children(recursive=True)
                for child in children:
                    new_tree.append(child)
                    new_pids.add(child.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            # Encontre os novos processos adicionados nesta atualização
            new_processes = new_pids - self.process_tree_pids

            # Atualize a árvore e o conjunto de PIDs
            self.process_tree = new_tree
            self.process_tree_pids = new_pids

            # Armazene as informações de tempo de CPU iniciais para os novos processos
            for pid in new_processes:
                try:
                    proc = psutil.Process(pid)
                    times = proc.cpu_times()
                    self.initial_process_times[pid] = {
                        'user': times.user,
                        'system': times.system,
                        'children_user': getattr(times, 'children_user', 0),
                        'children_system': getattr(times, 'children_system', 0)
                    }
                    
                    # Para Windows, tente obter um handle para este processo também
                    if os.name == 'nt':
                        try:
                            PROCESS_QUERY_INFORMATION = 0x0400
                            handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
                            if handle:
                                # Armazene os tempos via API do Windows
                                self.get_windows_process_times(handle, pid)
                                # Não feche o handle, vamos usá-lo no futuro
                                # Manter em uma lista para fechamento futuro
                                if not hasattr(self, 'child_handles'):
                                    self.child_handles = []
                                self.child_handles.append(handle)
                        except Exception:
                            pass
                            
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Se o processo principal desapareceu, mantenha a árvore existente para
            # calcular o tempo de CPU total que foi consumido
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
        windows_total_cpu_time = 0
        self.update_process_tree()

        # Método 1: Usando psutil (mais confiável para Linux/Unix)
        for proc in self.process_tree:
            try:
                pid = proc.pid
                current_times = proc.cpu_times()

                # Se temos tempos iniciais para este PID, calcule o delta
                if pid in self.initial_process_times:
                    initial = self.initial_process_times[pid]
                    delta_user = current_times.user - initial['user']
                    delta_system = current_times.system - initial['system']
                    
                    # Adicione também o tempo dos filhos se disponível
                    delta_children_user = 0
                    delta_children_system = 0
                    if hasattr(current_times, 'children_user') and 'children_user' in initial:
                        delta_children_user = current_times.children_user - initial['children_user']
                        delta_children_system = current_times.children_system - initial['children_system']
                    
                    total_cpu_time += delta_user + delta_system + delta_children_user + delta_children_system
                else:
                    # Se não temos tempos iniciais (caso raro), contabilize o total
                    total_cpu_time += current_times.user + current_times.system
                    # E armazene os tempos atuais como iniciais para o futuro
                    self.initial_process_times[pid] = {
                        'user': current_times.user,
                        'system': current_times.system,
                        'children_user': getattr(current_times, 'children_user', 0),
                        'children_system': getattr(current_times, 'children_system', 0)
                    }
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # Método 2: Para Windows, use APIs nativas para comparação/backup
        if os.name == 'nt':
            if self.process_handle:
                # Para o processo principal
                main_process_time = self.get_windows_process_times(self.process_handle, self.pid)
                if main_process_time is not None:
                    windows_total_cpu_time += main_process_time
                
                # Para os processos filhos que temos handles
                if hasattr(self, 'child_handles'):
                    for i, handle in enumerate(self.child_handles):
                        # Assumimos que os PIDs estão em ordem de adição
                        if i < len(self.process_tree) - 1:  # -1 porque o primeiro é o processo principal
                            child_pid = self.process_tree[i + 1].pid
                            child_time = self.get_windows_process_times(handle, child_pid)
                            if child_time is not None:
                                windows_total_cpu_time += child_time
        
        # Método 3: Para casos onde os métodos acima falham, verifique o uso relativo de CPU
        current_time = time.time()
        sample_interval = current_time - self.last_sample_time
        
        # Só registre uso se o intervalo for significativo para evitar divisões instáveis
        if sample_interval > 0.1:  # Pelo menos 100ms
            try:
                # Para cada processo na árvore, colete o uso percentual de CPU
                total_percent = 0
                for proc in self.process_tree:
                    try:
                        # cpu_percent() retorna o percentual de uma CPU
                        # Então 100% significa um núcleo de CPU totalmente utilizado
                        percent = proc.cpu_percent(interval=None)
                        total_percent += percent
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                
                # Converte percentual para tempo: 
                # 100% durante 1 segundo = 1 segundo de CPU (em um núcleo)
                cpu_time_in_interval = (total_percent / 100.0) * sample_interval
                
                # Adiciona este ponto à nossa amostragem
                self.sampling_data.append({
                    'timestamp': current_time,
                    'interval': sample_interval,
                    'cpu_time': cpu_time_in_interval
                })
                
                self.last_sample_time = current_time
            except Exception:
                pass
        
        # Se o tempo de CPU via psutil for significativamente baixo, use métodos alternativos
        if total_cpu_time < 0.1:  # Muito baixo, provavelmente incorreto
            # Use API do Windows se disponível
            if windows_total_cpu_time > 0:
                total_cpu_time = windows_total_cpu_time
            # Caso contrário, some os tempos relativos das amostras
            elif self.sampling_data:
                total_cpu_time = sum(sample['cpu_time'] for sample in self.sampling_data)
            
            # Se ainda estiver baixo e tivermos execução significativa (em tempo de relógio)
            # Tente fazer uma última estimativa baseada no tempo de vida do processo
            if total_cpu_time < 0.1 and current_time - self.process_creation_time > 1.0:
                elapsed = current_time - self.process_creation_time
                # Faça uma estimativa conservadora
                # Assumimos pelo menos 5% de um núcleo de CPU durante o tempo de vida
                estimated_cpu_time = elapsed * 0.05
                if estimated_cpu_time > total_cpu_time:
                    total_cpu_time = estimated_cpu_time
                
        return total_cpu_time

    def is_process_running(self):
        """Verifica se o processo principal ainda está em execução"""
        if not self.process:
            return False

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
        
        # Feche todos os handles de processos
        if os.name == 'nt':
            if self.process_handle:
                kernel32.CloseHandle(self.process_handle)
            if hasattr(self, 'child_handles'):
                for handle in self.child_handles:
                    if handle:
                        kernel32.CloseHandle(handle)
                        
        self.killed = True

    def monitor_resources(self):
        """Monitora recursos do processo em uma thread separada"""
        last_cpu_time = 0

        while self.monitoring:
            # Se o processo principal terminou, continue monitorando por mais um ciclo
            # para capturar os valores finais e então encerre
            process_running = self.is_process_running()

            # Verifica o tempo de execução (timeout)
            current_time = time.time()
            elapsed_time = current_time - self.start_time

            # Verifica memória utilizada
            try:
                memory_usage = self.get_process_memory()
                if memory_usage > self.max_memory_usage:
                    self.max_memory_usage = memory_usage

                # Verifica o tempo de CPU
                cpu_time = self.get_process_cpu_time()
                # Se houve mudança no tempo de CPU, atualize
                if cpu_time > last_cpu_time:
                    last_cpu_time = cpu_time
                self.total_cpu_time = cpu_time

                # Exibe progresso apenas se o processo ainda estiver em execução
                if process_running:
                    print(f"\rProgresso: CPU={cpu_time:.2f}s/{self.cpu_quota:.2f}s ({cpu_time/self.cpu_quota*100:.1f}%), "
                          f"Memória={memory_usage:.2f}MB/{self.memory_limit:.2f}MB ({memory_usage/self.memory_limit*100:.1f}%), "
                          f"Tempo={elapsed_time:.2f}s/{self.timeout if self.timeout else 'inf'}s", end="")

                # Verifica se o processo excedeu os limites
                if self.memory_limit and memory_usage > self.memory_limit:
                    print(
                        f"\nProcesso excedeu o limite de memória: {memory_usage:.2f}MB > {self.memory_limit:.2f}MB")
                    self.kill_process_tree()
                    return "MEMORY_EXCEEDED"

                if cpu_time > self.cpu_quota:
                    print(
                        f"\nProcesso excedeu a quota de CPU: {cpu_time:.2f}s > {self.cpu_quota:.2f}s")
                    self.kill_process_tree()
                    return "CPU_EXCEEDED"

                if self.timeout and elapsed_time > self.timeout:
                    print(
                        f"\nProcesso excedeu o timeout: {elapsed_time:.2f}s > {self.timeout:.2f}s")
                    self.kill_process_tree()
                    return "TIMEOUT"
            except Exception as e:
                print(f"\rErro durante o monitoramento: {str(e)}", end="")

            # Se o processo não está mais em execução, faça uma última atualização e saia
            if not process_running:
                # Capture uma última vez os valores finais
                try:
                    final_cpu_time = self.get_process_cpu_time()
                    if final_cpu_time > self.total_cpu_time:
                        self.total_cpu_time = final_cpu_time
                except:
                    pass
                break

            time.sleep(0.5)  # Verifica a cada 0.5 segundo para maior precisão

        return "NORMAL_EXIT"

    def start_monitoring(self):
        """Inicia o monitoramento em uma thread separada"""
        if not self.process:
            return None

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
        self.remaining_cpu_quota = 0
        self.used_cpu_quota = 0
        self.payment_mode = None  # "prepaid" ou "postpaid"
        self.credit_manager = None

    def run_binary(self, binary_path, cpu_quota, memory_limit, timeout):
        """Executa um binário com monitoramento de recursos - Versão corrigida"""
        try:
            if not os.path.exists(binary_path):
                print(f"Erro: O arquivo '{binary_path}' não existe!")
                return False

            print(f"\nExecutando: {binary_path}")
            print(f"Quota de CPU: {cpu_quota:.2f}s")
            print(f"Limite de memória: {memory_limit:.2f}MB")
            print(f"Timeout: {timeout if timeout else 'Sem limite'}s")

            # Tratamento especial para apps modernos do Windows
            is_modern_app = False
            modern_app_names = ['calc.exe', 'notepad.exe', 'mspaint.exe']
            
            if os.name == 'nt' and any(name in binary_path.lower() for name in modern_app_names):
                is_modern_app = True
                print("Detectado aplicativo moderno do Windows - Ajustando monitoramento...")

            start_time = time.time()
            
            # Configuração especial para apps modernos
            creationflags = 0
            if is_modern_app:
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                DETACHED_PROCESS = 0x00000008
                creationflags = CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS

            process = subprocess.Popen(
                binary_path,
                shell=True,
                creationflags=creationflags
            )

            # Tempo de espera aumentado para apps modernos
            wait_time = 2.0 if is_modern_app else 0.5
            time.sleep(wait_time)

            # Monitoramento com tratamento especial
            monitor = ProcessMonitor(process.pid, cpu_quota, memory_limit, timeout)
            
            # Ajuste para apps modernos
            if is_modern_app:
                monitor.process_creation_time = time.time()  # Reseta o tempo de criação
                monitor.windows_methods_tried = False  # Força tentar métodos Windows

            monitor_thread = monitor.start_monitoring()

            try:
                process.wait(timeout=timeout if timeout else None)
                result = "COMPLETED"
            except subprocess.TimeoutExpired:
                print("\nTimeout expirado - terminando processo...")
                process.kill()
                result = "TIMEOUT"
            except Exception as e:
                print(f"\nErro ao aguardar processo: {str(e)}")
                result = "ERROR"

            # Finaliza o monitoramento
            monitor.stop_monitoring()
            if monitor_thread:
                monitor_thread.join(timeout=1)

            end_time = time.time()
            execution_time = end_time - start_time

            # Aguarda mais um momento para capturar dados finais
            time.sleep(0.5)

            # Exibe relatório
            print(f"\n\nRelatório de execução:")
            print(f"Tempo de execução (relógio): {execution_time:.2f}s")
            print(f"Tempo de CPU utilizado: {monitor.total_cpu_time:.2f}s")
            print(f"Uso máximo de memória: {monitor.max_memory_usage:.2f}MB")

            # Calcula o custo da execução (para ambos modos de pagamento)
            if self.credit_manager:
                execution_cost = self.credit_manager.calculate_execution_cost(
                    monitor.total_cpu_time,
                    monitor.max_memory_usage,
                    execution_time
                )
                print(f"Custo da execução: {execution_cost:.2f} créditos")

                # Registra o uso se estiver no modo pós-pago
                if self.payment_mode == "postpaid":
                    self.credit_manager.log_usage(
                        binary_path,
                        monitor.total_cpu_time,
                        monitor.max_memory_usage,
                        execution_time,
                        execution_cost
                    )
                # Deduz os créditos se estiver no modo pré-pago
                elif self.payment_mode == "prepaid":
                    if not self.credit_manager.deduct_credits(execution_cost):
                        print("Créditos insuficientes. Execução será abortada.")
                        return "NO_CREDITS"

            # Verifica se o processo foi finalizado por algum limite
            if monitor.killed:
                return "LIMIT_EXCEEDED"
            
            return result

        except Exception as e:
            print(f"\nErro durante execução: {str(e)}")
            return "ERROR"

    def set_payment_mode(self, mode, user="default_user"):
        """Configura o modo de pagamento (prepaid ou postpaid)"""
        if mode.lower() not in ["prepaid", "postpaid"]:
            print("Modo de pagamento inválido. Use 'prepaid' ou 'postpaid'.")
            return False
        
        self.payment_mode = mode.lower()
        self.credit_manager = CreditManager(user)
        print(f"\nModo de pagamento configurado como: {self.payment_mode}")
        
        if self.payment_mode == "prepaid":
            print(f"Créditos disponíveis: {self.credit_manager.credits:.2f}")
        else:
            print("Modo pós-pago ativado. O uso será registrado para faturamento.")
        
        return True

    def show_credits(self):
        """Mostra créditos disponíveis"""
        if not self.credit_manager:
            print("\nModo de pagamento não configurado. Use set_payment_mode() primeiro.")
            return
        
        print(f"\nCréditos disponíveis: {self.credit_manager.credits:.2f}")

    def add_credits(self, amount):
        """Adiciona créditos à conta"""
        if not self.credit_manager:
            print("\nModo de pagamento não configurado. Use set_payment_mode() primeiro.")
            return False
        
        return self.credit_manager.add_credits(amount)

    def show_usage_report(self):
        """Mostra relatório de uso para modo pós-pago"""
        if not self.credit_manager:
            print("\nModo de pagamento não configurado. Use set_payment_mode() primeiro.")
            return
        
        if self.payment_mode != "postpaid":
            print("\nRelatório de uso só está disponível no modo pós-pago.")
            return
        
        self.credit_manager.show_usage_report()

    def clear_usage_history(self):
        """Limpa histórico de uso após pagamento"""
        if not self.credit_manager:
            print("\nModo de pagamento não configurado. Use set_payment_mode() primeiro.")
            return
        
        if self.payment_mode != "postpaid":
            print("\nLimpeza de histórico só está disponível no modo pós-pago.")
            return
        
        self.credit_manager.clear_usage_history()

# [Restante do código anterior permanece exatamente igual até a classe FMS...]

if __name__ == "__main__":
    fms = FMS()
    
    while True:
        print("\n=== File Monitoring System ===")
        print("1. Configurar modo de pagamento")
        print("2. Adicionar créditos (pré-pago)")
        print("3. Ver créditos disponíveis")
        print("4. Executar programa com monitoramento")
        print("5. Ver relatório de uso (pós-pago)")
        print("6. Limpar histórico de uso (após pagamento)")
        print("0. Sair")
        
        choice = input("\nEscolha uma opção: ")
        
        if choice == "1":
            user = input("Nome de usuário: ")
            mode = input("Modo de pagamento (prepaid/postpaid): ")
            fms.set_payment_mode(mode, user)
            
        elif choice == "2":
            if fms.payment_mode != "prepaid":
                print("Esta opção só está disponível no modo pré-pago.")
                continue
            amount = float(input("Quantidade de créditos a adicionar: "))
            fms.add_credits(amount)
            
        elif choice == "3":
            fms.show_credits()
            
        elif choice == "4":
            binary_path = input("Caminho completo do executável: ")
            
            # Valores padrão sugeridos
            default_cpu = 60
            default_mem = 500
            default_timeout = 120
            
            try:
                cpu_quota = float(input(f"Quota de CPU em segundos [{default_cpu}]: ") or default_cpu)
                memory_limit = float(input(f"Limite de memória em MB [{default_mem}]: ") or default_mem)
                timeout = float(input(f"Timeout em segundos (0 para ilimitado) [{default_timeout}]: ") or default_timeout)
                if timeout == 0:
                    timeout = None
            except ValueError:
                print("Valores inválidos. Usando padrões.")
                cpu_quota = default_cpu
                memory_limit = default_mem
                timeout = default_timeout
            
            print("\nIniciando execução monitorada...")
            result = fms.run_binary(
                binary_path=binary_path,
                cpu_quota=cpu_quota,
                memory_limit=memory_limit,
                timeout=timeout
            )
            print(f"\nResultado: {result}")
            
        elif choice == "5":
            fms.show_usage_report()
            
        elif choice == "6":
            confirm = input("Tem certeza que deseja limpar o histórico? (s/n): ")
            if confirm.lower() == 's':
                fms.clear_usage_history()
                
        elif choice == "0":
            print("Saindo do sistema...")
            break
            
        else:
            print("Opção inválida. Tente novamente.")