# IncuBrix Script and Voiceover to B-roll Video Engine

A FastAPI + Streamlit application for turning a written script or
uploaded narration into a B-roll video workflow.

> **Current status:** The FastAPI backend was deployed to Railway, and
> `/health` and `/docs` were confirmed to respond. The Streamlit
> frontend and end-to-end cloud video generation still need to be
> deployed/configured and verified. Do not describe the full application
> as production-ready until a complete video has been generated
> successfully in the deployed environment.

## Features

-   Script-based B-roll job creation.
-   Narration audio upload for MP3, WAV, or M4A, with backend duration
    validation up to 10 minutes.
-   Local speech transcription using `faster-whisper`.
-   Scene planning through a configured Ollama chat endpoint.
-   Stock-footage discovery through Pixabay, with semantic and keyword
    relevance ranking.
-   FFmpeg/FFprobe-based media inspection and rendering.
-   Background job creation and status polling.
-   FastAPI Swagger UI and OpenAPI schema.
-   Docker and Docker Compose setup for local development.

## Architecture
<img width="1376" height="768" alt="Gemini_Generated_Image_cpxs1ucpxs1ucpxs" src="https://github.com/user-attachments/assets/dc071c40-99a0-4814-8b70-a56683f9a7ad" />

## Project structure

``` text
.
├── app/
│   ├── main.py
│   ├── routers/
│   ├── schemas/
│   └── services/
├── frontend/
│   └── app.py
├── outputs/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .dockerignore
└── openapi.yaml
```

## Requirements

-   Python 3.11 for local development (the Docker image uses Python
    3.11)
-   Docker and Docker Compose (recommended)
-   Pixabay API key for footage search
-   A reachable Ollama endpoint/model for the configured scene-planning
    flow
-   FFmpeg and FFprobe with the filters used by the renderer

The first run may download model files for `faster-whisper` and
`sentence-transformers`. Runtime and memory requirements depend on the
input length, model choice, number of scenes, and requested output
formats.

## Configuration

Create `.env` from the example:

``` bash
cp .env.example .env
```

Set the required values:

``` dotenv
PIXABAY_API_KEY=your_pixabay_api_key
OLLAMA_URL=http://host.docker.internal:11434/api/chat
```

Keep real credentials in `.env` or your hosting provider's
secret-variable settings. Never commit `.env` or publish API keys.

**Cloud note:** `host.docker.internal` may let a local Docker container
reach a service running on your host, but it does not point to your Mac
from Railway. For cloud scene planning, configure `OLLAMA_URL` to a
reachable hosted endpoint or provide a supported fallback.

## Run with Docker Compose

From the project root, ensure `.env` is configured, then run:

``` bash
docker compose up --build
```

Open:

-   Streamlit UI: `http://localhost:8501`
-   FastAPI API: `http://localhost:8000`
-   Swagger UI: `http://localhost:8000/docs`
-   Health check: `http://localhost:8000/health`
-   Readiness check: `http://localhost:8000/ready`

Stop the services:

``` bash
docker compose down
```

## Run locally without Docker

Create a virtual environment and install dependencies:

``` bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the API in one terminal:

``` bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Run the UI in another terminal:

``` bash
streamlit run frontend/app.py --server.address 0.0.0.0 --server.port 8501
```

Set `BROLL_API_URL` if the frontend needs a different API address. Its
local default is `http://127.0.0.1:8000`.

## API overview

The API prefix is `/api/v1/broll`.

  ----------------------------------------------------------------------------
  Endpoint                                 Purpose
  ---------------------------------------- -----------------------------------
  `POST /api/v1/broll/jobs`                Create a B-roll job from a JSON
                                           request

  `GET /api/v1/broll/jobs/{job_id}`        Retrieve job status/result
                                           information

  `POST /api/v1/broll/jobs/audio-upload`   Upload narration audio and create a
                                           job

  `GET /health`                            Basic health check

  `GET /ready`                             Readiness check

  `GET /docs`                              Interactive Swagger UI

  `GET /openapi.json`                      Generated OpenAPI schema
  ----------------------------------------------------------------------------

