# Gemini Code Assistant Context

## Project Overview

This project is a Python-based price tracking system for Blu-ray and 4K Blu-ray movies on CDON.fi. It uses a hybrid scraping approach, combining the power of Playwright for dynamic, JavaScript-heavy listing pages with the efficiency of `requests` and `BeautifulSoup` for parsing individual product pages.

The system is designed to be deployed with Docker, providing a web dashboard to monitor prices, a background service to check for price drops, and a one-time crawler to populate the database.

### Key Technologies

*   **Backend:** Python 3.11, Flask
*   **Scraping:** Playwright, Requests, BeautifulSoup
*   **Database:** SQLite
*   **Deployment:** Docker, Docker Compose
*   **Frontend:** HTML, CSS, JavaScript (served by Flask)

### Architecture

The application is composed of several key Python scripts:

*   `monitor.py`: The main entry point for the application. It can be run in three modes:
    *   `web`: Starts the Flask web server, providing the user-facing dashboard.
    *   `monitor`: Runs the price monitoring service, which periodically checks for price updates on items in the watchlist.
    *   `crawl`: Executes a one-time crawl of the CDON.fi website to populate the database with movie listings.
*   `cdon_scraper_v2.py`: The core scraper orchestrator. It uses `listing_crawler.py` to get product URLs and then `product_parser.py` to extract details from each product page.
*   `listing_crawler.py`: A Playwright-based crawler responsible for navigating category pages and extracting product URLs. This is necessary for pages that load content dynamically with JavaScript.
*   `product_parser.py`: A lightweight parser that uses `requests` and `BeautifulSoup` to parse the HTML of individual product pages. This is more efficient than using a full browser for every product.
*   `requirements.txt`: Lists the Python dependencies for the project.
*   `Dockerfile`: Defines the Docker image for the application, including the installation of Python, Playwright, and other dependencies.
*   `docker-compose.yml`: Defines the services for the application, including the web server, monitor, and crawler. It also defines the networks and volumes used by the application.
*   `scripts/`: Contains helper scripts for building, running, and managing the application.

## Building and Running

The project is designed to be run with Docker and Docker Compose. The following scripts are provided in the `scripts/` directory to simplify the process.

### Building the Docker Image

To build the Docker image, run the following command:

```bash
./scripts/build.sh
```

This script will automatically detect whether you have `podman` or `docker` installed and use the appropriate tool.

### Running in Development Mode (macOS with Podman)

For development on macOS, the `run-dev.sh` script is provided. It uses `podman-compose` to start the `web` and `monitor` services.

```bash
./scripts/run-dev.sh
```

The web dashboard will be available at [http://localhost:8080](http://localhost:8080).

### Running in Production Mode (Linux with Docker)

For production deployments on a Linux VPS, the `run-prod.sh` script is provided. It uses `docker-compose` to start the services in detached mode.

```bash
./scripts/run-prod.sh
```

### Running Commands Manually

You can also run commands manually using `docker-compose` or `podman-compose`.

*   **Start all services:** `docker-compose up -d`
*   **Stop all services:** `docker-compose down`
*   **Run the crawler:** `docker-compose run --rm crawler`
*   **View logs:** `docker-compose logs -f`

## Development Conventions

*   **Configuration:** The application is configured using environment variables, which are defined in the `.env` file. A `.env.example` file is provided as a template.
*   **Database:** The SQLite database is stored in the `data/` directory. This directory is mounted as a volume in the Docker containers to persist data.
*   **Security:** The Docker container runs as a non-root user for improved security.
*   **Code Style:** The Python code is formatted using standard conventions and includes type hints for better readability and maintainability.
*   **Modularity:** The code is organized into modules with specific responsibilities, making it easier to understand and maintain.
