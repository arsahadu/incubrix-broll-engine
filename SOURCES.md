# SOURCES.md

## Stock footage

-   **Pixabay API** --- used to search for stock footage. Record the
    source page and applicable licence/attribution details for every
    clip in each final video.\
    https://pixabay.com/

## AI models

-   **Ollama --- Llama 3.2 3B** --- local scene planning.
-   **sentence-transformers/all-MiniLM-L6-v2** --- semantic ranking of
    footage descriptions.
-   **faster-whisper** --- local audio transcription.

## Application and media tools

-   **FastAPI** --- backend API.
-   **Streamlit** --- user interface.
-   **FFmpeg / FFprobe** --- audio/video processing and validation.
-   **Docker / Docker Compose** --- local containerized deployment.

## Notes

-   Model and tool use should be confirmed against the final deployed
    configuration.
-   Keep the source URL, clip identifier, licence/attribution
    information, and download date for each asset used.
-   No individual clip should be described as commercially cleared until
    its applicable licence has been checked.
