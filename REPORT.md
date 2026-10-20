# REPORT.md

## IncuBrix Script and Voiceover to B-roll Video Engine

**Candidate:** Alahadu Sheik Hussain\
**Problem statement:** PS3 --- Script and Voiceover to B-roll Video
Engine\
**Repository:** https://github.com/arsahadu/incubrix-broll-engine\

------------------------------------------------------------------------

## 1. What I Build?

The goal was to build a practical tool that turns a written script or
uploaded narration into a video assembled from relevant B-roll footage.
I wanted the workflow to be accessible through a simple Streamlit
interface while keeping the processing logic behind a FastAPI backend. I
also wanted the project to run locally and in containers, rather than
depending on a collection of manually started services.

The main flow is: accept a script or audio upload, plan scenes around
the narration, search for suitable footage, download selected clips, and
render a video in the requested aspect ratio. The application also
exposes job status and progress so that longer work can run in the
background instead of keeping the user waiting on a single blocking
request.

I treated this as an engineering project rather than only a
video-generation demo. That meant working on input validation, API
structure, duplicate-request handling, health checks, containerization,
and a record of the footage selected for a job.

## 2. Approaches considered and why I chose this design

### Scene planning and footage selection

A simple keyword-only search is easy to implement, but it can return
footage that contains a word from the script without actually matching
the idea being narrated. I therefore used a scene-planning step together
with semantic ranking using `sentence-transformers/all-MiniLM-L6-v2`.
The intent is to compare the meaning of a scene description with
available footage metadata, while retaining keyword signals where
useful.

For scene planning, the project uses local Ollama with `llama3.2:3b`.
Keeping this step local avoids sending every script to a paid hosted
language-model API and makes the prototype easier to run without a model
API key. The trade-off is that model availability, response quality, and
local compute requirements can affect startup time and results.

### Audio processing and narration

The project supports an audio-upload workflow and uses `faster-whisper`
for local transcription. Text-based input follows a narration-generation
path. The codebase includes audio probing and transcript-based timing
allocation so scenes can be placed along the narration timeline.

The current timing approach is a useful starting point, but proportional
allocation from transcript words is not the same as precise forced
alignment. Sentence and phrase boundaries, pauses, and changes in
speaking pace still need a more rigorous end-to-end evaluation. The
local narration path also needs to be verified in the deployment
environment, where macOS speech tools are not available; a portable TTS
engine is therefore used or configured for container environments.

### API and user interface

I chose FastAPI for the backend because it provides typed request
validation and an automatically generated OpenAPI contract. Streamlit
provides a quick, usable interface for trying the workflow without
building a separate JavaScript frontend. Docker Compose packages the API
and UI as separate services, making local startup more repeatable.

The API currently includes job creation, job-status polling, health and
readiness endpoints, and an audio-upload route. Idempotency-key handling
is present for duplicate job submissions. The OpenAPI endpoint reported
version **3.1.0** with **9 paths** during local verification, and the
contract was exported to `openapi.yaml`.

## 3. What works so far

The following items are implemented in the current codebase or were
directly observed during development:

-   FastAPI backend and Streamlit frontend are both running locally
    through Docker Compose.
-   The API exposes `/health`, `/ready`, job creation, job-status, and
    audio-upload routes.
-   Text and audio input workflows are present in the application.
-   Audio probing and local transcription support are implemented in the
    audio-processing service.
-   Scene planning and semantic footage ranking are implemented.
-   Pixabay is used as the intended stock-footage search source, with
    download validation and cleanup safeguards in the downloader.
-   Video rendering and aspect-ratio configuration are implemented in
    the renderer.
-   The API reports OpenAPI **3.1.0** and **9 paths**; `openapi.yaml`
    has been generated from the running API.
-   Docker images for the API and frontend built successfully, and both
    containers started locally.
-   A Railway deployment was attempted. The frontend initially crashed
    because Streamlit received the literal string `$PORT` instead of a
    numeric port. This is a deployment-configuration issue identified
    from the logs; the public deployment should not be described as
    working until a successful redeployment is confirmed.

These are implementation and startup observations, not proof that every
assessment must-have passes. The full workflow still needs a saved
end-to-end evidence pack.

## 4. What does not work yet, or remains unverified

The most important remaining work is validation across complete
input-to-video runs. The project should not be considered fully verified
until these items have been tested and documented:

1.  **Audio and timing:** Test MP3, WAV, and M4A inputs, including the
    10-minute boundary. Compare scene timings with the transcript and
    check that the full narration is covered without gaps or drift.
2.  **Semantic relevance and repetition:** Run a varied test pack, watch
    each scene, rate relevance from 1 to 5, and verify that no clip is
    reused within the same video. These scores have not yet been
    collected.
3.  **Licensing and attribution:** Audit the source, licence terms,
    attribution details, and source link for every selected clip.
    Confirm commercial-use suitability and check for watermarks. Do not
    infer that every downloaded clip is cleared merely because it came
    from a stock-footage provider.
4.  **Render integrity:** Validate all requested aspect ratios and check
    output resolution, frame rate, pixel format, black frames, frozen
    frames, and audio synchronisation.
5.  **Safety and difficult prompts:** Test named people, brand names,
    sensitive subjects, abstract concepts, and ambiguous terms.
    Dedicated policy checks and a saved hard-case result set are still
    needed.
6.  **Resilience:** Simulate a footage-provider failure during a job,
    corrupted downloads, and concurrent submissions. Confirm that the
    job either succeeds using a fallback or returns a clear, documented
    failure state.

## 5. Measured numbers and cost per unit

I have deliberately not filled gaps with estimated performance figures.
At the time of writing, the following are the measured or observed
values available:

  -----------------------------------------------------------------------
  Measure                 Current result          Evidence / status
  ----------------------- ----------------------- -----------------------
  OpenAPI version         3.1.0                   Queried from the
                                                  running local API

  API path count          9                       Queried from
                                                  `/openapi.json`

  Local Docker image      API and frontend images Docker Compose build
  build                   built                   output

  Local service startup   API and frontend        Docker Compose output
                          containers started      

  Average scene relevance Not measured            Human ratings across
                                                  the test pack are
                                                  pending

  End-to-end success rate Not measured            Requires completed runs
                                                  across varied inputs

  Render time per minute  Not measured            Requires timestamped
  of video                                        render runs

  Cold-start /            Not measured            Railway deployment must
  first-request latency                           be stable first

  Cost per minute of      Not calculated          Requires actual usage,
  generated video                                 billing, and runtime
                                                  records

  Peak memory / CPU use   Not measured            Requires a recorded
                                                  resource benchmark

  Number of concurrent    Not measured            Requires concurrency
  jobs supported                                  testing
  -----------------------------------------------------------------------

The project uses local/open-source components for scene planning,
semantic ranking, transcription, and rendering where configured. Pixabay
is used for footage search. Railway hosting may incur charges depending
on the plan and usage, and API-related charges must be checked against
actual account usage. Therefore, I cannot responsibly claim a final
project cost of zero until billing records have been checked.

For the final submission, I would record wall-clock render time, input
duration, output duration, number of scenes, number of unique clips,
human relevance scores, failure/fallback status, and actual paid-service
charges for each test run. Cost per output minute can then be calculated
from recorded charges divided by the total minutes of generated output,
with free local compute reported separately.

## 6. What I would do next

My next priority is to get a stable public deployment and capture a
clean end-to-end demo. After that, I would run the required varied-input
test pack and keep the outputs, manifests, logs, and video timestamps as
evidence. I would add automated checks for audio coverage, repeated clip
identifiers, render metadata, and black or frozen frames.

I would also improve transcript alignment, make job state durable,
standardize error responses, finish rate limiting, add structured
request/job correlation logs, and make sure the checked-in OpenAPI
contract stays synchronized with the running service. Finally, I would
audit clip licensing and attribution, document the hard
cases---including weaker results---and calculate runtime and cost from
real runs.

The project has a working application structure and a local
containerized startup path. The remaining step is to turn that
foundation into a measured, repeatable, reviewer-ready result. I will
only promote a feature or metric to "passed" after I have evidence that
supports the claim.

------------------------------------------------------------------------

## Evidence to attach before final submission

-   [ ] A successful public Railway URL and reviewer access instructions
-   [ ] An unedited demo video of no more than 8 minutes
-   [ ] A test pack containing varied scripts/audio inputs and generated
    outputs
-   [ ] Per-run manifests with source URLs and licence/attribution
    metadata
-   [ ] Human scene relevance ratings and repeat-clip checks
-   [ ] Render validation logs and timing measurements
-   [ ] Cold-start, resource-use, and cost records
-   [ ] `SOURCES.md` and `AI_USE.md`
-   [ ] A checked-in `openapi.yaml` matching the deployed API