See `/docs` or `openapi.yaml` for exact request and response schemas.
Job creation supports `Idempotency-Key` where configured.

### Example JSON request

``` json
{
  "script": "A short narration about sustainable cities and clean transportation.",
  "aspect_ratios": ["16:9", "9:16"],
  "style": "bright, modern, real-world footage",
  "avoid": ["watermarks", "unrelated footage"],
  "captions": {
    "burn_in": true,
    "srt": true
  }
}
```

Confirm exact options and output fields against the current OpenAPI
schema and running application.

## Railway deployment

The FastAPI service has been deployed to Railway:

-   API base URL:
    `https://incubrix-broll-engine-production-5b9f.up.railway.app`
-   Health check:
    `https://incubrix-broll-engine-production-5b9f.up.railway.app/health`
-   Swagger UI:
    `https://incubrix-broll-engine-production-5b9f.up.railway.app/docs`

The health and documentation endpoints were confirmed to respond during
deployment. The Streamlit UI should be deployed as a separate service
from the same repository with a start command similar to:

``` bash
streamlit run frontend/app.py --server.address 0.0.0.0 --server.port $PORT
```

Set this variable on the frontend service:

``` dotenv
BROLL_API_URL=https://incubrix-broll-engine-production-5b9f.up.railway.app
```

Generate a separate Railway public domain for the frontend. The target
port must match the port Streamlit listens on. Cloud video generation
also requires a valid Pixabay key and a reachable scene-planning
endpoint. Verify the full workflow before sharing a production-ready
demo URL.

## Outputs and storage

Generated videos and intermediate assets are written under the
configured output directory. `outputs/` is excluded from Git because it
may contain large media files. Separate service containers do not
automatically share their local filesystems; ensure output files the UI
needs are accessible to the frontend.

The current job store is in-memory, so job state may be lost when the
service restarts. Treat this as a prototype limitation unless persistent
storage is added.

## Troubleshooting

-   **Root URL returns 404:** This may be expected if the app has no `/`
    route. Try `/health` or `/docs`.
-   **Railway 502/503:** Check deployment logs, the start command, and
    whether the app listens on `0.0.0.0` and the assigned port.
-   **UI cannot reach API:** Confirm `BROLL_API_URL` is set on the
    frontend service and includes the full `https://` base URL.
-   **Scene planning fails in cloud:** Ensure `OLLAMA_URL` points to a
    reachable endpoint; a local address will not normally reach your Mac
    from Railway.
-   **Footage search fails:** Check `PIXABAY_API_KEY` and inspect logs.
    Never paste the key into public issues or commit it.
-   **Subtitle/render errors:** Confirm the deployed FFmpeg build
    includes the filters used by the renderer, such as `subtitles` or
    `drawtext`.
-   **Slow first request:** Model loading or downloading can make the
    first request slower.

## Security and responsible use

-   Store credentials in environment variables or a secret manager;
    never commit real keys.
-   Check each footage source's current license and terms before
    commercial distribution. Preserve source/license details and
    attribution where required.
-   Do not assume every returned asset is automatically cleared for
    every use.
-   Avoid unauthorized realistic depictions of real people, invented
    brand logos, or misleading footage for sensitive topics.
-   Validate uploads and enforce size/duration limits.

## Development status and remaining validation

Before describing this as production-ready, verify or complete:

-   Streamlit frontend deployment and connection to the public API.
-   End-to-end cloud generation from both script and uploaded audio.
-   Output storage/access across the two services.
-   Persistent job state and recovery after restarts.
-   Required FFmpeg filters in the deployed image.
-   Representative test inputs and human relevance scoring.
-   Source/license manifest for generated assets.
-   `REPORT.md`, `SOURCES.md`, and `AI_USE.md` submission documents, if
    not already committed.

## Repository

https://github.com/arsahadu/incubrix-broll-engine

## License

Add the license selected for this project before distributing or reusing
the repository. Until a license file is included, assume the code is not
granted an open-source license by default.
