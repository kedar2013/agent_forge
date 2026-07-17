import os
import uuid
from typing import Any

from app.generated_files_auth import sign_filename
from app.tool_registry.base import ConfigDrivenTool

# Matches the directory app/main.py mounts at /generated-images, regardless
# of the process's current working directory.
DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "generated_images")

DEFAULT_PROMPT_TEMPLATE = (
    "A simple, clear, colorful educational diagram/illustration for a school "
    "textbook: {description}. Clean lines, labeled if relevant, friendly and "
    "age-appropriate style, plain background."
)


class ImageGenTool(ConfigDrivenTool):
    """Real Gemini image-generation call — writes a PNG to disk, returns a
    relative URL for the agent to embed in its answer as markdown.

    `config` shape:
        {
          "model": "gemini-2.5-flash-image",
          "output_dir": "generated_images",           # relative to backend/
          "prompt_template": "... {description} ..."   # optional override
        }
    """

    def __init__(self, *, name: str, description: str, input_schema: dict, config: dict) -> None:
        super().__init__(name=name, description=description, input_schema=input_schema)
        self._config = config

    async def run_async(self, *, args: dict[str, Any], tool_context) -> Any:
        from google import genai

        config = self._config
        model = config.get("model", "gemini-2.5-flash-image")
        output_dir = config.get("output_dir", DEFAULT_OUTPUT_DIR)
        prompt_template = config.get("prompt_template", DEFAULT_PROMPT_TEMPLATE)

        prompt = prompt_template.format(description=args["description"])

        client = genai.Client()
        response = client.models.generate_content(model=model, contents=prompt)

        for part in response.candidates[0].content.parts:
            if part.inline_data:
                os.makedirs(output_dir, exist_ok=True)
                filename = f"{uuid.uuid4().hex}.png"
                with open(os.path.join(output_dir, filename), "wb") as f:
                    f.write(part.inline_data.data)
                token = sign_filename("generated-images", filename)
                return {"image_url": f"/generated-images/{filename}?token={token}"}

        return {"error": "The model did not return an image for this description."}
