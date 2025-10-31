# Synthetic Thinking Proxy

A FastAPI reverse proxy that processes LLM API responses containing reasoning tags and converts them into structured `reasoning_content` fields. This proxy specifically handles `` tags in both streaming and non-streaming responses from the upstream API.

## Features

- ✅ **Reverse Proxy**: Forwards requests to `https://api.glhf.chat`
- ✅ **Reasoning Tag Processing**: Converts ``tags into structured`reasoning_content` fields
- ✅ **Streaming Support**: Handles Server-Sent Events (SSE) streaming responses with real-time tag processing
- ✅ **Non-Streaming Support**: Processes complete JSON responses with reasoning tag extraction
- ✅ **Automatic Configuration**: Sets `reasoning_effort="high"` for all chat completion requests
- ✅ **Header Filtering**: Safely proxies request headers while excluding hop-by-hop headers
- ✅ **Error Handling**: Comprehensive error handling with upstream error propagation
- ✅ **Async/Await**: Fully asynchronous implementation using FastAPI and httpx

## How It Works

The proxy intercepts chat completion responses and processes reasoning tags:

1. **Tag Detection**: Identifies `` (end) reasoning tags
2. **Content Extraction**: Moves content between tags to `reasoning_content` field
3. **Content Cleaning**: Removes reasoning tags from the main `content` field
4. **State Processing**: Maintains state across streaming chunks for multi-chunk reasoning
5. **Response Reconstruction**: Yields properly structured JSON responses

## Example Transformation

### Before (Raw API Response)

```json
{
  "choices": [
    {
      "delta": {
        "content": " The answer is 42."
      }
    }
  ]
}
```

### After (Proxy Response)

```json
{
  "choices": [
    {
      "delta": {
        "content": " The answer is 42.",
        "reasoning_content": "Let me think about this problem..."
      }
    }
  ]
}
```

## Installation

### Prerequisites

- Python 3.13 or higher
- pip or uv package manager
- Docker (optional, for containerized deployment)

### Docker Deployment

1. Build the Docker image:

```bash
docker build -t synthetic-thinking-proxy .
```

2. Run the container:

```bash
docker run -p 8000:8000 synthetic-thinking-proxy
```

The proxy will be available at `http://localhost:8000`

### Local Development

1. Clone the repository:

```bash
git clone <repository-url>
cd synthetic-thinking
```

2. Install dependencies:

```bash
# Using pip
pip install -e .

# Or using uv
uv sync
```

3. Run the server:

```bash
python main.py
```

The proxy will start on `http://localhost:8000`
The proxy will be available at `http://localhost:8000`

### Docker Usage Examples

For Docker deployments, you can test the proxy using curl against localhost:8000:

```bash
# Chat completions with reasoning processing
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hf:MiniMaxAI/MiniMax-M2",
    "messages": [
      {
        "role": "user",
        "content": "What is 2+2?"
      }
    ]
  }'

# Transparent proxy for other endpoints
curl -X GET http://localhost:8000/v1/models \
  -H "Authorization: Bearer YOUR_API_KEY"
```

## Usage

### Chat Completions with Reasoning Processing

The `/v1/chat/completions` endpoint automatically processes reasoning tags and sets `reasoning_effort="high"`:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hf:MiniMaxAI/MiniMax-M2",
    "messages": [
      {
        "role": "user",
        "content": "What is 2+2?"
      }
    ]
  }'
```

**Note**: You don't need to specify `reasoning_effort` - the proxy automatically adds it.

### Streaming Responses

For real-time processing of reasoning tags in streaming responses:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hf:MiniMaxAI/MiniMax-M2",
    "stream": true,
    "messages": [
      {
        "role": "user",
        "content": "Explain quantum computing briefly"
      }
    ]
  }'
```

### Transparent Proxy for Other Endpoints

All other endpoints are forwarded transparently to the upstream API:

```bash
# Models endpoint
curl -X GET http://localhost:8000/v1/models \
  -H "Authorization: Bearer YOUR_API_KEY"

# Any other path
curl -X GET http://localhost:8000/v1/embeddings \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello world", "model": "text-embedding-ada-002"}'
```

## API Endpoints

### `/v1/chat/completions` (POST)

- **Purpose**: Chat completion endpoint with reasoning tag processing
- **Automatic Features**:
  - Sets `reasoning_effort="high"` if not specified
  - Processes `` tags in responses
  - Supports both streaming and non-streaming modes
- **Request Body**: Standard OpenAI-compatible chat completions format
- **Response**: Standard format with added `reasoning_content` field when reasoning tags are present

### `/{full_path:path}` (ALL METHODS)

- **Purpose**: Universal proxy for all other endpoints
- **Behavior**: Transparent forwarding to upstream API without modification
- **Methods**: GET, POST, PUT, DELETE, PATCH, OPTIONS, HEAD
- **Usage**: Drop-in replacement for direct API calls

## Configuration

### Hardcoded Configuration

The upstream API URL is hardcoded in `main.py`:

```python
UPSTREAM_URL = "https://api.glhf.chat"
```

To modify the upstream URL, edit this constant in the source code.

### Environment Variables

Create a `.env` file for any additional configuration:

```bash
# Optional: Custom timeout (default: 300.0 seconds)
REQUEST_TIMEOUT=300.0

# Optional: Custom host (default: 0.0.0.0)
HOST=0.0.0.0

# Optional: Custom port (default: 8000)
PORT=8000
```

## Project Structure

```
synthetic-thinking/
├── main.py                 # FastAPI application with proxy logic
├── pyproject.toml          # Python project configuration and dependencies
├── Dockerfile              # Docker container configuration
├── .env                    # Environment variables (create this)
├── .env.example            # Environment variables template
├── .gitignore              # Git ignore rules
├── .python-version         # Python version specification
├── README.md               # This file
└── uv.lock                 # UV package manager lock file
```

## Dependencies

- **FastAPI**: Modern, fast web framework for building APIs
- **httpx**: Async HTTP client for proxying requests
- **uvicorn[standard]**: ASGI server for running FastAPI applications

See `pyproject.toml` for exact version specifications.

## Development

### Running in Development Mode

```bash
# Install dependencies
uv sync

# Run with auto-reload
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Key Components

1. **Lifespan Management** (`lifespan` function): Manages httpx client lifecycle
2. **Request Proxying** (`_get_proxy_headers`): Filters and forwards request headers
3. **Streaming Processing** (`_streaming_content_modifier`): Real-time reasoning tag processing
4. **Non-Streaming Processing**: Complete response reasoning tag extraction
5. **Universal Proxy** (`proxy_all_other_routes`): Catch-all endpoint proxy

### Logging

The application includes comprehensive logging:

- Client lifecycle events (startup/shutdown)
- JSON parsing warnings for malformed chunks
- Error tracking and exception handling

## Error Handling

- **HTTP Errors**: Upstream API errors are propagated to clients with appropriate status codes
- **JSON Parsing**: Malformed streaming chunks are logged and skipped
- **Service Unavailability**: Returns 503 status when HTTP client is unavailable
- **Timeout**: Configurable timeout (300s default) for upstream requests

## License

Add your license information here.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly with both streaming and non-streaming requests
5. Submit a pull request

## Technical Notes

- The proxy maintains state across streaming chunks to handle reasoning tags that span multiple SSE events
- Header filtering excludes hop-by-hop headers for safe proxying
- Both streaming and non-streaming responses are processed identically in terms of reasoning tag handling
- The proxy is fully asynchronous and can handle multiple concurrent requests
