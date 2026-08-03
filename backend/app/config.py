"""
Configuration Management
Loads configuration from .env file in project root directory
"""

import os

from dotenv import load_dotenv

# Load .env file from project root
# Path: MiroFish/.env (relative to backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # If no .env in root, try to load environment variables (for production)
    load_dotenv(override=True)


class Config:
    """Flask configuration class"""

    # Flask configuration
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    # Debug is opt-in: the dev server binds every interface by default, and the
    # Werkzeug debugger would otherwise be reachable from the local network.
    DEBUG = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    MIROFISH_START_DRAINED = (
        os.environ.get('MIROFISH_START_DRAINED', 'false').lower() == 'true'
    )

    # JSON configuration - disable ASCII escaping to display Chinese directly (not as \uXXXX)
    JSON_AS_ASCII = False

    # LLM configuration (unified OpenAI format)
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'http://localhost:11434/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'qwen2.5:32b')
    MIROFISH_JSON_MODEL = os.environ.get('MIROFISH_JSON_MODEL')
    MIROFISH_NER_MODEL = os.environ.get('MIROFISH_NER_MODEL')
    MIROFISH_REPORT_MODEL = os.environ.get('MIROFISH_REPORT_MODEL')
    MIROFISH_REPAIR_MODEL = os.environ.get('MIROFISH_REPAIR_MODEL')
    MIROFISH_AUDIENCE_FAILURE_THRESHOLD = float(
        os.environ.get('MIROFISH_AUDIENCE_FAILURE_THRESHOLD', '0.30')
    )
    MIROFISH_AUDIENCE_CALL_TIMEOUT_SECONDS = float(
        os.environ.get('MIROFISH_AUDIENCE_CALL_TIMEOUT_SECONDS', '45')
    )
    MIROFISH_AUDIENCE_RUN_TIMEOUT_SECONDS = float(
        os.environ.get('MIROFISH_AUDIENCE_RUN_TIMEOUT_SECONDS', '210')
    )
    MIROFISH_AUDIENCE_MAX_WORKERS = int(
        os.environ.get('MIROFISH_AUDIENCE_MAX_WORKERS', '10')
    )
    MIROFISH_AUDIENCE_MAX_TERMINAL_RECORDS = int(
        os.environ.get('MIROFISH_AUDIENCE_MAX_TERMINAL_RECORDS', '64')
    )

    # Neo4j configuration
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
    NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'mirofish')

    # Embedding configuration
    EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'nomic-embed-text')
    EMBEDDING_BASE_URL = os.environ.get('EMBEDDING_BASE_URL', 'http://localhost:11434')

    # File upload configuration
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}

    # Text processing configuration
    DEFAULT_CHUNK_SIZE = 500  # Default chunk size
    DEFAULT_CHUNK_OVERLAP = 50  # Default overlap size

    # OASIS simulation configuration
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')

    # OASIS platform available actions configuration
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]

    # Report Agent configuration
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))

    @classmethod
    def validate(cls):
        """Validate required configuration"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY not configured (set to any non-empty value, e.g. 'ollama')")
        if not cls.NEO4J_URI:
            errors.append("NEO4J_URI not configured")
        if not cls.NEO4J_PASSWORD:
            errors.append("NEO4J_PASSWORD not configured")
        return errors
