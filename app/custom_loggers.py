from .logger import Logger

class GenerationLogger(Logger):
    channel = "generation"

class VerificationLogger(Logger):
    channel = "verification"

# Można dodać kolejne klasy loggerów w razie potrzeby
