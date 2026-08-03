"""
MiroFish Backend Entry Point
"""

import os
import sys

# Solve Windows console Chinese character encoding issue: set UTF-8 encoding before all imports
if sys.platform == 'win32':
    # Set environment variable to ensure Python uses UTF-8
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    # Reconfigure standard output stream to UTF-8
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add project root directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.config import Config


def main():
    """Main function"""
    # Validate configuration
    errors = Config.validate()
    if errors:
        print("Configuration errors:")
        for err in errors:
            print(f"  - {err}")
        print("\nPlease check configuration in .env file")
        sys.exit(1)

    # Create application
    app = create_app()

    # Get runtime configuration
    host = os.environ.get('FLASK_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_PORT', 5001))
    debug = Config.DEBUG

    if debug and host not in ('127.0.0.1', 'localhost', '::1'):
        print(
            f"WARNING: FLASK_DEBUG is on while binding {host}. The Werkzeug "
            "debugger executes code from the browser; keep this off any "
            "network you do not control."
        )

    # Start service
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    main()

