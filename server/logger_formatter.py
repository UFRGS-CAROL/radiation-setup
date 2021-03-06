import logging


class ColoredFormatter(logging.Formatter):
    BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)

    # The background is set with 40 plus the number of the color, and the foreground with 30

    # These are the sequences need to get colored output
    RESET_SEQ = "\033[0m"
    COLOR_SEQ = "\033[1;%dm"
    BOLD_SEQ = "\033[1m"

    COLORS = {
        'WARNING': YELLOW,
        'INFO': WHITE,
        'DEBUG': BLUE,
        'CRITICAL': YELLOW,
        'ERROR': RED
    }

    def __init__(self, msg, use_color=True):
        logging.Formatter.__init__(self, msg, "%d-%m-%y %H:%M:%S")
        self.use_color = use_color

    def format(self, record):
        level_name = record.levelname
        if self.use_color and level_name in self.COLORS:
            level_name_color = self.COLOR_SEQ % (30 + self.COLORS[level_name]) + level_name + self.RESET_SEQ
            record.levelname = level_name_color
        return logging.Formatter.format(self, record)

    @staticmethod
    def formatter_message(message, use_color=True):
        if use_color:
            message = message.replace("$RESET", ColoredFormatter.RESET_SEQ).replace("$BOLD", ColoredFormatter.BOLD_SEQ)
        else:
            message = message.replace("$RESET", "").replace("$BOLD", "")
        return message


# Custom logger class with multiple destinations
class ColoredLogger(logging.Logger):
    FORMAT = "[$BOLD%(name)-17s$RESET][%(levelname)-7s] %(message)s ($BOLD%(filename)s$RESET:%(lineno)d) %(asctime)s"
    COLOR_FORMAT = ColoredFormatter.formatter_message(FORMAT)

    def __init__(self, name):
        logging.Logger.__init__(self, name, logging.DEBUG)

        color_formatter = ColoredFormatter(self.COLOR_FORMAT)

        console = logging.StreamHandler()
        console.setFormatter(color_formatter)
        self.addHandler(console)


def logging_setup(logger_name: str, log_file: str) -> logging.Logger:
    """Logging setup
    :return: logger object
    """
    # create logger
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    # create file handler which logs even debug messages
    fh = logging.FileHandler(log_file, mode='a')
    fh.setLevel(logging.INFO)
    # create formatter and add it to the handlers
    file_formatter = logging.Formatter(fmt='%(asctime)s %(name)s %(levelname)s %(message)s %(filename)s:%(lineno)d',
                                       datefmt='%d-%m-%y %H:%M:%S')

    # add the handlers to the logger
    fh.setFormatter(file_formatter)
    logger.addHandler(fh)

    # create console handler with a higher log level for console
    console = ColoredLogger(logger_name)
    # noinspection PyTypeChecker
    logger.addHandler(console)
    return logger
