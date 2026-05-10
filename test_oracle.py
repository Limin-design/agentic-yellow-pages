class ChatRequest(BaseModel):
    messages: list[Message] = Field(default_factory=list)
    prompt: str | None = None   # ADD THIS: Allow simple string prompts
    query: str | None = None    # ADD THIS: Allow 'query' payloads
    session_id: str | None = None

# ... scroll down to the endpoint ...

@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest) -> ChatResponse:
    # 1. Try to extract from simple 'prompt' or 'query' first
    user_prompt = payload.prompt or payload.query or ""
    
    # 2. If empty, try to extract from the 'messages' array
    if not user_prompt and payload.messages:
        for msg in reversed(payload.messages):
            if msg.role == "user":
                user_prompt = msg.content
                break

    if not user_prompt:
        return ChatResponse(response="No user message received.")
