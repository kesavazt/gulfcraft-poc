from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from core.state import AgentState
from agents import (
    supervisor_node, search_node, refinement_node,
    selection_node, costing_node, status_node
)
from agents.edit_job import edit_job_node
from agents.quote_management import quote_management_node
from agents.job_lifecycle import job_lifecycle_node
from agents.pricing_advisor import pricing_advisor_node
from agents.explainer import explainer_node
from agents.vendor_info import vendor_info_node
from utils.tools import search_similar_quotations
from core.database import init_db

# --- Graph Construction ---
workflow = StateGraph(AgentState)
tool_node = ToolNode([search_similar_quotations])

# Add Nodes
workflow.add_node("Supervisor", supervisor_node)
workflow.add_node("SearchAgent", search_node)
workflow.add_node("Tools", tool_node)
workflow.add_node("RefinementAgent", refinement_node)
workflow.add_node("SelectionAgent", selection_node)
workflow.add_node("CostingAgent", costing_node)
workflow.add_node("StatusAgent", status_node)
workflow.add_node("EditJobAgent", edit_job_node)
workflow.add_node("QuoteManagementAgent", quote_management_node)
workflow.add_node("JobLifecycleAgent", job_lifecycle_node)
workflow.add_node("PricingAdvisorAgent", pricing_advisor_node)
workflow.add_node("ExplainerAgent", explainer_node)
workflow.add_node("VendorInfoAgent", vendor_info_node)

# Set entry point
workflow.set_entry_point("Supervisor")


# --- Routing Functions ---
def supervisor_router(state: AgentState) -> str:
    """Route from Supervisor to the next agent based on state."""
    return state.get("next", "FINISH")


# Supervisor routing (CostingAgent is not directly routable - only via SelectionAgent)
workflow.add_conditional_edges(
    "Supervisor",
    supervisor_router,
    {
        "SearchAgent": "SearchAgent",
        "SelectionAgent": "SelectionAgent",
        "StatusAgent": "StatusAgent",
        "EditJobAgent": "EditJobAgent",
        "QuoteManagementAgent": "QuoteManagementAgent",
        "JobLifecycleAgent": "JobLifecycleAgent",
        "PricingAdvisorAgent": "PricingAdvisorAgent",
        "ExplainerAgent": "ExplainerAgent",
        "VendorInfoAgent": "VendorInfoAgent",
        "FINISH": END
    }
)
workflow.add_edge("StatusAgent", END)
workflow.add_edge("EditJobAgent", END)
workflow.add_edge("QuoteManagementAgent", END)
workflow.add_edge("JobLifecycleAgent", END)
workflow.add_edge("PricingAdvisorAgent", END)
workflow.add_edge("ExplainerAgent", END)
workflow.add_edge("VendorInfoAgent", END)

# Search flow: SearchAgent -> Tools (if tool call) or RefinementAgent (if direct search)
def search_router(state):
    """Route based on whether SearchAgent made a tool call or direct search."""
    messages = state.get("messages", [])
    if messages:
        last_msg = messages[-1]
        # If the last message has tool_calls, go to Tools node
        if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
            return "Tools"
    # Otherwise go directly to RefinementAgent (for "show more" requests)
    return "RefinementAgent"

workflow.add_conditional_edges(
    "SearchAgent",
    search_router,
    {
        "Tools": "Tools",
        "RefinementAgent": "RefinementAgent"
    }
)
workflow.add_edge("Tools", "RefinementAgent")
workflow.add_edge("RefinementAgent", END)

# Selection flow: SelectionAgent -> CostingAgent or back to waiting
def selection_router(state):
    """Route based on whether a quotation was selected."""
    next_node = state.get("next")
    if next_node == "CostingAgent":
        return "CostingAgent"
    return "__end__"

workflow.add_conditional_edges(
    "SelectionAgent",
    selection_router,
    {
        "CostingAgent": "CostingAgent",
        "__end__": END
    }
)

# Costing flow: CostingAgent -> END
workflow.add_edge("CostingAgent", END)

# Compile the workflow
app = workflow.compile()


