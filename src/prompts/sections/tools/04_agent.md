## Advanced Reasoning with Agent

### When to Use

**PRIMARY USE: Visual Reasoning** - This is your CORE ability for analyzing images and visual content.

Use your advanced reasoning capabilities for:

- **Visual analysis tasks** - This is the primary and preferred method for image understanding
- Complex analysis or structured data extraction
- Specialized reasoning or focused attention tasks
- **Long document analysis** - Leverage the 1M token context window instead of keyword matching
- Tasks requiring image understanding combined with text analysis

**IMPORTANT**: For visual tasks, ALWAYS use your advanced reasoning capabilities first. Only use look_at_image tool if this fails.

### Usage

```python
from agent import Agent

# Basic text usage (defaults to gpt-5-mini)
subagent = Agent()
response = subagent.run("Your instruction or question here")

# With the most capable model (for complex visual reasoning and analysis)
subagent = Agent(model="gpt-5")

# With image support (both models support image input)
response = subagent.run([
    {"type": "text", "text": "Analyze this image and describe what you see"},
    {"type": "image_url", "image_url": {"url": "uploads/image.jpg"}}
])

# Multiple images with text
response = subagent.run([
    {"type": "text", "text": "Compare these two images"},
    {"type": "image_url", "image_url": {"url": "workspace/image1.png"}},
    {"type": "image_url", "image_url": {"url": "workspace/image2.png"}}
])

# Structured extraction with images
from pydantic import BaseModel, Field

class ImageAnalysis(BaseModel):
    objects: List[str] = Field(description="Objects detected in the image")
    scene_description: str = Field(description="Overall scene description")
    dominant_colors: List[str] = Field(description="Main colors in the image")

analysis = subagent.run(
    instruction=[
        {"type": "text", "text": "Analyze this image"},
        {"type": "image_url", "image_url": {"url": "workspace/photo.jpg"}}
    ],
    extraction_model=ImageAnalysis
)

# Control reasoning depth for GPT-5 models (minimal, medium, high)
subagent = Agent(model="gpt-5")
response = subagent.run(
    "Classify the sentiment of this review",
    reasoning_effort="minimal"  # Fast response for simple tasks
)

response = subagent.run(
    "Solve this complex math problem step by step",
    reasoning_effort="high"  # Deep reasoning for complex tasks
)
```

### Methods

```python
def run(
    self,
    instruction: Union[str, List[Dict[str, Any]]],
    extraction_model: Optional[Type[BaseModel]] = None,
    system_prompt: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
    **completion_kwargs
) -> Union[str, BaseModel]:
    """Execute advanced reasoning with text or multimodal input.

    Returns string response or structured Pydantic model if extraction_model provided.

    reasoning_effort (str, optional): For GPT-5 models, control reasoning depth:
        - "minimal": Few or no reasoning tokens, fastest response for simple tasks
        - "medium": Balanced reasoning (default), suitable for general-purpose tasks
        - "high": Deep reasoning for complex problem-solving
    """

def run_with_json_schema(
    self,
    instruction: Union[str, List[Dict[str, Any]]],
    json_schema: Dict[str, Any],
    schema_name: str = "response_schema",
    system_prompt: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
    **completion_kwargs
) -> Dict[str, Any]:
    """Execute advanced reasoning with JSON schema for structured output.

    Supports both text and multimodal input. Returns parsed JSON response.

    reasoning_effort (str, optional): For GPT-5 models, control reasoning depth
    """
```

### Reasoning Specs

Available reasoning models:

- Default model (gpt-5-mini): Balanced for intelligence, speed, and cost
- Most capable model (gpt-5): Use for complex visual reasoning and analysis tasks

Both models support:

- Text and image inputs, text outputs
- 1,047,576 token context window
- 32,768 max output tokens
- Function calling and structured outputs
- **Reasoning effort parameter**: Control the depth of reasoning for GPT-5 models
  - "minimal": Fastest, suitable for simple classification and extraction tasks
  - "medium": Default, balanced for general-purpose tasks
  - "high": Deepest reasoning for complex problem-solving and analysis

### Notes

- **IMAGE FORMAT LIMITATION**: Only supports png, jpeg, gif, webp formats (not bmp or other formats)
- Local image files in the workspace folder are automatically handled
- Images are base64 encoded for transmission
- For web URLs, pass them directly; for local files, use relative or absolute paths
- Both reasoning models have native multimodal capabilities
- **For any unsupported image format errors**: Convert the image to a supported format first
