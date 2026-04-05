"""
Configuration Management
Loads configuration from .env file at project root
"""

import os
from dotenv import load_dotenv

# Load .env from project root
# Path: MiroFish/.env (relative to backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # Fallback to environment variables (production)
    load_dotenv(override=True)


class Config:
    """Flask configuration"""

    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'

    # JSON - disable ASCII escape for non-Latin scripts (Persian, Chinese, etc.)
    JSON_AS_ASCII = False

    # LLM configuration (OpenAI-compatible format, used for report generation & chat)
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')
    ALLOW_DEGRADED_MODE = os.environ.get('ALLOW_DEGRADED_MODE', 'false').lower() == 'true'
    QENGIN_WIZARD_MODEL = os.environ.get('QENGIN_WIZARD_MODEL', LLM_MODEL_NAME)
    QENGIN_WIZARD_MAX_TOKENS = int(os.environ.get('QENGIN_WIZARD_MAX_TOKENS', '900'))
    QENGIN_WIZARD_MAX_RETRIES = int(os.environ.get('QENGIN_WIZARD_MAX_RETRIES', '2'))
    QENGIN_WIZARD_CACHE_TTL_SECONDS = int(os.environ.get('QENGIN_WIZARD_CACHE_TTL_SECONDS', '3600'))

    # Neo4j configuration (Graphiti backend)
    NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://qadr-graph-neo4j:7687')
    NEO4J_USERNAME = os.environ.get('NEO4J_USERNAME', 'neo4j')
    NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', '')

    # Graphiti LLM (for entity extraction - uses abliterated model for uncensored analysis)
    GRAPHITI_LLM_MODEL = os.environ.get('GRAPHITI_LLM_MODEL', 'local-qwen3.5-abliterated')
    GRAPHITI_LLM_BASE_URL = os.environ.get('GRAPHITI_LLM_BASE_URL', 'http://qadr-ai-gateway-litellm:4000/v1')
    GRAPHITI_LLM_API_KEY = os.environ.get('GRAPHITI_LLM_API_KEY', os.environ.get('LLM_API_KEY', ''))

    # Graphiti Embedder (for semantic search)
    GRAPHITI_EMBEDDING_MODEL = os.environ.get('GRAPHITI_EMBEDDING_MODEL', 'qwen2.5:7b')
    GRAPHITI_EMBEDDING_BASE_URL = os.environ.get('GRAPHITI_EMBEDDING_BASE_URL', 'http://qadr-local-llm-ollama:11434')
    GRAPHITI_EMBEDDING_DIM = int(os.environ.get('GRAPHITI_EMBEDDING_DIM', '3584'))

    # QADR Graph API (optional, for OSINT enrichment)
    QADR_GRAPH_API_URL = os.environ.get('QADR_GRAPH_API_URL', 'http://qadr-graph-api:8088')
    QADR_GRAPH_API_KEY = os.environ.get('QADR_GRAPH_API_KEY', '')

    # Legacy Zep (kept for backward compatibility, no longer used)
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY', '')

    # File upload
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}

    # Text processing
    DEFAULT_CHUNK_SIZE = 500
    DEFAULT_CHUNK_OVERLAP = 50

    # OASIS simulation
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')

    # OASIS platform actions
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]

    # Report Agent
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))

    @classmethod
    def validate(cls):
        """Validate required configuration"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY not configured")
        if not cls.NEO4J_PASSWORD and not cls.ALLOW_DEGRADED_MODE:
            errors.append("NEO4J_PASSWORD not configured")
        return errors

    @classmethod
    def degraded_reasons(cls):
        reasons = []
        if not cls.NEO4J_PASSWORD:
            reasons.append("NEO4J_PASSWORD not configured - graph memory and full simulation capabilities will be degraded")
        return reasons

