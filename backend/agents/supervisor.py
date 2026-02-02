"""
Supervisor Agent Node

Routes user requests to appropriate worker agents based on intent.
"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage
from core.state import AgentState
from utils.llm import llm
from utils.prompts import SUPERVISOR_SYSTEM_PROMPT
from utils import tools
from utils.langfuse_tracing import trace_agent


# --- Supervisor Configuration ---

# CostingAgent is not directly routable from Supervisor - only via SelectionAgent
ROUTABLE_MEMBERS = [
    "SearchAgent",
    "SelectionAgent",
    "StatusAgent",
    "EditJobAgent",
    "QuoteManagementAgent",
    "JobLifecycleAgent",
    "PricingAdvisorAgent",
    "ExplainerAgent",
    "VendorInfoAgent"
]
OPTIONS = ["FINISH"] + ROUTABLE_MEMBERS

ROUTE_FUNCTION_DEF = {
    "name": "route",
    "description": "Select the next role.",
    "parameters": {
        "title": "routeSchema",
        "type": "object",
        "properties": {
            "next": {
                "title": "Next",
                "anyOf": [{"enum": OPTIONS}],
            },
            "greeting_response": {
                "title": "GreetingResponse",
                "type": "string",
                "description": "Response to the user when no worker is selected (e.g., greetings, asking for missing information)"
            }
        },
        "required": ["next"],
    },
}

# Build the supervisor chain
_prompt = ChatPromptTemplate.from_messages([
    ("system", SUPERVISOR_SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="messages"),
    ("system", "Given the conversation above, who should act next? Or should we FINISH? Select one of: {options}"),
]).partial(options=str(OPTIONS), members=", ".join(ROUTABLE_MEMBERS))

_supervisor_chain = _prompt | llm.with_structured_output(ROUTE_FUNCTION_DEF)


@trace_agent
def supervisor_node(state: AgentState):
    """
    Supervisor node that routes user requests to appropriate worker agents.
    
    Returns:
        dict with 'next' key indicating the next agent, and optionally 'messages' for greetings.
    """
    trace_input = {"messages_count": len(state.get("messages", []))}
    try:
        result = _supervisor_chain.invoke(state)
    except Exception as e:
        raise

    # If it's a greeting or info request, add the response to messages
    if result["next"] == "FINISH" and result.get("greeting_response"):
        return {
            "next": result["next"],
            "messages": [AIMessage(content=result["greeting_response"])]
        }

    return {"next": result["next"]}
