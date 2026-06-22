from typing import Any
from dotenv import load_dotenv

import chainlit as cl

from langchain.agents import AgentState, create_agent
from langchain.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from langchain.agents.middleware import after_agent
from langchain_google_genai import ChatGoogleGenerativeAI

from langgraph.runtime import Runtime

from prompt import systemPrompt

load_dotenv()

model = ChatGoogleGenerativeAI(model="gemma-4-26b-a4b-it")

@after_agent(can_jump_to=["end"])
def safety_guardrail(state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
    """Model-based guardrail: Use an LLM to evaluate response safety."""
    # Get the final AI response
    if not state["messages"]:
        return None

    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return None

    # Use a model to evaluate safety
    safety_prompt = f"""Evaluate if this response is safe and appropriate.
    Respond with only 'SAFE' or 'UNSAFE'.

    Response: {last_message.content}"""

    result = model.invoke([{"role": "user", "content": safety_prompt}])

    if "UNSAFE" in result.content:
        last_message.content = "I cannot provide that response. Please rephrase your request."

    return None

agent = create_agent(model=model, middleware=[safety_guardrail])

@cl.on_chat_start
def start_chat():
    cl.user_session.set(
        "message_history",
        [SystemMessage(systemPrompt)],
    )

@cl.on_message
async def main(message: cl.Message):
    message_history = cl.user_session.get("message_history")
    user_msg = HumanMessage(content=message.content)
    message_history.append(user_msg)
    
    input_data = {"messages": message_history}
    msg = cl.Message(content="")
    await msg.send()
    
    # version="v2" is recommended for the latest event structure
    async for event in agent.astream_events(input_data, version="v2"):
        # The event structure: event["event"] tells you what happened
        if event["event"] == "on_chat_model_stream":
            # This event carries a chunk of the AI's response
            chunk = event["data"]["chunk"]
            if isinstance(chunk, AIMessageChunk):
                # Stream the text part of the chunk
                content = chunk.content
                if isinstance(content, list):
                    for block in content:
                        if block.get("type") == "text":
                            await msg.stream_token(block.get("text", ""))
                else:
                    await msg.stream_token(str(content))
    

    
    assistant_msg = AIMessage(content=msg.content)
    message_history.append(assistant_msg)
    await msg.update()