def invoke_agent(message: str, user_id: int = 1, threshold: float = 1000.0, conversation_history: list = None, session_state: dict = None, conversation_id: str = None):
    """
    Invoke the agent with a single message.
    Used by API endpoints for stateless invocations.

    Args:
        message: User's message
        user_id: User ID for the session
        threshold: Price threshold for items requiring quotes
        conversation_history: Optional list of previous messages for context
        session_state: Optional dict with persisted state (last_search_description, last_search_boat_model, current_top_k)
        conversation_id: Optional conversation ID for tracing (defaults to timestamp-based ID)

    Returns:
        dict with 'response' (str) and 'state' (dict) for maintaining conversation
    """
    from langchain_core.messages import HumanMessage, AIMessage
    from utils.langfuse_tracing import trace_context
    import uuid

    # Generate conversation_id if not provided (must be valid 32-char hex for Langfuse)
    if not conversation_id:
        conversation_id = uuid.uuid4().hex

    messages = []
    if conversation_history:
        for msg in conversation_history:
            if msg.get("role") == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg.get("role") == "assistant":
                messages.append(AIMessage(content=msg["content"]))

    messages.append(HumanMessage(content=message))

    inputs = {
        "messages": messages,
        "user_id": user_id,
        "threshold": threshold
    }

    # Add persisted session state if available
    if session_state:
        if session_state.get("last_search_description"):
            inputs["last_search_description"] = session_state["last_search_description"]
        if session_state.get("last_search_boat_model"):
            inputs["last_search_boat_model"] = session_state["last_search_boat_model"]
        if session_state.get("current_top_k"):
            inputs["current_top_k"] = session_state["current_top_k"]
        if session_state.get("selected_quotation"):
            inputs["selected_quotation"] = session_state["selected_quotation"]
        if session_state.get("similar_quotations"):
            inputs["similar_quotations"] = session_state["similar_quotations"]
        if session_state.get("awaiting_selection") is not None:
            inputs["awaiting_selection"] = session_state["awaiting_selection"]
        # Context tracking fields
        if session_state.get("last_mentioned_job_id"):
            inputs["last_mentioned_job_id"] = session_state["last_mentioned_job_id"]
        if session_state.get("last_action"):
            inputs["last_action"] = session_state["last_action"]
        if session_state.get("last_vendor_email"):
            inputs["last_vendor_email"] = session_state["last_vendor_email"]


    response_messages = []
    final_state = {}

    # Wrap entire agent execution in trace context
    with trace_context(conversation_id, user_id=user_id, metadata={"message": message, "threshold": threshold}):
        for output in app.stream(inputs):
            for _, value in output.items():
                final_state.update(value)
                if 'messages' in value:
                    for msg in value["messages"]:
                        if isinstance(msg, AIMessage) and msg.content:
                            response_messages.append(msg.content)

    return {
        "response": "\n".join(response_messages),
        "state": {
            "awaiting_selection": final_state.get("awaiting_selection", False),
            "job_id": final_state.get("job_id"),
            "emails_sent": final_state.get("emails_sent", False),
            "awaiting_quotes": final_state.get("awaiting_quotes", False),
            "generated_file": final_state.get("generated_file"),
            "sharepoint_url": final_state.get("sharepoint_url"),
            "last_search_description": final_state.get("last_search_description"),
            "last_search_boat_model": final_state.get("last_search_boat_model"),
            "current_top_k": final_state.get("current_top_k"),
            "similar_quotations": final_state.get("similar_quotations"),
            "selected_quotation": final_state.get("selected_quotation"),
            # Context tracking
            "last_mentioned_job_id": final_state.get("last_mentioned_job_id"),
            "last_action": final_state.get("last_action"),
            "last_vendor_email": final_state.get("last_vendor_email")
        }

    }


def run_interactive():
    """
    Run the agent in interactive terminal mode.
    Supports multi-turn conversations with user input.
    """
    from langchain_core.messages import HumanMessage, AIMessage

    print("=" * 60)
    print("Gulf Craft Costing Agent - Interactive Mode")
    print("=" * 60)
    print("Type 'quit' or 'exit' to end the conversation.")
    print("Type 'reset' to start a new conversation.")
    print("-" * 60)

    conversation_history = []
    session_state = {}  # Persist search state across turns
    user_id = 1
    threshold = 1000.0

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ['quit', 'exit']:
            print("Goodbye!")
            break

        if user_input.lower() == 'reset':
            conversation_history = []
            session_state = {}
            print("\n[Conversation reset. Starting fresh.]\n")
            continue

        # Build messages list with history
        messages = []
        for msg in conversation_history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            else:
                messages.append(AIMessage(content=msg["content"]))

        messages.append(HumanMessage(content=user_input))

        inputs = {
            "messages": messages,
            "user_id": user_id,
            "threshold": threshold
        }

        # Add persisted session state
        if session_state.get("last_search_description"):
            inputs["last_search_description"] = session_state["last_search_description"]
        if session_state.get("last_search_boat_model"):
            inputs["last_search_boat_model"] = session_state["last_search_boat_model"]
        if session_state.get("current_top_k"):
            inputs["current_top_k"] = session_state["current_top_k"]

        print("\nAgent: ", end="", flush=True)

        response_parts = []
        final_state = {}
        for output in app.stream(inputs):
            for _, value in output.items():
                final_state.update(value)
                if 'messages' in value:
                    for msg in value["messages"]:
                        if hasattr(msg, 'content') and msg.content:
                            print(msg.content)
                            response_parts.append(msg.content)

        # Update session state with search parameters
        if final_state.get("last_search_description"):
            session_state["last_search_description"] = final_state["last_search_description"]
        if final_state.get("last_search_boat_model"):
            session_state["last_search_boat_model"] = final_state["last_search_boat_model"]
        if final_state.get("current_top_k"):
            session_state["current_top_k"] = final_state["current_top_k"]

        # Add to conversation history
        conversation_history.append({"role": "user", "content": user_input})
        if response_parts:
            conversation_history.append({"role": "assistant", "content": "\n".join(response_parts)})


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        # Single test run (non-interactive)
        test_message = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "I need a quotation for boat polishing work. My boat model is MAJESTY62"

        print(f"Test message: {test_message}\n")
        result = invoke_agent(test_message)
        print(f"Response:\n{result['response']}")
        print(f"\nState: {result['state']}")
    else:
        import tools
        #results = tools.search_similar_quotations('At Sundeck The coffee machine needs a sliding mechanism for better use. And need additional sockets inside forward portside storage cabinet.','MAJESTY120')
        #print(results)
        #exit()
        # Interactive mode
        # Give me a quotation for polishing work. My boat model is MAJESTY62
        # I want to get my boat's chiller system chemically cleaned. Give me a quotation. My boat model is NA
        # Give me a quotation for the following job description: Installation of Dinghy stand and set the Dinghy. My boat model is MAJESTY125
        # Give me a quotation. Description: "At Sundeck The coffee machine needs a sliding mechanism for better use. And need additional sockets inside forward portside storage cabinet." My boat model is MAJESTY120
        run_interactive()
