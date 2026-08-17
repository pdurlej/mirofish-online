"""
MiroFish Backend - Flask Application Factory
"""

import os
import warnings
from pathlib import Path

# Suppress multiprocessing resource_tracker warnings (from third-party libraries like transformers)
# Must be set before all other imports
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, abort, request, send_from_directory  # noqa: E402
from flask_cors import CORS  # noqa: E402
from werkzeug.exceptions import NotFound  # noqa: E402

from .config import Config  # noqa: E402
from .lifecycle import (  # noqa: E402
    LifecycleState,
    register_default_work_providers,
    register_lifecycle,
)
from .utils.logger import get_logger, setup_logger  # noqa: E402


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
BACKEND_ROUTE_PREFIXES = frozenset({"api", "health", "internal"})


def register_frontend_routes(app: Flask) -> None:
    """Serve the production SPA without masking missing backend routes."""

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def frontend(path: str):
        first_segment = path.partition("/")[0]
        if first_segment in BACKEND_ROUTE_PREFIXES:
            abort(404)

        if path:
            try:
                return send_from_directory(FRONTEND_DIST, path)
            except NotFound:
                if first_segment == "assets" or Path(path).suffix:
                    abort(404)

        index = FRONTEND_DIST / "index.html"
        if not index.is_file():
            abort(404)
        return send_from_directory(FRONTEND_DIST, "index.html")


def create_app(config_class=Config):
    """Flask application factory function"""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Read once: several blocks below depend on it and a test subclass may set it.
    simulation_enabled = bool(app.config.get('MIROFISH_ENABLE_SIMULATION', False))

    # Configure JSON encoding: ensure Chinese displays directly (not as \uXXXX)
    # Flask >= 2.3 uses app.json.ensure_ascii, older versions use JSON_AS_ASCII config
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False

    # Setup logging
    logger = setup_logger('mirofish')

    # Only print startup info in reloader subprocess (avoid printing twice in debug mode)
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process

    if should_log_startup:
        logger.info("=" * 50)
        logger.info("MiroFish-Offline Backend starting...")
        logger.info("=" * 50)

    # Enable CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # --- Initialize Neo4jStorage singleton (DI via app.extensions) ---
    from .storage import Neo4jStorage
    try:
        neo4j_storage = Neo4jStorage()
        app.extensions['neo4j_storage'] = neo4j_storage
        if should_log_startup:
            logger.info("Neo4jStorage initialized (connected to %s)", Config.NEO4J_URI)
    except Exception as e:
        logger.error("Neo4jStorage initialization failed: %s", e)
        # Store None so endpoints can return 503 gracefully
        app.extensions['neo4j_storage'] = None

    from .storage.embedding_service import EmbeddingService
    app.extensions['embedding_service'] = EmbeddingService(max_retries=1, timeout=3)

    lifecycle = LifecycleState(
        start_drained=bool(app.config.get("MIROFISH_START_DRAINED", False))
    )
    register_default_work_providers(lifecycle)
    register_lifecycle(app, lifecycle)

    # Reap simulation subprocesses on shutdown. Pointless when the lane cannot be
    # reached, since nothing will have started one.
    if simulation_enabled:
        from .services.simulation_runner import SimulationRunner
        SimulationRunner.register_cleanup()
        if should_log_startup:
            logger.info("Simulation process cleanup function registered")

    # Request logging middleware
    @app.before_request
    def log_request():
        logger = get_logger('mirofish.request')
        logger.debug(f"Request: {request.method} {request.path}")
        if request.content_type and 'json' in request.content_type:
            if request.path.startswith('/api/audience/'):
                body = request.get_json(silent=True) or {}
                logger.debug(
                    "Request body: %s",
                    {
                        "redacted": True,
                        "keys": sorted(body.keys()) if isinstance(body, dict) else [],
                    },
                )
            else:
                logger.debug(f"Request body: {request.get_json(silent=True)}")

    @app.after_request
    def log_response(response):
        logger = get_logger('mirofish.request')
        logger.debug(f"Response: {response.status_code}")
        return response

    # Register blueprints. The audience lane is the product; the document-graph
    # and simulation lanes are the inherited fork, off unless asked for.
    #
    # Only registration is conditional, not the import. Making the import
    # conditional too was measured and rejected: with camel out of the default
    # install, importing api.simulation costs about 14 ms and pulls in nothing
    # heavy, so the complexity bought nothing.
    from .api import audience_bp, graph_bp, report_bp, simulation_bp
    app.register_blueprint(audience_bp, url_prefix='/api/audience')
    if simulation_enabled:
        app.register_blueprint(graph_bp, url_prefix='/api/graph')
        app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
        app.register_blueprint(report_bp, url_prefix='/api/report')
    elif should_log_startup:
        logger.info(
            "Simulation lane disabled; set MIROFISH_ENABLE_SIMULATION=true to register it"
        )
    register_frontend_routes(app)

    if should_log_startup:
        logger.info("MiroFish-Offline Backend startup complete")

    return app
