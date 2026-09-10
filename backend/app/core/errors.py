"""Public errors contain fixed messages, never submitted values or credentials."""


class ServiceError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(code)
