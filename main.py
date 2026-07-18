import os
import time
import asyncio
from typing import AsyncGenerator, Annotated
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import jwt
from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

# 1. Load environment variables from the .env file
load_dotenv()

# 2. Configure JWT settings and Rate Limiter boundaries
JWT_SECRET = os.getenv("JWT_SECRET", "fallback-secret-key")  # Secret key for signing tokens
ALGORITHM = "HS256"  # Algorithm used for JWT encoding/decoding
RATE_LIMIT_LIMIT = 10  # Maximum number of requests allowed per window
RATE_LIMIT_WINDOW = 60  # Time window duration in seconds (60s = 1 minute)

app = FastAPI()

# 3. CORS Configuration to manage external frontend requests (Allows HTTP & HTTPS)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex="https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Initialize Authentication Scheme & LangGraph In-Memory Checkpointer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")  # Extracts the Bearer token from headers
memory = InMemorySaver()  # Saves chat session state temporarily in memory
rate_limit_store = {}  # Dictionary to track timestamps of requests per user


# 5. Define LangGraph State Schema (Data retained across conversation turns)
class ChatState(BaseModel):
    # Annotated with add_messages ensures new messages append to the history instead of overwriting it
    messages: Annotated[list, add_messages] = []
    cohort_id: str = ""
    user_id: str = ""


# 6. Chatbot Node (The functional step in the LangGraph workflow)
def chatbot_node(state: dict) -> dict:
    # Simulates a multi-turn response; Genuine RAG and knowledge retrieval will be integrated in Sprint 2
    return {
        "messages": [
            "Hello Bot [Stub Response]: This is a simulated multi-turn response for testing. Genuine RAG knowledge retrieval and citations will be integrated in Sprint 2."
        ]
    }


# 7. Construct and Compile the LangGraph Workflow (Conversation Flow)
workflow = StateGraph(dict)
workflow.add_node("chatbot", chatbot_node)  # Add the chatbot node
workflow.add_edge(START, "chatbot")  # Start node routes to chatbot node
workflow.add_edge("chatbot", END)  # Chatbot node routes to end of conversation
compiled_graph = workflow.compile(checkpointer=memory)  # Compile graph with memory checkpointer


# 8. Request Body Schema for the Chat Stream Endpoint
class ChatRequest(BaseModel):
    message: str  # The message sent by the user
    thread_id: str  # Unique identifier for the conversation session
    cohort_id: str  # The cohort group identifier of the user


# 9. Dependency to validate incoming JWT Token (Authentication)
def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        # Decode token to verify its signature and expiration
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        # Raises 401 Unauthorized if token is invalid or expired
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


# 10. Dependency to enforce Rate Limiting (Protection against spam)
def rate_limiter(request: Request, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("sub", request.client.host)  # Identify user by sub or fallback to IP
    now = time.time()  # Get current timestamp

    if user_id not in rate_limit_store:
        rate_limit_store[user_id] = []

    # Filter out requests that are older than the 60-second window (Sliding Window)
    rate_limit_store[user_id] = [t for t in rate_limit_store[user_id] if now - t < RATE_LIMIT_WINDOW]

    # Check if the user has exceeded the limit of 10 requests in the last minute
    if len(rate_limit_store[user_id]) >= RATE_LIMIT_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded. Max 10 requests per minute."
        )
    rate_limit_store[user_id].append(now)  # Log the timestamp of the current request


# 11. Login Endpoint to issue JWT access tokens
@app.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    payload = {
        "sub": form_data.username,
        "cohort_id": "alexandria-university-cohort-1",  # Stubbed cohort assigned during testing
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}


# 12. SSE Generator to yield stream tokens with artificial delay
async def sse_generator(response_text: str) -> AsyncGenerator[str, None]:
    for word in response_text.split(" "):
        yield f"data: {word} \n\n"  # Yield word in Server-Sent Events (SSE) format
        await asyncio.sleep(0.05)  # Yield flow control back to event loop (Non-blocking delay)


# 13. Secure, Rate-Limited Streaming Chat Endpoint
@app.post("/chat/stream", dependencies=[Depends(rate_limiter)])
async def chat_stream(payload: ChatRequest, current_user: dict = Depends(get_current_user)):
    user_cohort = current_user.get("cohort_id")

    # 403 Cohort Isolation: Enforce that users can only access their authorized cohort data
    if user_cohort != payload.cohort_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized access to this cohort data")

    config = {"configurable": {"thread_id": payload.thread_id}}  # Set up active session thread config
    state = compiled_graph.get_state(config)  # Retrieve saved graph state from memory checkpointer

    current_messages = []
    if state and state.values:
        current_messages = state.values.get("messages", [])  # Fetch history list of previous messages

    current_messages.append(payload.message)  # Append the user's new message to the list

    inputs = {"messages": current_messages, "cohort_id": payload.cohort_id, "user_id": current_user.get("sub")}

    # Invoke compiled workflow graph to process the message & generate response
    output = compiled_graph.invoke(inputs, config)
    bot_response = output["messages"][-1]  # Extract the latest response from the bot

    if hasattr(bot_response, "content"):
        bot_response = bot_response.content

    # Return streaming response using Server-Sent Events (SSE)
    return StreamingResponse(sse_generator(bot_response), media_type="text/event-stream")
