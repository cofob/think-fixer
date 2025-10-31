import json
import re
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

# The upstream API you are proxying to
UPSTREAM_URL = "https://api.glhf.chat"

# A dictionary to hold the httpx client during the app's lifespan
client_store = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the lifespan of the httpx.AsyncClient.
    It starts the client on app startup and closes it on shutdown.
    """
    client = httpx.AsyncClient(base_url=UPSTREAM_URL)
    client_store["client"] = client
    print("FastAPI app started, httpx client created.")
    yield
    await client.aclose()
    print("FastAPI app shutting down, httpx client closed.")
    client_store.clear()


app = FastAPI(lifespan=lifespan)


def _get_client() -> httpx.AsyncClient:
    """Helper function to retrieve the httpx client from the store."""
    return client_store.get("client")


def _get_proxy_headers(request: Request) -> dict:
    """
    Filters request headers to safely pass them to the upstream API.
    Excludes headers that are set by httpx or are hop-by-hop.
    """
    exclude_headers = {
        "host",
        "content-length",
        "content-type",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
    headers = {}
    for key, value in request.headers.items():
        if key.lower() not in exclude_headers:
            headers[key] = value
    return headers


async def _streaming_content_modifier(
    upstream_response: httpx.Response,
) -> AsyncGenerator[bytes, None]:
    """
    An async generator that processes the streaming response from the upstream API.
    It maintains a state (is_thinking) to move content between <think>...</think>
    tags from the 'content' field to the 'reasoning_content' field.
    """
    is_thinking = False

    # Process the stream line by line
    async for line in upstream_response.aiter_lines():
        if not line.startswith("data:"):
            # Pass through empty lines or other non-data lines
            if line:
                yield (line + "\n").encode("utf-8")
            continue

        if line == "data: [DONE]":
            yield (line + "\n\n").encode("utf-8")
            break

        json_str = line[5:].strip()
        try:
            chunk_json = json.loads(json_str)
        except json.JSONDecodeError:
            print(f"Warning: Failed to decode JSON from chunk: {json_str}")
            continue

        # Extract the delta content
        try:
            delta = chunk_json.get("choices", [{}])[0].get("delta", {})
            content = delta.get("content")
        except (IndexError, AttributeError):
            # Not a standard chunk, pass it through
            yield (line + "\n\n").encode("utf-8")
            continue

        if content is None:
            # Not a content chunk (e.g., first chunk with role), pass it through
            yield (line + "\n\n").encode("utf-8")
            continue

        # We have content, now we process it with the state machine
        new_content = ""
        new_reasoning = ""
        current_chunk_content = content

        while current_chunk_content:
            if is_thinking:
                # We are currently inside a <think> block
                end_tag_index = current_chunk_content.find("</think>")
                if end_tag_index != -1:
                    # End tag found
                    new_reasoning += current_chunk_content[:end_tag_index]
                    current_chunk_content = current_chunk_content[
                        end_tag_index + len("</think>") :
                    ]
                    is_thinking = False
                else:
                    # Still thinking, consume the rest of the chunk as reasoning
                    new_reasoning += current_chunk_content
                    current_chunk_content = ""
            else:
                # We are currently outside a <think> block
                start_tag_index = current_chunk_content.find("<think>")
                if start_tag_index != -1:
                    # Start tag found
                    new_content += current_chunk_content[:start_tag_index]
                    current_chunk_content = current_chunk_content[
                        start_tag_index + len("<think>") :
                    ]
                    is_thinking = True
                else:
                    # No tag, consume the rest of the chunk as normal content
                    new_content += current_chunk_content
                    current_chunk_content = ""

        # Reconstruct and yield the modified chunk

        # Only add reasoning_content if it's not empty
        if new_reasoning:
            delta["reasoning_content"] = new_reasoning
            # If we added reasoning, but no new content, set content to null
            if not new_content:
                delta["content"] = None
            else:
                delta["content"] = new_content
        else:
            # No reasoning content, just pass through the new_content
            delta["content"] = new_content
            # Ensure the key exists and is null if empty, matching example
            delta["reasoning_content"] = None

        new_json_str = json.dumps(chunk_json)
        yield f"data: {new_json_str}\n\n".encode("utf-8")


@app.post("/v1/chat/completions")
async def proxy_chat_completions(request: Request):
    """
    Handles the /v1/chat/completions endpoint.
    Modifies the request to set reasoning_effort='high'.
    Modifies the response to parse <think> tags into reasoning_content.
    """
    client = _get_client()
    if not client:
        return JSONResponse({"error": "Service unavailable"}, status_code=503)

    try:
        # Modify request body
        body = await request.json()
        body["reasoning_effort"] = "high"
        is_stream = body.get("stream", False)

        headers = _get_proxy_headers(request)

        # Build the upstream request
        upstream_request = client.build_request(
            method="POST",
            url=request.url.path,
            json=body,
            headers=headers,
            params=request.query_params,
            timeout=300.0,  # Increase timeout for LLM requests
        )

        # Send request and handle response based on stream type
        upstream_response = await client.send(upstream_request, stream=is_stream)

        # Ensure upstream errors are passed to the client
        upstream_response.raise_for_status()

        if is_stream:
            # Return a streaming response, applying our modifier
            return StreamingResponse(
                _streaming_content_modifier(upstream_response),
                status_code=upstream_response.status_code,
                media_type=upstream_response.headers.get("content-type"),
            )
        else:
            # Non-streaming: parse the full response
            response_json = upstream_response.json()

            try:
                # Modify the non-streaming response
                content = response_json["choices"][0]["message"]["content"]

                # Find all <think> blocks and join their content
                matches = re.findall(r"<think>(.*?)</think>", content, re.DOTALL)
                reasoning_content = "\n".join(matches).strip()

                # Remove all <think> blocks from the main content
                new_content = re.sub(
                    r"<think>(.*?)</think>", "", content, flags=re.DOTALL
                ).strip()

                # Set reasoning_content, or None if it's empty
                response_json["choices"][0]["message"]["reasoning_content"] = (
                    reasoning_content if reasoning_content else None
                )

                # If we produced reasoning content AND the new content is empty, set content to null.
                if reasoning_content and not new_content:
                    response_json["choices"][0]["message"]["content"] = None
                else:
                    response_json["choices"][0]["message"]["content"] = new_content

            except (KeyError, IndexError, TypeError) as e:
                print(f"Warning: Could not parse non-streaming response: {e}")
                # Return as-is if structure is unexpected
                pass

            return JSONResponse(
                content=response_json,
                status_code=upstream_response.status_code,
            )

    except httpx.HTTPStatusError as e:
        # Pass upstream API errors (like 401, 404, 500) back to the client
        return JSONResponse(
            content=e.response.json()
            if e.response.content
            else {"detail": e.response.reason_phrase},
            status_code=e.response.status_code,
        )
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return JSONResponse({"error": "Internal server error"}, status_code=500)


@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_all_other_routes(request: Request, full_path: str):
    """
    A catch-all proxy for all other routes.
    It streams the request and response bodies as-is.
    """
    client = _get_client()
    if not client:
        return JSONResponse({"error": "Service unavailable"}, status_code=503)

    try:
        headers = _get_proxy_headers(request)

        # Build the upstream request
        upstream_request = client.build_request(
            method=request.method,
            url=f"/{full_path}",
            params=request.query_params,
            headers=headers,
            content=request.stream(),  # Stream the request body
            timeout=300.0,
        )

        # Send the request and stream the response
        upstream_response = await client.send(upstream_request, stream=True)

        return StreamingResponse(
            upstream_response.aiter_bytes(),
            status_code=upstream_response.status_code,
            headers=upstream_response.headers,
        )

    except httpx.HTTPStatusError as e:
        return JSONResponse(
            content=e.response.json()
            if e.response.content
            else {"detail": e.response.reason_phrase},
            status_code=e.response.status_code,
        )
    except Exception as e:
        print(f"An unexpected error occurred on catch-all proxy: {e}")
        return JSONResponse({"error": "Internal server error"}, status_code=500)


if __name__ == "__main__":
    import uvicorn

    # To run: uvicorn main:app --host 0.0.0.0 --port 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
