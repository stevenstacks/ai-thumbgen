from __future__ import annotations

import base64
from contextlib import ExitStack

import openai
from openai import OpenAI

from ..config import MAX_INPUT_IMAGES
from .base import EditRequest, EditResult, ProviderError


class OpenAIImagesProvider:
    """OpenAI Images API (`/v1/images/edits`), stateless: every call sends the full image set."""

    name = "openai"
    max_input_images = MAX_INPUT_IMAGES

    def __init__(self, api_key: str):
        # SDK retries 429/5xx/connection errors with exponential backoff.
        self.client = OpenAI(api_key=api_key, max_retries=2, timeout=600)

    def edit(self, request: EditRequest) -> EditResult:
        if not request.images:
            raise ProviderError("No input images.")
        if len(request.images) > self.max_input_images:
            raise ProviderError(f"Too many input images ({len(request.images)} > {self.max_input_images}).")
        w, h = request.size
        try:
            with ExitStack() as stack:
                files = [stack.enter_context(open(p, "rb")) for p in request.images]
                # input_fidelity is intentionally omitted: gpt-image-2 does not accept it.
                resp = self.client.images.edit(
                    model=request.model,
                    image=files,
                    prompt=request.prompt,
                    size=f"{w}x{h}",
                    quality=request.quality,
                    output_format="png",
                    n=1,
                )
        except openai.AuthenticationError:
            raise ProviderError("OpenAI rejected the API key (401). Check OPENAI_API_KEY in .env.") from None
        except openai.PermissionDeniedError as e:
            raise ProviderError(
                f"Access denied (403): {e.message}. The model may require organization verification."
            ) from None
        except openai.RateLimitError as e:
            raise ProviderError(f"Rate limited or out of quota (429): {e.message}") from None
        except openai.BadRequestError as e:
            raise ProviderError(f"Request rejected (400): {e.message}") from None
        except openai.APIConnectionError:
            raise ProviderError("Could not reach the OpenAI API (network error).") from None
        except openai.APIStatusError as e:
            raise ProviderError(f"OpenAI API error ({e.status_code}): {e.message}") from None

        if not resp.data or not resp.data[0].b64_json:
            raise ProviderError("OpenAI returned no image data.")
        usage = resp.usage.model_dump() if getattr(resp, "usage", None) else None
        return EditResult(
            image_bytes=base64.b64decode(resp.data[0].b64_json),
            usage=usage,
            meta={"created": getattr(resp, "created", None)},
        )
