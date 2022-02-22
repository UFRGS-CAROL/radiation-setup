import errno
import telnetlib
import threading
import time
import logging
import socket

from dut_logging import DUTLogging, MessageType
from error_codes import ErrorCodes
from reboot_machine import reboot_machine, turn_machine_on


class Machine(threading.Thread):
    """ Machine Thread
    do not change the machine constants unless you
    really know what you are doing, most of the constants
    describes the behavior of HARD reboot execution
    """
    __TIME_MIN_REBOOT_THRESHOLD = 3
    __TIME_MAX_REBOOT_THRESHOLD = 10
    __REBOOT_AGAIN_INTERVAL_AFTER_BOOT_PROBLEM = 3600

    def __init__(self,
                 ip: str, receiving_port: int, diff_reboot: float, hostname: str, power_switch_ip: str,
                 power_switch_port: int,
                 power_switch_model: str, logger_name: str, boot_problem_max_delta: float,
                 power_cycle_sleep_time: float, dut_log_path: str,
                 sdc_data_size: int, max_timeout_time:int, username: str, dut_passwd: str, dut_app_path: str, exec_code: str,
                 app_args: str, *args, **kwargs):
        """ Initialize a new thread that represents a setup machine
        :param ip: Machine' IP
        :param receiving_port: port fro receiving messages from the DUT
        :param diff_reboot: Difference threshold to wait between the connections of the device
        :param hostname: Hostname of the device
        :param power_switch_ip: IP address of the power switch that the device is connected
        :param power_switch_port: Power switch port that the device is connected
        :param power_switch_model: Model (type/brand) of the power switch
        :param logger_name: Main logger name to store the logging information
        :param boot_problem_max_delta: Delta time necessary to take some action after boot problem
        :param power_cycle_sleep_time: difference between OFF and ON when rebooting
        :param dut_log_path: directory to store the logs for the test
        :paran sdc_data_size: size of the SDC message
        :param max_timeout_time: maximum waiting time for messages
        :param username: DUT username
        :param dut_passwd: DUT password
        :param dut_app_path: path where is the application and input files
        :param exec_code: name the application running
        :param app_args: arguments for the application running
        # TODO: CHeck if the approach will use this way of setting the parameters
        """
        self.__ip = ip
        self.__diff_reboot = diff_reboot
        self.__hostname = hostname
        self.__switch_ip = power_switch_ip
        self.__switch_port = power_switch_port
        self.__switch_model = power_switch_model
        self.__logger_name = logger_name
        self.__boot_problem_max_delta = boot_problem_max_delta
        self.__reboot_sleep_time = power_cycle_sleep_time
        self.__timestamp = time.time()
        self.__logger = logging.getLogger(self.__logger_name)
        self.__stop_event = threading.Event()
        self.__reboot_status = ErrorCodes.SUCCESS
        self.__dut_log_path = dut_log_path
        self.__receiving_port = receiving_port
        self.__dut_log_obj = None
        self.__sdc_data_size = sdc_data_size
        self.__messages_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.__max_timeout_time = max_timeout_time
        self.__username = username
        self.__dut_passwd = dut_passwd
        self.__dut_app_path = dut_app_path
        self.__exec_code = exec_code
        self.__app_args = app_args
        self.__messages_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.__messages_socket.bind((self.get_self_ip_address(), self.__receiving_port))
        self.__messages_socket.settimeout(self.__max_timeout_time)

        super(Machine, self).__init__(*args, **kwargs)

    def run(self):
        """ Run execution of thread
        """
        # lower and upper threshold for reboot interval
        lower_threshold = self.__TIME_MIN_REBOOT_THRESHOLD * self.__diff_reboot
        upper_threshold = self.__TIME_MAX_REBOOT_THRESHOLD * self.__diff_reboot
        # mandatory: It must start the machine on
        turn_machine_on(address=self.__ip, switch_model=self.__switch_model, switch_port=self.__switch_port,
                        switch_ip=self.__switch_ip, logger_name=self.__logger_name)
        # TODO: Refactor this code to manage the new setup
        #       The following behaviors must be present here:
        #           - Create a log obj of DUTLogging in the first connection from a device
        #           - At the destruction of the class or stop of the server the Machine MUST close all log files
        while self.__stop_event.is_set():
            try:
                data, addr = self.__messages_socket.recvfrom(self.__sdc_data_size)
            except socket.timeout:
                start_app_ret = self.start_app()
                if start_app_ret == ErrorCodes.REBOOTING:
                    # TODO log as syscrash
                    self.__reboot_this_machine()
                else:
                    num_tries = 0
                    while start_app_ret != ErrorCodes.SUCCESS and num_tries < 4:
                        start_app_ret = self.start_app()
                        num_tries += 1
                    if start_app_ret != ErrorCodes.SUCCESS:
                        self.__reboot_this_machine()
                        # TODO log as syscrash
                    # TODO log as appcrash
            else:

                self.__process_message(data)

    def get_self_ip_address(self):

        ip_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            ip_socket.connect((self.__ip, 1027))
        except socket.error:
            return None

        return ip_socket.getsockname()[0]

    def start_app(self):

        try:
            tn = telnetlib.Telnet(self.__ip, timeout=30)
            tn.read_until(b'ogin: ', timeout=30)
            tn.write(self.__username.encode('ascii') + b'\n')
            l = tn.read_very_eager()
            if self.__dut_passwd != "":
                tn.read_until(b'assword: ', timeout=30)
                tn.write( self.__dut_passwd.encode('ascii') + b'\n')
            tn.read_until(b'$ ', timeout=30)

            cmd_line_pkill = 'pkill ' + self.__exec_code + '\r\n'
            tn.write(cmd_line_pkill.encode('ascii'))
            l = tn.read_very_eager()

            cmd_line_run = 'nohup ' + self.__dut_app_path + self.__exec_code + ' ' + self.get_self_ip_address() + ' ' + str( self.__receiving_port) + ' ' + \
                           self.__app_args + ' &\r\n'

            tn.write(cmd_line_run.encode('ascii'))
            l = tn.read_very_eager()
            time.sleep(0.1)
            tn.close()

        except OSError as e:
            if e.errno == errno.EHOSTUNREACH:
                return ErrorCodes.REBOOTING
            return ErrorCodes.WAITING_FOR_POSSIBLE_BOOT
        except EOFError as e:
            return ErrorCodes.WAITING_FOR_POSSIBLE_BOOT
        return ErrorCodes.SUCCESS

    def join(self, *args, **kwargs) -> None:
        """ Stop the main function before join the thread
        :param args: to be passed to the base class
        :param kwargs: to be passed to the base class
        """
        self.__stop_event.set()
        super(Machine, self).join(*args, **kwargs)

    def __process_message(self, message) -> None:
        """ Process the last message in the queue
        All messages have 1024B
        The message is organized in the following way
        | 1 byte MessageType | 1023 message content |
        - MessageType is a number 0 to 255, the following types are defined
            CREATE_HEADER = 0
            ITERATION_TIME = 1
            ERROR_DETAIL = 2
            INFO_DETAIL = 3
            SDC_END = 4
            TOO_MANY_ERRORS_PER_ITERATION = 5
            TOO_MANY_INFOS_PER_ITERATION = 6
            NORMAL_END = 7
            SAME_ERROR_LAST_ITERATION = 8
        :return:
        """
        message_type = MessageType(int(message[0]))
        message_content = message[1:]
        if message_type == MessageType.CREATE_HEADER:
            self.__dut_log_obj = DUTLogging(log_dir=self.__dut_log_path,
                                            test_name="None", test_header=message_content,
                                            hostname=self.__hostname, ecc_config="OFF")
            raise NotImplementedError

        elif message_type == MessageType.ITERATION_TIME:
            raise NotImplementedError
        elif message_type == MessageType.ERROR_DETAIL:
            raise NotImplementedError
        elif message_type == MessageType.INFO_DETAIL:
            raise NotImplementedError
        elif message_type == MessageType.SDC_END:
            raise NotImplementedError
        elif message_type == MessageType.TOO_MANY_ERRORS_PER_ITERATION:
            raise NotImplementedError
        elif message_type == MessageType.TOO_MANY_INFOS_PER_ITERATION:
            raise NotImplementedError
        elif message_type == MessageType.NORMAL_END:
            raise NotImplementedError
        elif message_type == MessageType.SAME_ERROR_LAST_ITERATION:
            raise NotImplementedError

    def __log(self, kind: ErrorCodes) -> None:
        """ Log some Machine behavior
        :param kind: Error code to be logged
        """
        if kind == ErrorCodes.REBOOTING:
            if self.__reboot_status == ErrorCodes.SUCCESS:
                reboot_msg = f"Rebooted IP:{self.__ip}"
            else:
                reboot_msg = f"Reboot failed for IP:{self.__ip}"
            reboot_msg += f" HOSTNAME:{self.__hostname} STATUS:{self.__reboot_status}"
            reboot_msg += f" PORT_NUMBER: {self.__switch_port} SWITCH_IP: {self.__switch_ip}"
            self.__logger.info(reboot_msg)
        elif kind == ErrorCodes.WAITING_BOOT_PROBLEM:
            reboot_msg = f"Waiting {self.__boot_problem_max_delta}s due boot problem IP:{self.__ip} "
            reboot_msg += f"HOSTNAME:{self.__hostname}"
            self.__logger.info(reboot_msg)
        elif kind == ErrorCodes.WAITING_FOR_POSSIBLE_BOOT:
            self.__logger.debug(
                f"Waiting for a possible boot in the future from IP:{self.__ip} HOSTNAME:{self.__hostname}")
        elif kind == ErrorCodes.BOOT_PROBLEM:
            reboot_msg = f"Boot Problem IP:{self.__ip} HOSTNAME:{self.__hostname}. "
            reboot_msg += f"The thread will wait for a connection for {self.__boot_problem_max_delta}s"
            self.__logger.error(reboot_msg)
        elif kind == ErrorCodes.MAX_SEQ_REBOOT_REACHED:
            self.__logger.error(
                f"Maximum number of reboots allowed reached for IP:{self.__ip} HOSTNAME:{self.__hostname}")
        elif kind == ErrorCodes.TURN_ON:
            self.__logger.info(f"Turning ON IP:{self.__ip} HOSTNAME:{self.__hostname} STATUS:{self.__reboot_status}")

    def __reboot_this_machine(self) -> float:
        """ reboot the device based on reboot_machine module
        :return reboot_status
        """
        last_reboot_timestamp = time.time()
        # Reboot machine in another thread
        off_status, on_status = reboot_machine(address=self.__ip,
                                               switch_model=self.__switch_model,
                                               switch_port=self.__switch_port,
                                               switch_ip=self.__switch_ip,
                                               rebooting_sleep=self.__reboot_sleep_time,
                                               logger_name=self.__logger_name)
        self.__reboot_status = ErrorCodes.SUCCESS
        if off_status != ErrorCodes.SUCCESS:
            self.__reboot_status = off_status
        if on_status != ErrorCodes.SUCCESS:
            self.__reboot_status = on_status
        return last_reboot_timestamp


if __name__ == '__main__':
    # FOR DEBUG ONLY
    # from RebootMachine import RebootMachine

    print("CREATING THE MACHINE")
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
        datefmt='%d-%m-%y %H:%M:%S',
        filename="unit_test_log_Machine.log",
        filemode='w'
    )
    machine = Machine(
        ip="127.0.0.1",
        receiving_port=10002,
        diff_reboot=1,
        hostname="test",
        power_switch_ip="127.0.0.1",
        power_switch_port=1,
        power_switch_model="lindy",
        logger_name="MACHINE_LOG",
        boot_problem_max_delta=10,
        power_cycle_sleep_time=2,
        dut_log_path="/tmp",
        sdc_data_size=5,
        max_timeout_time=10,
        username="carol",
        dut_passwd="qwerty0",
        dut_app_path="/home/carol/",
        exec_code="test",
        app_args=" 1"
    )

    print("EXECUTING THE MACHINE")
    machine.start()
    print(f"SLEEPING THE MACHINE FOR {100}s")
    time.sleep(100)

    print("JOINING THE MACHINE")
    machine.join()

    print("RAGE AGAINST THE MACHINE")
