import logging
import os

# Basic log formatting
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"

# Ensure logs directory exists for future use (optional)
os.makedirs("logs", exist_ok=True)

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
)

# Function for modules
def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
